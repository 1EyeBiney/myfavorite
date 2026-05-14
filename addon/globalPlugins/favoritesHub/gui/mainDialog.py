# Favorites Hub — NVDA 2026.1 Global Plugin
# gui/mainDialog.py: Listbook-based main dialog (§6.1 of project_brief.md).
#
# Key characteristics:
#   • Modeless wx.Dialog parented to gui.mainFrame (§6.1).
#   • Singleton: re-invoking the hotkey raises the existing instance.
#   • wx.Listbook with 6 pages: Folders, Links, Snippets, CLIs, Macros, Tags.
#   • Pages 1–5 are _CategoryPage instances (filter + virtual ListCtrl + buttons).
#   • Page 6 is a TagsView (left ListBox + right ListCtrl).
#   • EVT_CHAR_HOOK handles 1–6 page switching, Escape close, Enter activate,
#     Delete delete, F2 edit, Applications/Shift+F10 context menu.
#   • Context menu: Activate, Edit, Delete, ─, Duplicate, Copy name,
#     Copy value, ─, Move to tab… (submenu).
#
# Thread-safety: all methods MUST be called on the GUI thread (§5).
#
# Copyright (C) 2026 1EyeBiney
# This file is covered by the GNU General Public License version 2.
# See the file COPYING for more details.

from __future__ import annotations

import copy
import os
from typing import Any

import addonHandler
import api
import config
import gui
import ui
import wx
from logHandler import log

from ..constants import (
    CATEGORY_KEYS,
    CATEGORY_LABELS,
    CONFIG_KEY_CONFIRM_DELETE,
    CONFIG_KEY_LAST_TAB,
    CONFIG_SECTION,
    CONTENT_CATEGORIES,
    Category,
)
from ..schema import (
    CliEntry,
    FolderEntry,
    LinkEntry,
    MacroEntry,
    SnippetEntry,
    _new_id,
    _utc_now_iso,
)
from .. import storage
from .tagsView import TagsView, _dispatch_activate
from . import widgets as _w

addonHandler.initTranslation()

# ---------------------------------------------------------------------------
# Column and row-factory configuration per category (§6.1)
# ---------------------------------------------------------------------------

_COLUMNS: dict[Category, list[tuple[str, int]]] = {
    # Translators: Column headers for the Folders page
    Category.FOLDERS: [(_("Name"), 200), (_("Path"), 300), (_("Tags"), 150)],
    # Translators: Column headers for the Links page
    Category.LINKS:   [(_("Name"), 200), (_("URL"), 300), (_("Tags"), 150)],
    # Translators: Column headers for the Snippets page
    Category.SNIPPETS: [(_("Name"), 200), (_("Preview"), 300), (_("Tags"), 150)],
    # Translators: Column headers for the CLIs page
    Category.CLIS:    [(_("Name"), 200), (_("Command"), 300), (_("Tags"), 150)],
    # Translators: Column headers for the Macros page
    Category.MACROS:  [(_("Name"), 200), (_("Steps"), 100), (_("Tags"), 150)],
}


def _folder_row(e: FolderEntry) -> list[str]:
    return [e.name, e.path, ", ".join(e.tags)]


def _link_row(e: LinkEntry) -> list[str]:
    return [e.name, e.url, ", ".join(e.tags)]


def _snippet_row(e: SnippetEntry) -> list[str]:
    preview = e.body[:60].replace("\n", " ").replace("\r", "")
    if len(e.body) > 60:
        preview += "\u2026"
    return [e.name, preview, ", ".join(e.tags)]


def _cli_row(e: CliEntry) -> list[str]:
    return [e.name, e.command, ", ".join(e.tags)]


def _macro_row(e: MacroEntry) -> list[str]:
    return [e.name, str(len(e.gestures)), ", ".join(e.tags)]


_ROW_FACTORIES: dict[Category, Any] = {
    Category.FOLDERS: _folder_row,
    Category.LINKS:   _link_row,
    Category.SNIPPETS: _snippet_row,
    Category.CLIS:    _cli_row,
    Category.MACROS:  _macro_row,
}

