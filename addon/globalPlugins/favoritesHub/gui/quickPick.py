# Favorites Hub — NVDA 2026.1 Global Plugin
# gui/quickPick.py: Borderless always-on-top fuzzy-search overlay (§6.5).
#
# Design rules (§6.5):
#   • wx.Frame with FRAME_NO_TASKBAR | STAY_ON_TOP | BORDER_SIMPLE.
#   • Centered on the active monitor using the mouse cursor position.
#   • Captures previously focused window; restores it on close.
#   • Closes automatically when the frame loses activation.
#   • Fuzzy scoring: fuzzy.score(query, entry.name)*2 + score(query, tags_str).
#   • Enter activates top result / current selection.
#   • Up/Down arrow moves selection without leaving the TextCtrl.
#   • Escape closes.
#   • Singleton: calling show_singleton while already open raises the frame.
#
# Thread-safety: all methods MUST be called on the GUI thread (§5).
#
# Copyright (C) 2026 1EyeBiney
# This file is covered by the GNU General Public License version 2.
# See the file COPYING for more details.

from __future__ import annotations

from typing import Any

import addonHandler
import wx
from logHandler import log

from ..constants import CATEGORY_KEYS, CATEGORY_LABELS
from . import widgets as _w
from .tagsView import _dispatch_activate

addonHandler.initTranslation()

# ---------------------------------------------------------------------------
# Singleton reference (module-level, GUI thread only)
# ---------------------------------------------------------------------------

_instance: "QuickPickFrame | None" = None

# Frame dimensions
_FRAME_WIDTH: int = 700
_FRAME_HEIGHT: int = 420


