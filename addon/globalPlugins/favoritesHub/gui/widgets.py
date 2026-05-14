# Favorites Hub — NVDA 2026.1 Global Plugin
# gui/widgets.py: Shared GUI primitives used across all pages of the Hub.
#
# Exports:
#   FavoritesListCtrl  — virtual-mode wx.ListCtrl with built-in filter support
#                        and typed entry association.
#
# Thread-safety: all methods MUST be called on the GUI thread (§5).
#
# Copyright (C) 2026 1EyeBiney
# This file is covered by the GNU General Public License version 2.
# See the file COPYING for more details.

from __future__ import annotations

from typing import Any, Callable

import addonHandler
import wx
from logHandler import log

addonHandler.initTranslation()


class FavoritesListCtrl(wx.ListCtrl):
    """Virtual-mode report-view ListCtrl with integrated filter and entry binding.

    Usage::

        cols = [(_("Name"), 200), (_("Path"), 300), (_("Tags"), 150)]
        lc = FavoritesListCtrl(parent, cols)
        lc.set_entries(entries, lambda e: [e.name, e.path, ", ".join(e.tags)])
        lc.apply_filter("docs")

    MUST be called on the GUI thread.
    """

    def __init__(
        self,
        parent: wx.Window,
        columns: list[tuple[str, int]],
    ) -> None:
        super().__init__(
            parent,
            style=wx.LC_REPORT | wx.LC_VIRTUAL | wx.LC_SINGLE_SEL,
        )

        for i, (header, width) in enumerate(columns):
            self.InsertColumn(i, header, width=width)

        # Full (unfiltered) data
        self._all_entries: list[Any] = []
        self._all_rows: list[list[str]] = []

        # Currently visible (filtered) data — what OnGetItemText draws from
        self._filtered_entries: list[Any] = []
        self._filtered_rows: list[list[str]] = []

        # Row factory stored so set_entries can be called without repeating it
        self._row_factory: Callable[[Any], list[str]] = lambda _e: []

        # Current filter query (lowercased)
        self._current_filter: str = ""

    # ------------------------------------------------------------------
    # wx virtual ListCtrl required override
    # ------------------------------------------------------------------

    def OnGetItemText(self, item: int, col: int) -> str:
        """Called by wxPython to retrieve the text for a cell in virtual mode."""
        try:
            return self._filtered_rows[item][col]
        except IndexError:
            return ""

    # ------------------------------------------------------------------
    # Data management
    # ------------------------------------------------------------------

    def set_entries(
        self,
        entries: list[Any],
        row_factory: Callable[[Any], list[str]],
    ) -> None:
        """Replace the full entry list and rebuild the visible rows.

        Parameters
        ----------
        entries:
            List of typed entry objects (FolderEntry, LinkEntry, etc.) or
            any object whose fields the *row_factory* knows how to access.
        row_factory:
            Callable that accepts a single entry and returns a ``list[str]``
            with one element per column.
        """
        self._row_factory = row_factory
        self._all_entries = list(entries)
        self._all_rows = [row_factory(e) for e in self._all_entries]
        self._rebuild_filter()

    def apply_filter(self, text: str) -> None:
        """Narrow the visible rows to those whose columns contain *text*.

        An empty *text* clears the filter and shows all rows.
        The search is case-insensitive and checks every column.
        """
        self._current_filter = text.strip().lower()
        self._rebuild_filter()

    def _rebuild_filter(self) -> None:
        """Recompute ``_filtered_*`` from ``_all_*`` and the current query."""
        q = self._current_filter
        if q:
            pairs: list[tuple[Any, list[str]]] = [
                (e, r)
                for e, r in zip(self._all_entries, self._all_rows)
                if any(q in col.lower() for col in r)
            ]
        else:
            pairs = list(zip(self._all_entries, self._all_rows))

        self._filtered_entries = [p[0] for p in pairs]
        self._filtered_rows = [p[1] for p in pairs]

        count = len(self._filtered_rows)
        self.SetItemCount(count)

        if count > 0:
            # Restore selection to first visible item after a filter change
            self.Select(0, True)
            self.Focus(0)
            self.EnsureVisible(0)

        self.Refresh()

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------

    def get_selected_entry(self) -> Any | None:
        """Return the entry object corresponding to the currently selected row.

        Returns ``None`` when nothing is selected or the list is empty.
        """
        idx = self.GetFirstSelected()
        if 0 <= idx < len(self._filtered_entries):
            return self._filtered_entries[idx]
        return None

    def get_selected_index(self) -> int:
        """Return the index of the selected row in the *filtered* list, or -1."""
        return self.GetFirstSelected()

    def select_entry_by_id(self, entry_id: str) -> None:
        """Attempt to re-select an entry by its UUID after a data refresh."""
        for i, entry in enumerate(self._filtered_entries):
            if getattr(entry, "id", None) == entry_id:
                self.Select(i, True)
                self.Focus(i)
                self.EnsureVisible(i)
                return

    def get_all_entries(self) -> list[Any]:
        """Return the full (unfiltered) entry list."""
        return list(self._all_entries)

    def get_filtered_entries(self) -> list[Any]:
        """Return the currently visible (filtered) entry list."""
        return list(self._filtered_entries)

    # ------------------------------------------------------------------
    # Keyboard convenience
    # ------------------------------------------------------------------

    def move_selection(self, delta: int) -> None:
        """Move the selection by *delta* rows (+1 down, -1 up), clamped."""
        count = self.GetItemCount()
        if count == 0:
            return
        current = self.GetFirstSelected()
        if current < 0:
            new_idx = 0 if delta > 0 else count - 1
        else:
            new_idx = max(0, min(count - 1, current + delta))
        self.Select(new_idx, True)
        self.Focus(new_idx)
        self.EnsureVisible(new_idx)
