# Favorites Hub — NVDA 2026.1 Global Plugin
# gui/entryDialogs.py: Modal Add/Edit dialogs for all five entry categories.
#
# Class hierarchy:
#   _BaseEntryDialog(wx.Dialog)      — common fields: name, tags, notes + OK/Cancel
#     ├── FolderEntryDialog          — path + Browse + Capture buttons
#     ├── LinkEntryDialog            — url
#     ├── SnippetEntryDialog         — body (multiline)
#     ├── CliEntryDialog             — command, args, shell, cwd, timeout, speakOutput
#     └── MacroEntryDialog           — gestures (multiline), interStepDelayMs
#
# Validation is performed in _build_result() which returns the typed entry or
# None (after showing an error message) when validation fails.  The OK button
# only closes the dialog if _build_result() succeeds.
#
# Usage:
#   dlg = FolderEntryDialog(parent)          # Add mode
#   dlg = FolderEntryDialog(parent, entry)   # Edit mode (entry prepopulated)
#   if dlg.ShowModal() == wx.ID_OK:
#       new_entry = dlg.get_result()
#   dlg.Destroy()
#
# Thread-safety: all methods MUST be called on the GUI thread (§5).
#
# Copyright (C) 2026 1EyeBiney
# This file is covered by the GNU General Public License version 2.
# See the file COPYING for more details.

from __future__ import annotations

import addonHandler
import config
import gui
import wx
from gui import guiHelper
from logHandler import log

from ..constants import (
    CLI_TIMEOUT_DEFAULT,
    CLI_TIMEOUT_MAX,
    CLI_TIMEOUT_MIN,
    CONFIG_KEY_CONTEXT_CAPTURE,
    CONFIG_SECTION,
    MACRO_DELAY_DEFAULT,
    MACRO_DELAY_MAX,
    MACRO_DELAY_MIN,
)
from ..schema import (
    CliEntry,
    FolderEntry,
    LinkEntry,
    MacroEntry,
    SnippetEntry,
    _utc_now_iso,
)

addonHandler.initTranslation()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALLOWED_LINK_SCHEMES = ("http://", "https://", "mailto:")


def _tags_to_str(tags: list[str]) -> str:
    return ", ".join(tags)


def _str_to_tags(text: str) -> list[str]:
    return [t.strip() for t in text.split(",") if t.strip()]


# ---------------------------------------------------------------------------
# Base dialog
# ---------------------------------------------------------------------------