class QuickPickFrame(wx.Frame):
    """Borderless fuzzy-search overlay for Favorites Hub (§6.5)."""

    # ------------------------------------------------------------------
    # Singleton factory
    # ------------------------------------------------------------------

    @classmethod
    def show_singleton(cls, parent: wx.Window) -> None:
        """Show the QuickPick overlay, or raise it if already visible.

        MUST be called on the GUI thread via wx.CallAfter.
        """
        global _instance
        if _instance is not None and _instance.IsShown():
            _instance.Raise()
            _instance.SetFocus()
            return

        _instance = cls(parent)
        _instance.Show()
        _instance.Raise()

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(
            parent,
            style=(
                wx.FRAME_NO_TASKBAR
                | wx.STAY_ON_TOP
                | wx.BORDER_SIMPLE
                | wx.FRAME_FLOAT_ON_PARENT
            ),
        )

        # Translators: Title of the Quick-Pick overlay (used for accessibility)
        self.SetTitle(_("Favorites Hub Quick-Pick"))

        # Capture the currently focused window so we can restore it on close
        self._prior_focus: wx.Window | None = wx.Window.FindFocus()

        # Internal state
        self._results: list[tuple[str, Any]] = []  # (category_key, entry)

        self._setup_ui()
        self._center_on_active_monitor()
        self._bind_events()

        # Populate with everything on first open (empty query shows all entries)
        self._update_results("")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        mainPanel = wx.Panel(self)
        mainSizer = wx.BoxSizer(wx.VERTICAL)

        # Search TextCtrl
        searchSizer = wx.BoxSizer(wx.HORIZONTAL)

        # Translators: Label for the search box in the Favorites Hub Quick-Pick overlay
        searchLabel = wx.StaticText(mainPanel, label=_("&Search:"))
        self._searchCtrl = wx.TextCtrl(mainPanel)
        # Translators: Accessible name for the search box in Quick-Pick
        self._searchCtrl.SetName(_("Search"))

        searchSizer.Add(searchLabel, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        searchSizer.Add(self._searchCtrl, 1, wx.EXPAND)
        mainSizer.Add(searchSizer, 0, wx.EXPAND | wx.ALL, 8)

        # Results ListCtrl
        columns: list[tuple[str, int]] = [
            # Translators: Column header "Name" in the Quick-Pick results list
            (_("Name"), 260),
            # Translators: Column header "Category" in the Quick-Pick results list
            (_("Category"), 120),
            # Translators: Column header "Tags" in the Quick-Pick results list
            (_("Tags"), 200),
        ]
        self._listCtrl = _w.FavoritesListCtrl(mainPanel, columns)
        # Translators: Accessible name for the results list in Quick-Pick
        self._listCtrl.SetName(_("Results"))
        mainSizer.Add(self._listCtrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Status / hint text
        self._hintLabel = wx.StaticText(
            mainPanel,
            # Translators: Hint text at the bottom of the Quick-Pick overlay
            label=_(
                "Enter: activate  \u2191\u2193: move  Esc: close"
            ),
        )
        mainSizer.Add(self._hintLabel, 0, wx.LEFT | wx.BOTTOM, 8)

        mainPanel.SetSizer(mainSizer)

        frameSizer = wx.BoxSizer(wx.VERTICAL)
        frameSizer.Add(mainPanel, 1, wx.EXPAND)
        self.SetSizer(frameSizer)
        self.SetClientSize(wx.Size(_FRAME_WIDTH, _FRAME_HEIGHT))

    def _center_on_active_monitor(self) -> None:
        """Position the frame at the centre of the monitor under the mouse."""
        try:
            display_idx = wx.Display.GetFromPoint(wx.GetMousePosition())
            if display_idx < 0:
                display_idx = 0
            rect = wx.Display(display_idx).GetClientArea()
            x = rect.x + (rect.Width - _FRAME_WIDTH) // 2
            y = rect.y + (rect.Height - _FRAME_HEIGHT) // 2
            self.Move(x, y)
        except Exception as exc:
            log.debugWarning("Favorites Hub QuickPick: centering failed: %s", exc)
            self.Center()

    # ------------------------------------------------------------------
    # Event binding
    # ------------------------------------------------------------------

    def _bind_events(self) -> None:
        self._searchCtrl.Bind(wx.EVT_TEXT, self._on_search_text)
        self._searchCtrl.Bind(wx.EVT_KEY_DOWN, self._on_search_key_down)
        self._listCtrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_list_activated)
        self._listCtrl.Bind(wx.EVT_KEY_DOWN, self._on_list_key_down)
        self.Bind(wx.EVT_ACTIVATE, self._on_activate)
        self.Bind(wx.EVT_CLOSE, self._on_close)

    # ------------------------------------------------------------------
    # Fuzzy search
    # ------------------------------------------------------------------

    def _update_results(self, query: str) -> None:
        """Score all entries against *query* and refresh the ListCtrl."""
        try:
            from ..fuzzy import score as _score
            from ..storage import get_document, hydrate_document

            doc = get_document()
            hydrated = hydrate_document(doc)

            # Build key → Category label reverse map
            key_to_cat = {v: k for k, v in CATEGORY_KEYS.items()}

            scored: list[tuple[float, str, Any]] = []
            for key, entries in hydrated.items():
                for entry in entries:
                    tags_str = " ".join(entry.tags)
                    if query:
                        s = _score(query, entry.name) * 2.0 + _score(query, tags_str)
                        if s <= 0.0:
                            continue
                    else:
                        # Empty query: show all entries, sorted by name
                        s = 0.0
                    scored.append((s, key, entry))

            if query:
                scored.sort(key=lambda x: x[0], reverse=True)
            else:
                scored.sort(key=lambda x: x[2].name.lower())

            # Limit to top 100 results for performance
            self._results = [(key, entry) for _, key, entry in scored[:100]]

            def row_factory(pair: tuple[str, Any]) -> list[str]:
                key, entry = pair
                cat = key_to_cat.get(key)
                cat_label = CATEGORY_LABELS.get(cat, key) if cat else key
                return [entry.name, cat_label, ", ".join(entry.tags)]

            self._listCtrl.set_entries(self._results, row_factory)

        except Exception as exc:
            log.error("Favorites Hub QuickPick._update_results: %s", exc)

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    def _activate_selection(self) -> None:
        """Activate the selected entry and close the overlay."""
        idx = self._listCtrl.get_selected_index()
        if idx < 0 or idx >= len(self._results):
            # If nothing is explicitly selected, use item 0
            if self._results:
                idx = 0
            else:
                return

        key, entry = self._results[idx]
        self._close()
        # Dispatch after closing so activation happens in the correct window context
        wx.CallAfter(_dispatch_activate, key, entry)

    def _close(self) -> None:
        """Hide the frame and restore the previously focused window."""
        global _instance
        self.Hide()
        _instance = None
        if self._prior_focus:
            try:
                if self._prior_focus.IsShown():
                    self._prior_focus.SetFocus()
            except Exception:
                pass
        self.DestroyLater()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_search_text(self, event: wx.CommandEvent) -> None:
        try:
            self._update_results(self._searchCtrl.GetValue())
        except Exception as exc:
            log.error("Favorites Hub QuickPick._on_search_text: %s", exc)
        event.Skip()

    def _on_search_key_down(self, event: wx.KeyEvent) -> None:
        """Handle Up/Down/Enter/Escape in the search TextCtrl."""
        key = event.GetKeyCode()

        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            try:
                self._activate_selection()
            except Exception as exc:
                log.error("Favorites Hub QuickPick enter: %s", exc)
            return  # consume key

        elif key == wx.WXK_ESCAPE:
            self._close()
            return  # consume key

        elif key == wx.WXK_DOWN:
            try:
                self._listCtrl.move_selection(+1)
            except Exception as exc:
                log.error("Favorites Hub QuickPick down: %s", exc)
            return  # consume key

        elif key == wx.WXK_UP:
            try:
                self._listCtrl.move_selection(-1)
            except Exception as exc:
                log.error("Favorites Hub QuickPick up: %s", exc)
            return  # consume key

        else:
            event.Skip()

    def _on_list_activated(self, event: wx.ListEvent) -> None:
        try:
            self._activate_selection()
        except Exception as exc:
            log.error("Favorites Hub QuickPick list activate: %s", exc)
        event.Skip()

    def _on_list_key_down(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            try:
                self._activate_selection()
            except Exception as exc:
                log.error("Favorites Hub QuickPick list enter: %s", exc)
        elif key == wx.WXK_ESCAPE:
            self._close()
        else:
            event.Skip()

    def _on_activate(self, event: wx.ActivateEvent) -> None:
        """Close the overlay when it loses focus to another application."""
        if not event.GetActive():
            # wx.CallAfter so the deactivate event fully processes first
            wx.CallAfter(self._on_deactivated_idle)
        event.Skip()

    def _on_deactivated_idle(self) -> None:
        """Called via wx.CallAfter after the frame has been deactivated."""
        global _instance
        if _instance is self and not self.IsActive():
            self._close()

    def _on_close(self, event: wx.CloseEvent) -> None:
        self._close()
        # Don't call event.Skip() — we handle destruction ourselves via DestroyLater
