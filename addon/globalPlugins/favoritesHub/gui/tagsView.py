# Favorites Hub — NVDA 2026.1 Global Plugin
# gui/tagsView.py: Page 6 of the Listbook — aggregate tag-based view.
#
# Layout:
#   Left  (proportion 1): labelled wx.ListBox of sorted unique tags.
#   Right (proportion 2): labelled virtual FavoritesListCtrl showing all
#                         entries that carry the selected tag (Name, Category,
#                         Tags columns).
#
# Activating an entry on this page dispatches to the same handler as the
# entry's native category page (open folder / open link / copy snippet /
# run CLI / play macro).
#
# Thread-safety: all methods MUST be called on the GUI thread (§5).
#
# Copyright (C) 2026 1EyeBiney
# This file is covered by the GNU General Public License version 2.
# See the file COPYING for more details.

from __future__ import annotations

import os
from typing import Any

import addonHandler
import gui
import ui
import wx
from logHandler import log

from ..constants import (
    CATEGORY_KEYS,
    CATEGORY_LABELS,
    Category,
)
from ..schema import (
    CliEntry,
    FolderEntry,
    LinkEntry,
    MacroEntry,
    SnippetEntry,
)
from . import widgets as _w

addonHandler.initTranslation()


class TagsView(wx.Panel):
    """Split-panel view for page 6 of the Favorites Hub Listbook (§6.1)."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent)
        # List of (category_key, entry) pairs across all content categories
        self._all_entries: list[tuple[str, Any]] = []
        # Subset currently visible on the right list
        self._visible_entries: list[tuple[str, Any]] = []
        self._setup_ui()
        self._bind_events()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        mainSizer = wx.BoxSizer(wx.HORIZONTAL)

        # ---- Left pane: tag list ----
        leftSizer = wx.BoxSizer(wx.VERTICAL)

        # Translators: Label for the tags list on the Tags page of Favorites Hub
        tagsLabel = wx.StaticText(self, label=_("&Tags:"))
        leftSizer.Add(tagsLabel, 0, wx.BOTTOM, 3)

        self._tagsListBox = wx.ListBox(self, style=wx.LB_SINGLE)
        # Translators: Accessible name for the tags list on the Tags page
        self._tagsListBox.SetName(_("Tags"))
        leftSizer.Add(self._tagsListBox, 1, wx.EXPAND)

        mainSizer.Add(leftSizer, 1, wx.EXPAND | wx.ALL, 5)

        # ---- Right pane: entries matching selected tag ----
        rightSizer = wx.BoxSizer(wx.VERTICAL)

        # Translators: Label for the entries list on the Tags page of Favorites Hub
        entriesLabel = wx.StaticText(self, label=_("&Entries:"))
        rightSizer.Add(entriesLabel, 0, wx.BOTTOM, 3)

        columns: list[tuple[str, int]] = [
            # Translators: Column header "Name" on the Tags page
            (_("Name"), 220),
            # Translators: Column header "Category" on the Tags page
            (_("Category"), 120),
            # Translators: Column header "Tags" on the Tags page
            (_("Tags"), 200),
        ]
        self._entriesListCtrl = _w.FavoritesListCtrl(self, columns)
        # Translators: Accessible name for the entries list on the Tags page
        self._entriesListCtrl.SetName(_("Entries"))
        rightSizer.Add(self._entriesListCtrl, 1, wx.EXPAND)

        # ---- Action buttons ----
        btnSizer = wx.BoxSizer(wx.HORIZONTAL)

        # Translators: Button to activate (open/run/copy) the selected entry
        # on the Tags page of Favorites Hub
        self._activateBtn = wx.Button(self, label=_("A&ctivate"))
        btnSizer.Add(self._activateBtn, 0, wx.RIGHT, 5)

        rightSizer.Add(btnSizer, 0, wx.TOP, 5)
        mainSizer.Add(rightSizer, 2, wx.EXPAND | wx.ALL, 5)

        self.SetSizer(mainSizer)

    def _bind_events(self) -> None:
        self._tagsListBox.Bind(wx.EVT_LISTBOX, self._on_tag_selected)
        self._entriesListCtrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_entry_activated)
        self._activateBtn.Bind(wx.EVT_BUTTON, self._on_activate_button)
        self._entriesListCtrl.Bind(wx.EVT_KEY_DOWN, self._on_list_key_down)

    # ------------------------------------------------------------------
    # Data refresh — called by the main dialog on page switch and after
    # any mutation in another category page.
    # ------------------------------------------------------------------

    def refresh(self, doc: dict) -> None:
        """Rebuild the tag list and entry cache from the in-memory document.

        Preserves the currently selected tag when possible.
        """
        try:
            self._rebuild_from_doc(doc)
        except Exception as exc:
            log.error("Favorites Hub TagsView.refresh: %s", exc)

    def _rebuild_from_doc(self, doc: dict) -> None:
        from ..storage import hydrate_document

        hydrated = hydrate_document(doc)

        # Build flat list of (key, entry) and collect tag universe
        self._all_entries = []
        tag_set: set[str] = set()

        for key in ("folders", "links", "snippets", "clis", "macros"):
            for entry in hydrated.get(key, []):
                self._all_entries.append((key, entry))
                for tag in entry.tags:
                    tag_set.add(tag.lower())

        # Preserve current tag selection
        current_tag = self._get_selected_tag()

        # Rebuild the tag ListBox (sorted, case-normalised to lower)
        self._tagsListBox.Clear()
        for tag in sorted(tag_set):
            self._tagsListBox.Append(tag)

        # Restore or default selection
        if current_tag:
            idx = self._tagsListBox.FindString(current_tag, caseSensitive=False)
            if idx != wx.NOT_FOUND:
                self._tagsListBox.SetSelection(idx)
            elif self._tagsListBox.GetCount() > 0:
                self._tagsListBox.SetSelection(0)
        elif self._tagsListBox.GetCount() > 0:
            self._tagsListBox.SetSelection(0)

        self._update_entries_list()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_selected_tag(self) -> str | None:
        idx = self._tagsListBox.GetSelection()
        if idx == wx.NOT_FOUND:
            return None
        return self._tagsListBox.GetString(idx)

    def _update_entries_list(self) -> None:
        """Filter the right ListCtrl to match the currently selected tag."""
        selected_tag = self._get_selected_tag()

        if selected_tag is not None:
            self._visible_entries = [
                (key, entry)
                for key, entry in self._all_entries
                if any(t.lower() == selected_tag for t in entry.tags)
            ]
        else:
            # No tag selected: show everything
            self._visible_entries = list(self._all_entries)

        # Build key → Category reverse map
        key_to_cat = {v: k for k, v in CATEGORY_KEYS.items()}

        def row_factory(pair: tuple[str, Any]) -> list[str]:
            key, entry = pair
            cat = key_to_cat.get(key)
            cat_label = CATEGORY_LABELS.get(cat, key) if cat else key
            return [entry.name, cat_label, ", ".join(entry.tags)]

        self._entriesListCtrl.set_entries(self._visible_entries, row_factory)

    # ------------------------------------------------------------------
    # Activation dispatch
    # ------------------------------------------------------------------

    def _activate_selected(self) -> None:
        """Activate the currently selected entry using its native category logic."""
        idx = self._entriesListCtrl.get_selected_index()
        if idx < 0 or idx >= len(self._visible_entries):
            return
        key, entry = self._visible_entries[idx]
        _dispatch_activate(key, entry)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_tag_selected(self, event: wx.CommandEvent) -> None:
        try:
            self._update_entries_list()
        except Exception as exc:
            log.error("Favorites Hub TagsView._on_tag_selected: %s", exc)
        event.Skip()

    def _on_entry_activated(self, event: wx.ListEvent) -> None:
        try:
            self._activate_selected()
        except Exception as exc:
            log.error("Favorites Hub TagsView._on_entry_activated: %s", exc)
        event.Skip()

    def _on_activate_button(self, event: wx.CommandEvent) -> None:
        try:
            self._activate_selected()
        except Exception as exc:
            log.error("Favorites Hub TagsView._on_activate_button: %s", exc)

    def _on_list_key_down(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            try:
                self._activate_selected()
            except Exception as exc:
                log.error("Favorites Hub TagsView._on_list_key_down: %s", exc)
        else:
            event.Skip()


# ---------------------------------------------------------------------------
# Category activation dispatch (shared between TagsView and mainDialog)
# ---------------------------------------------------------------------------

def _dispatch_activate(category_key: str, entry: Any) -> None:
    """Route activation to the correct handler based on category key."""
    try:
        if category_key == "folders":
            _activate_folder(entry)
        elif category_key == "links":
            _activate_link(entry)
        elif category_key == "snippets":
            _activate_snippet(entry)
        elif category_key == "clis":
            _activate_cli(entry)
        elif category_key == "macros":
            _activate_macro(entry)
        else:
            log.warning("Favorites Hub: unknown category key %r for activation.", category_key)
    except Exception as exc:
        log.error("Favorites Hub _dispatch_activate(%r): %s", category_key, exc)
        gui.messageBox(
            # Translators: Error message shown when activating an entry fails.
            # {error} is the error description.
            _("Could not activate the entry:\n{error}").format(error=str(exc)),
            # Translators: Title of the activation error dialog
            _("Favorites Hub — Activation Error"),
            wx.OK | wx.ICON_ERROR,
        )


def _activate_folder(entry: FolderEntry) -> None:
    """Open the folder in Windows Explorer."""
    try:
        os.startfile(entry.path)
        log.debug("Favorites Hub: opened folder %r", entry.path)
    except OSError as exc:
        log.error("Favorites Hub: cannot open folder %r: %s", entry.path, exc)
        gui.messageBox(
            # Translators: Message shown when a folder cannot be opened.
            # {path} is the folder path; {error} is the OS error.
            _("Could not open folder:\n{path}\n\n{error}").format(
                path=entry.path, error=str(exc)
            ),
            # Translators: Title of the open-folder error dialog
            _("Favorites Hub — Open Failed"),
            wx.OK | wx.ICON_ERROR,
        )


def _activate_link(entry: LinkEntry) -> None:
    """Open the URL in the system default browser (or mail client for mailto:)."""
    try:
        os.startfile(entry.url)
        log.debug("Favorites Hub: opened link %r", entry.url)
    except OSError as exc:
        log.error("Favorites Hub: cannot open link %r: %s", entry.url, exc)
        gui.messageBox(
            # Translators: Message shown when a link cannot be opened.
            # {url} is the URL; {error} is the OS error.
            _("Could not open link:\n{url}\n\n{error}").format(
                url=entry.url, error=str(exc)
            ),
            # Translators: Title of the open-link error dialog
            _("Favorites Hub — Open Failed"),
            wx.OK | wx.ICON_ERROR,
        )


def _activate_snippet(entry: SnippetEntry) -> None:
    """Expand tokens and place the result on the clipboard."""
    from ..snippets import expand_and_copy
    expand_and_copy(entry)


def _activate_cli(entry: CliEntry) -> None:
    """Launch the CLI command in a background daemon thread."""
    from ..cli import execute
    execute(entry)


def _activate_macro(entry: MacroEntry) -> None:
    """Begin macro keystroke playback (GUI thread, wx.CallLater chain)."""
    from ..macros import play
    play(entry)