# Map category → dialog class (imported lazily to avoid circular imports)
_DIALOG_MAP: dict[Category, str] = {
    Category.FOLDERS:  "FolderEntryDialog",
    Category.LINKS:    "LinkEntryDialog",
    Category.SNIPPETS: "SnippetEntryDialog",
    Category.CLIS:     "CliEntryDialog",
    Category.MACROS:   "MacroEntryDialog",
}

# Reverse map: JSON key → Category
_KEY_TO_CAT: dict[str, Category] = {v: k for k, v in CATEGORY_KEYS.items()}


def _get_dialog_class(category: Category):
    """Import and return the appropriate entry dialog class."""
    from . import entryDialogs as _ed
    name = _DIALOG_MAP[category]
    return getattr(_ed, name)


def _copy_value_for(category: Category, entry: Any) -> str:
    """Return the primary value string for 'Copy value to clipboard' action."""
    if category == Category.FOLDERS:
        return entry.path
    elif category == Category.LINKS:
        return entry.url
    elif category == Category.SNIPPETS:
        return entry.body
    elif category == Category.CLIS:
        return entry.command
    elif category == Category.MACROS:
        return "\n".join(entry.gestures)
    return ""


# ---------------------------------------------------------------------------
# Singleton reference
# ---------------------------------------------------------------------------

_instance: "FavoritesHubDialog | None" = None


# ===========================================================================
# _CategoryPage — one Listbook page for a content category (1–5)
# ===========================================================================