class _BaseEntryDialog(wx.Dialog):
    """Common scaffolding for all five Add/Edit entry dialogs.

    Subclasses MUST implement:
        _add_category_fields(helper)          — add category-specific widgets
        _populate_category_fields(entry)      — fill them from an existing entry
        _build_result() -> entry | None       — validate and construct the entry
    """

    def __init__(
        self,
        parent: wx.Window,
        title: str,
        editing_entry=None,
    ) -> None:
        super().__init__(
            parent,
            title=title,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._editing = editing_entry
        self._result = None
        self._setup_ui()
        if editing_entry is not None:
            self._populate(editing_entry)
        self.Fit()
        self.SetMinSize(wx.Size(480, -1))
        self.CentreOnParent()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        outerSizer = wx.BoxSizer(wx.VERTICAL)
        helper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

        # ---- Name ----
        self._nameCtrl: wx.TextCtrl = helper.addLabeledControl(
            # Translators: Label for the "Name" field in Favorites Hub entry dialogs
            _("&Name:"),
            wx.TextCtrl,
        )

        # ---- Category-specific fields (provided by subclass) ----
        self._add_category_fields(helper)

        # ---- Tags ----
        self._tagsCtrl: wx.TextCtrl = helper.addLabeledControl(
            # Translators: Label for the "Tags" field in Favorites Hub entry dialogs
            _("&Tags (comma-separated):"),
            wx.TextCtrl,
        )

        # ---- Notes ----
        notesLabel = wx.StaticText(self, label=_("&Notes:"))
        self._notesCtrl = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE,
            size=wx.Size(-1, 70),
        )
        # Translators: Accessible name for the Notes text area in entry dialogs
        self._notesCtrl.SetName(_("Notes"))
        notesLabelledSizer = wx.BoxSizer(wx.VERTICAL)
        notesLabelledSizer.Add(notesLabel, 0, wx.BOTTOM, 3)
        notesLabelledSizer.Add(self._notesCtrl, 0, wx.EXPAND)
        helper.addItem(notesLabelledSizer, flag=wx.EXPAND)

        # ---- OK / Cancel ----
        btnSizer = wx.BoxSizer(wx.HORIZONTAL)
        self._okBtn = wx.Button(self, label=_("&OK"))
        self._okBtn.SetDefault()
        # Cancel with wx.ID_CANCEL so Escape works automatically
        self._cancelBtn = wx.Button(self, wx.ID_CANCEL, label=_("&Cancel"))
        btnSizer.Add(self._okBtn, 0, wx.RIGHT, 5)
        btnSizer.Add(self._cancelBtn, 0)
        helper.addItem(btnSizer)

        outerSizer.Add(helper.sizer, 1, wx.EXPAND | wx.ALL, 10)
        self.SetSizer(outerSizer)

        # Bind OK button (Cancel handled by wx.ID_CANCEL automatically)
        self._okBtn.Bind(wx.EVT_BUTTON, self._on_ok)

    # ------------------------------------------------------------------
    # Subclass hooks
    # ------------------------------------------------------------------

    def _add_category_fields(self, helper: guiHelper.BoxSizerHelper) -> None:
        """Override in subclasses to insert category-specific controls."""
        pass

    def _populate_category_fields(self, entry) -> None:
        """Override in subclasses to populate category-specific controls."""
        pass

    def _build_result(self):
        """Override in subclasses. Returns a typed entry or None on validation failure."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Common populate helper
    # ------------------------------------------------------------------

    def _populate(self, entry) -> None:
        """Fill all common fields from *entry* (called in edit mode)."""
        self._nameCtrl.SetValue(entry.name)
        self._tagsCtrl.SetValue(_tags_to_str(entry.tags))
        self._notesCtrl.SetValue(entry.notes)
        self._populate_category_fields(entry)

    # ------------------------------------------------------------------
    # Common extraction helpers
    # ------------------------------------------------------------------

    def _get_name(self) -> str:
        return self._nameCtrl.GetValue().strip()

    def _get_tags(self) -> list[str]:
        return _str_to_tags(self._tagsCtrl.GetValue())

    def _get_notes(self) -> str:
        return self._notesCtrl.GetValue()

    def _validate_name(self) -> bool:
        """Returns True if name is non-empty; shows error and returns False otherwise."""
        if not self._get_name():
            gui.messageBox(
                # Translators: Validation error when the Name field is empty
                _("Name is required and must not be empty."),
                # Translators: Title of validation error dialogs in Favorites Hub
                _("Validation Error"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            self._nameCtrl.SetFocus()
            return False
        return True

    # ------------------------------------------------------------------
    # Common kwargs for all entry constructors
    # ------------------------------------------------------------------

    def _common_kwargs(self) -> dict:
        base = {
            "name": self._get_name(),
            "tags": self._get_tags(),
            "notes": self._get_notes(),
        }
        if self._editing is not None:
            base["id"] = self._editing.id
            base["createdUtc"] = self._editing.createdUtc
            base["modifiedUtc"] = _utc_now_iso()
        return base

    # ------------------------------------------------------------------
    # OK event handler
    # ------------------------------------------------------------------

    def _on_ok(self, event: wx.CommandEvent) -> None:
        try:
            result = self._build_result()
        except Exception as exc:
            log.error("Favorites Hub entryDialog._on_ok: %s", exc)
            gui.messageBox(
                # Translators: Generic error shown in entry dialogs on unexpected failure
                _("An unexpected error occurred: {error}").format(error=str(exc)),
                _("Error"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            return
        if result is not None:
            self._result = result
            self.EndModal(wx.ID_OK)
        # else: validation failed — dialog stays open

    # ------------------------------------------------------------------
    # Public accessor
    # ------------------------------------------------------------------

    def get_result(self):
        """Return the validated entry object (available after ShowModal → ID_OK)."""
        return self._result


# ---------------------------------------------------------------------------
# FolderEntryDialog
# ---------------------------------------------------------------------------

class FolderEntryDialog(_BaseEntryDialog):
    """Add/Edit dialog for FolderEntry items."""

    def __init__(
        self,
        parent: wx.Window,
        editing_entry: FolderEntry | None = None,
        prefill_path: str = "",
    ) -> None:
        self._prefill_path = prefill_path
        super().__init__(
            parent,
            # Translators: Title of the dialog for adding a new folder entry
            title=_("Edit Folder") if editing_entry else _("Add Folder"),
            editing_entry=editing_entry,
        )
        if prefill_path and not (editing_entry and editing_entry.path):
            self._pathCtrl.SetValue(prefill_path)

    def _add_category_fields(self, helper: guiHelper.BoxSizerHelper) -> None:
        # Path TextCtrl with label
        self._pathCtrl: wx.TextCtrl = helper.addLabeledControl(
            # Translators: Label for the Path field in the Add/Edit Folder dialog
            _("&Path:"),
            wx.TextCtrl,
        )

        # Browse + Capture buttons on same row
        browseCaptureSizer = wx.BoxSizer(wx.HORIZONTAL)

        self._browseBtn = wx.Button(
            self,
            # Translators: Button to browse for a folder in the Add/Edit Folder dialog
            label=_("&Browse\u2026"),
        )
        browseCaptureSizer.Add(self._browseBtn, 0, wx.RIGHT, 5)

        self._captureBtn = wx.Button(
            self,
            # Translators: Button to capture the path from the currently active window
            label=_("Capture from &active window"),
        )
        browseCaptureSizer.Add(self._captureBtn, 0)

        helper.addItem(browseCaptureSizer)

        # Hide capture button if context capture is disabled
        try:
            capture_enabled = config.conf[CONFIG_SECTION][CONFIG_KEY_CONTEXT_CAPTURE]
        except Exception:
            capture_enabled = True
        if not capture_enabled:
            self._captureBtn.Hide()

        # Bind button events
        self._browseBtn.Bind(wx.EVT_BUTTON, self._on_browse)
        self._captureBtn.Bind(wx.EVT_BUTTON, self._on_capture)

    def _populate_category_fields(self, entry: FolderEntry) -> None:
        self._pathCtrl.SetValue(entry.path)

    def _build_result(self) -> FolderEntry | None:
        if not self._validate_name():
            return None

        path = self._pathCtrl.GetValue().strip()
        if not path:
            gui.messageBox(
                # Translators: Validation error when the Path field is empty
                _("Path is required."),
                _("Validation Error"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            self._pathCtrl.SetFocus()
            return None

        return FolderEntry(**self._common_kwargs(), path=path, openWith=None)

    def _on_browse(self, event: wx.CommandEvent) -> None:
        current = self._pathCtrl.GetValue().strip()
        dlg = wx.DirDialog(
            self,
            # Translators: Prompt text in the folder browser dialog
            _("Select a folder"),
            defaultPath=current,
            style=wx.DD_DEFAULT_STYLE,
        )
        if dlg.ShowModal() == wx.ID_OK:
            self._pathCtrl.SetValue(dlg.GetPath())
        dlg.Destroy()

    def _on_capture(self, event: wx.CommandEvent) -> None:
        try:
            from ..contextCapture import get_active_folder_path
            path = get_active_folder_path()
            if path:
                self._pathCtrl.SetValue(path)
                import ui as _ui
                # Translators: Spoken after a folder path is captured from the active window.
                # {path} is the captured path.
                _ui.message(_("Captured: {path}").format(path=path))
            else:
                gui.messageBox(
                    # Translators: Message shown when no folder could be detected
                    _("No folder path could be detected from the active window."),
                    # Translators: Title of the capture-failed information dialog
                    _("Capture Failed"),
                    wx.OK | wx.ICON_INFORMATION,
                    self,
                )
        except Exception as exc:
            log.error("Favorites Hub FolderEntryDialog._on_capture: %s", exc)
            gui.messageBox(
                # Translators: Error shown when context capture raises an exception
                _("An error occurred while capturing the folder path."),
                _("Capture Error"),
                wx.OK | wx.ICON_ERROR,
                self,
            )


# ---------------------------------------------------------------------------
# LinkEntryDialog
# ---------------------------------------------------------------------------

class LinkEntryDialog(_BaseEntryDialog):
    """Add/Edit dialog for LinkEntry items."""

    def __init__(
        self,
        parent: wx.Window,
        editing_entry: LinkEntry | None = None,
    ) -> None:
        super().__init__(
            parent,
            # Translators: Title of the dialog for editing a link entry
            title=_("Edit Link") if editing_entry else _("Add Link"),
            editing_entry=editing_entry,
        )

    def _add_category_fields(self, helper: guiHelper.BoxSizerHelper) -> None:
        self._urlCtrl: wx.TextCtrl = helper.addLabeledControl(
            # Translators: Label for the URL field in the Add/Edit Link dialog
            _("&URL:"),
            wx.TextCtrl,
        )
        helper.addItem(
            wx.StaticText(
                self,
                # Translators: Hint text shown below the URL field, listing allowed schemes
                label=_("Allowed schemes: http://, https://, mailto:"),
            )
        )

    def _populate_category_fields(self, entry: LinkEntry) -> None:
        self._urlCtrl.SetValue(entry.url)

    def _build_result(self) -> LinkEntry | None:
        if not self._validate_name():
            return None

        url = self._urlCtrl.GetValue().strip()
        if not any(url.startswith(s) for s in _ALLOWED_LINK_SCHEMES):
            gui.messageBox(
                # Translators: Validation error when the URL scheme is not allowed
                _(
                    "URL must start with http://, https://, or mailto:.\n"
                    "Got: {url}"
                ).format(url=url[:80]),
                _("Validation Error"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            self._urlCtrl.SetFocus()
            return None

        return LinkEntry(**self._common_kwargs(), url=url, browser=None)


# ---------------------------------------------------------------------------
# SnippetEntryDialog
# ---------------------------------------------------------------------------

class SnippetEntryDialog(_BaseEntryDialog):
    """Add/Edit dialog for SnippetEntry items."""

    def __init__(
        self,
        parent: wx.Window,
        editing_entry: SnippetEntry | None = None,
    ) -> None:
        super().__init__(
            parent,
            # Translators: Title of the dialog for editing a snippet entry
            title=_("Edit Snippet") if editing_entry else _("Add Snippet"),
            editing_entry=editing_entry,
        )

    def _add_category_fields(self, helper: guiHelper.BoxSizerHelper) -> None:
        bodyLabel = wx.StaticText(self, label=_("&Body:"))
        self._bodyCtrl = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE,
            size=wx.Size(-1, 120),
        )
        # Translators: Accessible name for the snippet body text area
        self._bodyCtrl.SetName(_("Body"))
        bodySizer = wx.BoxSizer(wx.VERTICAL)
        bodySizer.Add(bodyLabel, 0, wx.BOTTOM, 3)
        bodySizer.Add(self._bodyCtrl, 0, wx.EXPAND)
        helper.addItem(bodySizer, flag=wx.EXPAND)

        helper.addItem(
            wx.StaticText(
                self,
                # Translators: Hint about snippet tokens shown in the Add/Edit Snippet dialog
                label=_(
                    "Supported tokens: {{date}}, {{time}}, {{datetime}}, "
                    "{{clipboard}}, {{cursor}}, {{nl}}, {{tab}}, {{name}}"
                ),
            )
        )

    def _populate_category_fields(self, entry: SnippetEntry) -> None:
        self._bodyCtrl.SetValue(entry.body)

    def _build_result(self) -> SnippetEntry | None:
        if not self._validate_name():
            return None

        body = self._bodyCtrl.GetValue()
        if not body:
            gui.messageBox(
                # Translators: Validation error when the snippet body is empty
                _("Body must not be empty."),
                _("Validation Error"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            self._bodyCtrl.SetFocus()
            return None

        return SnippetEntry(**self._common_kwargs(), body=body, pasteMode="clipboard")


# ---------------------------------------------------------------------------
# CliEntryDialog
# ---------------------------------------------------------------------------

class CliEntryDialog(_BaseEntryDialog):
    """Add/Edit dialog for CliEntry items."""

    def __init__(
        self,
        parent: wx.Window,
        editing_entry: CliEntry | None = None,
    ) -> None:
        super().__init__(
            parent,
            # Translators: Title of the dialog for editing a CLI entry
            title=_("Edit CLI Command") if editing_entry else _("Add CLI Command"),
            editing_entry=editing_entry,
        )

    def _add_category_fields(self, helper: guiHelper.BoxSizerHelper) -> None:
        # Command
        self._commandCtrl: wx.TextCtrl = helper.addLabeledControl(
            # Translators: Label for the Command field in the Add/Edit CLI dialog
            _("&Command:"),
            wx.TextCtrl,
        )

        # Args (one per line)
        argsLabel = wx.StaticText(self, label=_("&Arguments (one per line):"))
        self._argsCtrl = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE,
            size=wx.Size(-1, 60),
        )
        # Translators: Accessible name for the arguments text area in CLI dialog
        self._argsCtrl.SetName(_("Arguments"))
        argsSizer = wx.BoxSizer(wx.VERTICAL)
        argsSizer.Add(argsLabel, 0, wx.BOTTOM, 3)
        argsSizer.Add(self._argsCtrl, 0, wx.EXPAND)
        helper.addItem(argsSizer, flag=wx.EXPAND)

        # Working directory
        self._cwdCtrl: wx.TextCtrl = helper.addLabeledControl(
            # Translators: Label for the working directory field in the CLI dialog
            _("&Working directory (optional):"),
            wx.TextCtrl,
        )

        # Timeout spinner
        self._timeoutCtrl: wx.SpinCtrl = helper.addLabeledControl(
            # Translators: Label for the timeout field in the CLI dialog
            _("&Timeout (seconds, {min}–{max}):").format(
                min=CLI_TIMEOUT_MIN, max=CLI_TIMEOUT_MAX
            ),
            wx.SpinCtrl,
            min=CLI_TIMEOUT_MIN,
            max=CLI_TIMEOUT_MAX,
            initial=CLI_TIMEOUT_DEFAULT,
        )

        # Shell checkbox + warning
        self._shellCb = helper.addItem(
            wx.CheckBox(
                self,
                # Translators: Checkbox label for shell=True option in the CLI dialog
                label=_("&Run in shell (cmd.exe)"),
            )
        )
        self._shellWarning = helper.addItem(
            wx.StaticText(
                self,
                # Translators: Security warning shown when shell=True is enabled.
                # Displayed adjacent to the shell checkbox in the CLI Add/Edit dialog.
                label=_(
                    "\u26a0 Warning: shell=True can expose your system to "
                    "command-injection attacks. Only enable this when you "
                    "completely trust the command string."
                ),
            )
        )
        self._shellWarning.SetForegroundColour(wx.Colour(180, 0, 0))
        self._shellWarning.Show(False)

        # Speak output checkbox
        self._speakOutputCb = helper.addItem(
            wx.CheckBox(
                self,
                # Translators: Checkbox label for speakOutput in the CLI dialog
                label=_("&Speak command output when complete"),
            )
        )
        self._speakOutputCb.SetValue(True)

        # Bind shell toggle
        self._shellCb.Bind(wx.EVT_CHECKBOX, self._on_shell_toggle)

    def _on_shell_toggle(self, event: wx.CommandEvent) -> None:
        self._shellWarning.Show(self._shellCb.GetValue())
        self.Layout()
        self.Fit()

    def _populate_category_fields(self, entry: CliEntry) -> None:
        self._commandCtrl.SetValue(entry.command)
        self._argsCtrl.SetValue("\n".join(entry.args))
        self._cwdCtrl.SetValue(entry.cwd or "")
        self._timeoutCtrl.SetValue(entry.timeoutSec)
        self._shellCb.SetValue(entry.shell)
        self._shellWarning.Show(entry.shell)
        self._speakOutputCb.SetValue(entry.speakOutput)

    def _build_result(self) -> CliEntry | None:
        if not self._validate_name():
            return None

        command = self._commandCtrl.GetValue().strip()
        if not command:
            gui.messageBox(
                # Translators: Validation error when the CLI command field is empty
                _("Command is required."),
                _("Validation Error"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            self._commandCtrl.SetFocus()
            return None

        raw_args = self._argsCtrl.GetValue()
        args = [a.strip() for a in raw_args.splitlines() if a.strip()]

        cwd_raw = self._cwdCtrl.GetValue().strip()
        cwd = cwd_raw if cwd_raw else None

        timeout = max(CLI_TIMEOUT_MIN, min(CLI_TIMEOUT_MAX, self._timeoutCtrl.GetValue()))

        return CliEntry(
            **self._common_kwargs(),
            command=command,
            args=args,
            shell=self._shellCb.GetValue(),
            cwd=cwd,
            timeoutSec=timeout,
            speakOutput=self._speakOutputCb.GetValue(),
        )


# ---------------------------------------------------------------------------
# MacroEntryDialog
# ---------------------------------------------------------------------------

class MacroEntryDialog(_BaseEntryDialog):
    """Add/Edit dialog for MacroEntry items."""

    def __init__(
        self,
        parent: wx.Window,
        editing_entry: MacroEntry | None = None,
    ) -> None:
        super().__init__(
            parent,
            # Translators: Title of the dialog for editing a macro entry
            title=_("Edit Macro") if editing_entry else _("Add Macro"),
            editing_entry=editing_entry,
        )

    def _add_category_fields(self, helper: guiHelper.BoxSizerHelper) -> None:
        gesturesLabel = wx.StaticText(self, label=_("&Gestures (one per line):"))
        self._gesturesCtrl = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE,
            size=wx.Size(-1, 100),
        )
        # Translators: Accessible name for the gestures text area in the Macro dialog
        self._gesturesCtrl.SetName(_("Gestures"))
        gesturesSizer = wx.BoxSizer(wx.VERTICAL)
        gesturesSizer.Add(gesturesLabel, 0, wx.BOTTOM, 3)
        gesturesSizer.Add(self._gesturesCtrl, 0, wx.EXPAND)
        helper.addItem(gesturesSizer, flag=wx.EXPAND)

        helper.addItem(
            wx.StaticText(
                self,
                # Translators: Hint about gesture format in the Add/Edit Macro dialog
                label=_(
                    "Example gestures: control+c   alt+tab   windows+d\n"
                    "Use the same format as NVDA Input Gestures."
                ),
            )
        )

        # Inter-step delay spinner
        self._delayCtrl: wx.SpinCtrl = helper.addLabeledControl(
            # Translators: Label for the delay field in the Macro dialog
            _("&Inter-step delay (ms, {min}–{max}):").format(
                min=MACRO_DELAY_MIN, max=MACRO_DELAY_MAX
            ),
            wx.SpinCtrl,
            min=MACRO_DELAY_MIN,
            max=MACRO_DELAY_MAX,
            initial=MACRO_DELAY_DEFAULT,
        )

    def _populate_category_fields(self, entry: MacroEntry) -> None:
        self._gesturesCtrl.SetValue("\n".join(entry.gestures))
        self._delayCtrl.SetValue(entry.interStepDelayMs)

    def _build_result(self) -> MacroEntry | None:
        if not self._validate_name():
            return None

        raw = self._gesturesCtrl.GetValue()
        gestures = [g.strip() for g in raw.splitlines() if g.strip()]
        if not gestures:
            gui.messageBox(
                # Translators: Validation error when the gestures list is empty
                _("At least one gesture is required."),
                _("Validation Error"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            self._gesturesCtrl.SetFocus()
            return None

        # Validate all gesture strings before accepting
        import keyboardHandler
        for g in gestures:
            try:
                keyboardHandler.KeyboardInputGesture.fromName(g)
            except Exception:
                gui.messageBox(
                    # Translators: Validation error for an unrecognised gesture string.
                    # {gesture} is the offending gesture text.
                    _("Unrecognised gesture: \u201c{gesture}\u201d\n\n"
                      "Check that it matches NVDA's gesture format.").format(gesture=g),
                    _("Validation Error"),
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
                self._gesturesCtrl.SetFocus()
                return None

        delay = max(MACRO_DELAY_MIN, min(MACRO_DELAY_MAX, self._delayCtrl.GetValue()))

        return MacroEntry(
            **self._common_kwargs(),
            gestures=gestures,
            interStepDelayMs=delay,
        )