class _CategoryPage(wx.Panel):
    """A single category page (Folders / Links / Snippets / CLIs / Macros)."""

    def __init__(
        self,
        parent: wx.Window,
        category: Category,
        main_dialog: "FavoritesHubDialog",
    ) -> None:
        super().__init__(parent)
        self._category = category
        self._category_key: str = CATEGORY_KEYS[category]
        self._main_dialog = main_dialog
        self._setup_ui()
        self._bind_events()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        mainSizer = wx.BoxSizer(wx.VERTICAL)

        # ---- Filter row ----
        filterSizer = wx.BoxSizer(wx.HORIZONTAL)
        # Translators: Label for the filter box on each category page
        filterLabel = wx.StaticText(self, label=_("&Filter:"))
        self._filterCtrl = wx.TextCtrl(self)
        # Translators: Accessible name for the filter text box on category pages
        self._filterCtrl.SetName(_("Filter"))
        filterSizer.Add(filterLabel, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        filterSizer.Add(self._filterCtrl, 1, wx.EXPAND)
        mainSizer.Add(filterSizer, 0, wx.EXPAND | wx.ALL, 5)

        # ---- List ----
        self._listCtrl = _w.FavoritesListCtrl(self, _COLUMNS[self._category])
        mainSizer.Add(self._listCtrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        # ---- Buttons ----
        btnSizer = wx.BoxSizer(wx.HORIZONTAL)
        # Translators: Add button on category pages
        self._addBtn = wx.Button(self, label=_("&Add"))
        # Translators: Edit button on category pages
        self._editBtn = wx.Button(self, label=_("&Edit"))
        # Translators: Delete button on category pages
        self._deleteBtn = wx.Button(self, label=_("&Delete"))
        # Translators: Activate button on category pages
        self._activateBtn = wx.Button(self, label=_("A&ctivate"))
        # Translators: Close button on category pages (closes the whole dialog)
        self._closeBtn = wx.Button(self, label=_("&Close"))
        for btn in (
            self._addBtn, self._editBtn, self._deleteBtn,
            self._activateBtn, self._closeBtn,
        ):
            btnSizer.Add(btn, 0, wx.RIGHT, 5)
        mainSizer.Add(btnSizer, 0, wx.ALL, 5)

        self.SetSizer(mainSizer)

    def _bind_events(self) -> None:
        self._filterCtrl.Bind(wx.EVT_TEXT, self._on_filter)
        self._filterCtrl.Bind(wx.EVT_KEY_DOWN, self._on_filter_key_down)
        self._listCtrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_list_activated)
        self._listCtrl.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self._on_right_click)
        self._listCtrl.Bind(wx.EVT_KEY_DOWN, self._on_list_key_down)
        self._addBtn.Bind(wx.EVT_BUTTON, self._on_add)
        self._editBtn.Bind(wx.EVT_BUTTON, self._on_edit)
        self._deleteBtn.Bind(wx.EVT_BUTTON, self._on_delete)
        self._activateBtn.Bind(wx.EVT_BUTTON, self._on_activate_btn)
        self._closeBtn.Bind(wx.EVT_BUTTON, lambda _e: self._main_dialog.Close())

    # ------------------------------------------------------------------
    # Data refresh
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Reload this page's entries from the in-memory storage cache."""
        try:
            doc = storage.get_document()
            hydrated = storage.hydrate_document(doc)
            entries = hydrated.get(self._category_key, [])
            self._listCtrl.set_entries(entries, _ROW_FACTORIES[self._category])
        except Exception as exc:
            log.error(
                "Favorites Hub _CategoryPage.refresh(%s): %s",
                self._category_key, exc,
            )

    # ------------------------------------------------------------------
    # Add / Edit / Delete
    # ------------------------------------------------------------------

    def _on_add(self, event: wx.CommandEvent, prefill_path: str = "") -> None:
        try:
            DlgClass = _get_dialog_class(self._category)
            if self._category == Category.FOLDERS and prefill_path:
                dlg = DlgClass(self._main_dialog, prefill_path=prefill_path)
            else:
                dlg = DlgClass(self._main_dialog)

            if dlg.ShowModal() == wx.ID_OK:
                new_entry = dlg.get_result()
                if new_entry is not None:
                    with storage.mutating() as doc:
                        doc["entries"][self._category_key].append(new_entry.to_dict())
                    self.refresh()
                    self._main_dialog.refresh_tags_page()
                    # Translators: Spoken after successfully adding an entry
                    ui.message(_("{name} added.").format(name=new_entry.name))
            dlg.Destroy()
        except Exception as exc:
            log.error("Favorites Hub _on_add(%s): %s", self._category_key, exc)
            gui.messageBox(
                _("Could not add entry: {error}").format(error=str(exc)),
                _("Error"),
                wx.OK | wx.ICON_ERROR,
                self._main_dialog,
            )

    def _on_edit(self, event: wx.CommandEvent) -> None:
        try:
            entry = self._listCtrl.get_selected_entry()
            if entry is None:
                # Translators: Spoken when no entry is selected for editing
                ui.message(_("No entry selected."))
                return

            DlgClass = _get_dialog_class(self._category)
            dlg = DlgClass(self._main_dialog, editing_entry=entry)

            if dlg.ShowModal() == wx.ID_OK:
                updated_entry = dlg.get_result()
                if updated_entry is not None:
                    with storage.mutating() as doc:
                        entries = doc["entries"][self._category_key]
                        for i, raw in enumerate(entries):
                            if raw.get("id") == entry.id:
                                entries[i] = updated_entry.to_dict()
                                break
                    self.refresh()
                    self._main_dialog.refresh_tags_page()
                    self._listCtrl.select_entry_by_id(updated_entry.id)
                    # Translators: Spoken after successfully editing an entry
                    ui.message(_("{name} updated.").format(name=updated_entry.name))
            dlg.Destroy()
        except Exception as exc:
            log.error("Favorites Hub _on_edit(%s): %s", self._category_key, exc)
            gui.messageBox(
                _("Could not edit entry: {error}").format(error=str(exc)),
                _("Error"),
                wx.OK | wx.ICON_ERROR,
                self._main_dialog,
            )

    def _on_delete(self, event: wx.CommandEvent) -> None:
        try:
            entry = self._listCtrl.get_selected_entry()
            if entry is None:
                # Translators: Spoken when no entry is selected for deletion
                ui.message(_("No entry selected."))
                return
            if not self._confirm_delete(entry.name):
                return
            with storage.mutating() as doc:
                entries = doc["entries"][self._category_key]
                doc["entries"][self._category_key] = [
                    e for e in entries if e.get("id") != entry.id
                ]
            self.refresh()
            self._main_dialog.refresh_tags_page()
            # Translators: Spoken after successfully deleting an entry
            ui.message(_("{name} deleted.").format(name=entry.name))
        except Exception as exc:
            log.error("Favorites Hub _on_delete(%s): %s", self._category_key, exc)
            gui.messageBox(
                _("Could not delete entry: {error}").format(error=str(exc)),
                _("Error"),
                wx.OK | wx.ICON_ERROR,
                self._main_dialog,
            )

    def _confirm_delete(self, name: str) -> bool:
        """Ask for confirmation if the setting requires it. Returns True to proceed."""
        try:
            need_confirm = config.conf[CONFIG_SECTION][CONFIG_KEY_CONFIRM_DELETE]
        except Exception:
            need_confirm = True

        if not need_confirm:
            return True

        result = gui.messageBox(
            # Translators: Confirmation prompt before deleting an entry.
            # {name} is the entry name.
            _("Are you sure you want to delete \u201c{name}\u201d?").format(name=name),
            # Translators: Title of the delete confirmation dialog
            _("Confirm Delete"),
            wx.YES_NO | wx.ICON_QUESTION,
            self._main_dialog,
        )
        return result == wx.YES

    def _on_activate_btn(self, event: wx.CommandEvent) -> None:
        self._activate_selected()

    def _activate_selected(self) -> None:
        entry = self._listCtrl.get_selected_entry()
        if entry is None:
            # Translators: Spoken when no entry is selected for activation
            ui.message(_("No entry selected."))
            return
        _dispatch_activate(self._category_key, entry)

    # ------------------------------------------------------------------
    # Context menu (§6.3)
    # ------------------------------------------------------------------

    def _on_right_click(self, event: wx.ListEvent) -> None:
        try:
            self._show_context_menu()
        except Exception as exc:
            log.error("Favorites Hub context menu: %s", exc)

    def _show_context_menu(self) -> None:
        entry = self._listCtrl.get_selected_entry()
        if entry is None:
            return

        menu = wx.Menu()

        # ---- Activate ----
        # Translators: Context menu item to activate (open/run/copy) an entry
        activate_item = menu.Append(wx.ID_ANY, _("&Activate"))
        self.Bind(wx.EVT_MENU, lambda _e: self._activate_selected(), activate_item)

        # ---- Edit ----
        # Translators: Context menu item to edit an entry
        edit_item = menu.Append(wx.ID_ANY, _("&Edit\tF2"))
        self.Bind(wx.EVT_MENU, lambda _e: self._on_edit(None), edit_item)

        # ---- Delete ----
        # Translators: Context menu item to delete an entry
        delete_item = menu.Append(wx.ID_ANY, _("&Delete\tDel"))
        self.Bind(wx.EVT_MENU, lambda _e: self._on_delete(None), delete_item)

        menu.AppendSeparator()

        # ---- Duplicate ----
        # Translators: Context menu item to duplicate an entry
        dup_item = menu.Append(wx.ID_ANY, _("D&uplicate"))
        self.Bind(wx.EVT_MENU, lambda _e: self._on_duplicate(entry), dup_item)

        # ---- Copy name ----
        # Translators: Context menu item to copy the entry name to the clipboard
        copy_name_item = menu.Append(wx.ID_ANY, _("Copy &name to clipboard"))
        self.Bind(
            wx.EVT_MENU,
            lambda _e: api.copyToClip(entry.name, notify=False),
            copy_name_item,
        )

        # ---- Copy value ----
        value_str = _copy_value_for(self._category, entry)
        # Translators: Context menu item to copy the entry's main value to the clipboard
        copy_val_item = menu.Append(wx.ID_ANY, _("Copy &value to clipboard"))
        self.Bind(
            wx.EVT_MENU,
            lambda _e: api.copyToClip(value_str, notify=False),
            copy_val_item,
        )
        copy_val_item.Enable(bool(value_str))

        menu.AppendSeparator()

        # ---- Move to tab… submenu ----
        move_sub = wx.Menu()
        for cat in CONTENT_CATEGORIES:
            if cat == self._category:
                continue
            cat_label = CATEGORY_LABELS.get(cat, str(cat))
            move_item = move_sub.Append(wx.ID_ANY, cat_label)
            self.Bind(
                wx.EVT_MENU,
                lambda _e, _cat=cat: self._on_move_to_tab(entry, _cat),
                move_item,
            )
        # Translators: Context menu item that opens a submenu to move an entry to another tab
        menu.AppendSubMenu(move_sub, _("Move to &tab\u2026"))

        self._listCtrl.PopupMenu(menu)
        menu.Destroy()

    def _on_duplicate(self, entry: Any) -> None:
        """Create a copy of *entry* with a new ID and add it directly after the original."""
        try:
            with storage.mutating() as doc:
                entries = doc["entries"][self._category_key]
                for i, raw in enumerate(entries):
                    if raw.get("id") == entry.id:
                        dupe = copy.deepcopy(raw)
                        dupe["id"] = _new_id()
                        # Translators: Suffix added to the name of a duplicated entry.
                        # {name} is the original name.
                        dupe["name"] = _("{name} (copy)").format(name=raw["name"])
                        dupe["createdUtc"] = _utc_now_iso()
                        dupe["modifiedUtc"] = _utc_now_iso()
                        entries.insert(i + 1, dupe)
                        break
            self.refresh()
            self._main_dialog.refresh_tags_page()
            # Translators: Spoken after duplicating an entry
            ui.message(_("{name} duplicated.").format(name=entry.name))
        except Exception as exc:
            log.error("Favorites Hub _on_duplicate: %s", exc)

    def _on_move_to_tab(self, entry: Any, target_category: Category) -> None:
        """Move *entry* from the current category to *target_category*.

        Category-specific fields of the source are dropped; the target entry
        is created with name, tags, and notes preserved. The user MUST edit
        the new entry to fill in the target-specific fields.
        """
        target_key = CATEGORY_KEYS[target_category]
        target_label = CATEGORY_LABELS.get(target_category, str(target_category))

        result = gui.messageBox(
            # Translators: Confirmation prompt before moving an entry to another tab.
            # {name} is the entry name; {target} is the destination tab name.
            _(
                "Move \u201c{name}\u201d to the {target} tab?\n\n"
                "Category-specific fields will be reset to defaults. "
                "You will need to edit the entry to fill them in."
            ).format(name=entry.name, target=target_label),
            # Translators: Title of the move-to-tab confirmation dialog
            _("Move to Tab"),
            wx.YES_NO | wx.ICON_QUESTION,
            self._main_dialog,
        )
        if result != wx.YES:
            return

        try:
            # Build a minimal raw dict for the target category
            minimal_raw: dict = {
                "id": _new_id(),
                "name": entry.name,
                "tags": entry.tags,
                "createdUtc": _utc_now_iso(),
                "modifiedUtc": _utc_now_iso(),
                "notes": entry.notes,
            }
            # Fill target-specific default fields
            if target_category == Category.FOLDERS:
                minimal_raw["path"] = ""
                minimal_raw["openWith"] = None
            elif target_category == Category.LINKS:
                minimal_raw["url"] = "https://"
                minimal_raw["browser"] = None
            elif target_category == Category.SNIPPETS:
                minimal_raw["body"] = ""
                minimal_raw["pasteMode"] = "clipboard"
            elif target_category == Category.CLIS:
                minimal_raw["command"] = ""
                minimal_raw["args"] = []
                minimal_raw["shell"] = False
                minimal_raw["cwd"] = None
                minimal_raw["timeoutSec"] = 15
                minimal_raw["speakOutput"] = True
            elif target_category == Category.MACROS:
                minimal_raw["gestures"] = []
                minimal_raw["interStepDelayMs"] = 50

            with storage.mutating() as doc:
                # Remove from source
                src_entries = doc["entries"][self._category_key]
                doc["entries"][self._category_key] = [
                    e for e in src_entries if e.get("id") != entry.id
                ]
                # Add to target
                doc["entries"][target_key].append(minimal_raw)

            self.refresh()
            self._main_dialog.refresh_page(target_category)
            self._main_dialog.refresh_tags_page()
            # Translators: Spoken after moving an entry to another tab
            ui.message(
                _("{name} moved to {target}.").format(
                    name=entry.name, target=target_label
                )
            )
        except Exception as exc:
            log.error("Favorites Hub _on_move_to_tab: %s", exc)
            gui.messageBox(
                _("Could not move entry: {error}").format(error=str(exc)),
                _("Error"),
                wx.OK | wx.ICON_ERROR,
                self._main_dialog,
            )

    # ------------------------------------------------------------------
    # Keyboard event handlers
    # ------------------------------------------------------------------

    def _on_filter(self, event: wx.CommandEvent) -> None:
        try:
            self._listCtrl.apply_filter(self._filterCtrl.GetValue())
        except Exception as exc:
            log.error("Favorites Hub _on_filter: %s", exc)
        event.Skip()

    def _on_filter_key_down(self, event: wx.KeyEvent) -> None:
        """Move focus to the list when the user presses Down in the filter box."""
        if event.GetKeyCode() == wx.WXK_DOWN:
            count = self._listCtrl.GetItemCount()
            if count > 0:
                self._listCtrl.SetFocus()
                self._listCtrl.Focus(0)
                self._listCtrl.Select(0, True)
        else:
            event.Skip()

    def _on_list_activated(self, event: wx.ListEvent) -> None:
        try:
            self._activate_selected()
        except Exception as exc:
            log.error("Favorites Hub _on_list_activated: %s", exc)
        event.Skip()

    def _on_list_key_down(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            try:
                self._activate_selected()
            except Exception as exc:
                log.error("Favorites Hub list Enter: %s", exc)
        elif key == wx.WXK_DELETE:
            try:
                self._on_delete(None)
            except Exception as exc:
                log.error("Favorites Hub list Delete: %s", exc)
        elif key == wx.WXK_F2:
            try:
                self._on_edit(None)
            except Exception as exc:
                log.error("Favorites Hub list F2: %s", exc)
        elif key == wx.WXK_WINDOWS_MENU or (key == wx.WXK_F10 and event.ShiftDown()):
            try:
                self._show_context_menu()
            except Exception as exc:
                log.error("Favorites Hub context menu key: %s", exc)
        else:
            event.Skip()

    # ------------------------------------------------------------------
    # Public helper: open Add dialog pre-filled (used by mainDialog for capture)
    # ------------------------------------------------------------------

    def open_add_with_prefill(self, path: str) -> None:
        """Open the Add dialog pre-filled with *path* (Folders only)."""
        if self._category == Category.FOLDERS:
            self._on_add(None, prefill_path=path)


# ===========================================================================
# FavoritesHubDialog — the main singleton dialog
# ===========================================================================

class FavoritesHubDialog(wx.Dialog):
    """The Favorites Hub main dialog (§6.1).

    Always created via ``show_singleton()``.  It is modeless so that the user
    can alt-tab to another window (e.g. Explorer) for context capture without
    losing their place.
    """

    # ------------------------------------------------------------------
    # Singleton management
    # ------------------------------------------------------------------

    @classmethod
    def show_singleton(
        cls,
        parent: wx.Window,
        initial_page: int = -1,
        prefill_path: str | None = None,
    ) -> None:
        """Show the dialog, or raise the existing instance if already open.

        Parameters
        ----------
        parent:
            Parent window (should be ``gui.mainFrame``).
        initial_page:
            0-based Listbook page to select on open.  -1 uses the last-used
            tab stored in config.
        prefill_path:
            If supplied, after opening, switch to the Folders page and open
            the Add Folder dialog pre-filled with this path.
        """
        global _instance
        if _instance is not None:
            if initial_page >= 0:
                _instance._listbook.SetSelection(initial_page)
            _instance.Raise()
            _instance.SetFocus()
            return

        # Determine which page to show
        if initial_page < 0:
            try:
                initial_page = int(config.conf[CONFIG_SECTION][CONFIG_KEY_LAST_TAB])
                initial_page = max(0, min(5, initial_page))
            except Exception:
                initial_page = 0

        _instance = cls(parent, initial_page=initial_page)
        gui.mainFrame.prePopup()
        _instance.Show()

        if prefill_path:
            wx.CallAfter(_instance._open_add_folder_with_path, prefill_path)

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    def __init__(self, parent: wx.Window, initial_page: int = 0) -> None:
        super().__init__(
            parent,
            # Translators: Title of the Favorites Hub main dialog
            title=_("Favorites Hub"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._pages: dict[Category, _CategoryPage] = {}
        self._tags_page: TagsView | None = None
        self._initial_page = initial_page
        self._setup_ui()
        self._bind_events()
        self._refresh_all_pages()
        self.SetSize(wx.Size(760, 520))
        self.SetMinSize(wx.Size(600, 400))
        self.CentreOnParent()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        mainSizer = wx.BoxSizer(wx.VERTICAL)

        self._listbook = wx.Listbook(self, style=wx.LB_LEFT)
        mainSizer.Add(self._listbook, 1, wx.EXPAND | wx.ALL, 5)

        # ---- Content pages (1–5) ----
        for cat in CONTENT_CATEGORIES:
            page = _CategoryPage(self._listbook, cat, self)
            self._pages[cat] = page
            self._listbook.AddPage(
                page,
                # Each category label is already translatable via CATEGORY_LABELS
                CATEGORY_LABELS.get(cat, str(cat)),
            )

        # ---- Tags page (6) ----
        self._tags_page = TagsView(self._listbook)
        self._listbook.AddPage(
            self._tags_page,
            # Translators: Label for the Tags page in the Favorites Hub Listbook
            _("Tags"),
        )

        self.SetSizer(mainSizer)

        # Select the initial page
        self._listbook.SetSelection(self._initial_page)

    def _bind_events(self) -> None:
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self._listbook.Bind(wx.EVT_LISTBOOK_PAGE_CHANGED, self._on_page_changed)

    # ------------------------------------------------------------------
    # Data management
    # ------------------------------------------------------------------

    def _refresh_all_pages(self) -> None:
        """Reload all category pages and the tags page from storage."""
        for page in self._pages.values():
            page.refresh()
        self.refresh_tags_page()

    def refresh_tags_page(self) -> None:
        """Reload only the Tags page from storage."""
        if self._tags_page is not None:
            try:
                doc = storage.get_document()
                self._tags_page.refresh(doc)
            except Exception as exc:
                log.error("Favorites Hub refresh_tags_page: %s", exc)

    def refresh_page(self, category: Category) -> None:
        """Reload a single category page from storage."""
        page = self._pages.get(category)
        if page is not None:
            page.refresh()

    # ------------------------------------------------------------------
    # Context-capture pre-fill
    # ------------------------------------------------------------------

    def _open_add_folder_with_path(self, path: str) -> None:
        """Switch to the Folders page and open Add Folder pre-filled."""
        self._listbook.SetSelection(0)  # Folders is page 0
        folder_page = self._pages.get(Category.FOLDERS)
        if folder_page is not None:
            folder_page.open_add_with_prefill(path)

    # ------------------------------------------------------------------
    # EVT_CHAR_HOOK — global accelerators (§6.2)
    # ------------------------------------------------------------------

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        focus = wx.Window.FindFocus()
        in_text = isinstance(focus, (wx.TextCtrl, wx.ComboBox))

        # 1–6: switch Listbook page (suppressed when focus is in an editable control)
        if ord("1") <= key <= ord("6") and not in_text:
            page_idx = key - ord("1")
            self._listbook.SetSelection(page_idx)
            # Announce the new page for screen readers
            cat_name = self._listbook.GetPageText(page_idx)
            ui.message(cat_name)
            return  # consume key

        # Escape: close dialog
        if key == wx.WXK_ESCAPE:
            self.Close()
            return  # consume key

        # For all other keys, pass through
        event.Skip()

    # ------------------------------------------------------------------
    # Page-changed event — announce page name
    # ------------------------------------------------------------------

    def _on_page_changed(self, event: wx.BookCtrlEvent) -> None:
        new_page = event.GetSelection()
        if 0 <= new_page < self._listbook.GetPageCount():
            page_text = self._listbook.GetPageText(new_page)
            # Refresh tags page when it becomes active
            if new_page == len(CONTENT_CATEGORIES):  # Tags is the last page
                self.refresh_tags_page()
        event.Skip()

    # ------------------------------------------------------------------
    # Close / cleanup
    # ------------------------------------------------------------------

    def _on_close(self, event: wx.CloseEvent) -> None:
        global _instance
        # Persist the last-used tab
        try:
            config.conf[CONFIG_SECTION][CONFIG_KEY_LAST_TAB] = (
                self._listbook.GetSelection()
            )
        except Exception as exc:
            log.debugWarning("Favorites Hub: could not save lastUsedTab: %s", exc)

        gui.mainFrame.postPopup()
        _instance = None
        self.Destroy()
