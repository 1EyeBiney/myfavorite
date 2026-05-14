# Favorites Hub — NVDA 2026.1 Global Plugin
# gui/settingsPanel.py: NVDA Settings Panel integration (§12 of project_brief.md).
#
# Registered by GlobalPlugin.__init__ and deregistered in GlobalPlugin.terminate().
#
# v1 exposes exactly two checkboxes:
#   1. Confirm before deleting an entry  (default: True)
#   2. Enable context-aware path capturing (default: True)
#
# Thread-safety: all methods run on the GUI thread via the NVDA settings dialog.
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
    CONFIG_KEY_CONFIRM_DELETE,
    CONFIG_KEY_CONTEXT_CAPTURE,
    CONFIG_SECTION,
)

addonHandler.initTranslation()

# ---------------------------------------------------------------------------
# confspec — registered here so that importing this module at any point
# ensures the spec is in place before any access to config.conf[CONFIG_SECTION].
# The GlobalPlugin also calls _register_confspec() at startup for safety.
# ---------------------------------------------------------------------------

CONFSPEC: dict[str, str] = {
    CONFIG_KEY_CONFIRM_DELETE: "boolean(default=True)",
    CONFIG_KEY_CONTEXT_CAPTURE: "boolean(default=True)",
    # lastUsedTab is also stored but managed by the main dialog
    "lastUsedTab": "integer(default=0)",
}


def register_confspec() -> None:
    """Idempotently register the favoritesHub section in config.conf.spec."""
    if CONFIG_SECTION not in config.conf.spec:
        config.conf.spec[CONFIG_SECTION] = CONFSPEC
        log.debug("Favorites Hub settingsPanel: confspec registered.")


# Register immediately on import so any code that accesses config.conf[CONFIG_SECTION]
# before the GlobalPlugin starts will still find a valid spec.
register_confspec()


# ---------------------------------------------------------------------------
# Settings panel
# ---------------------------------------------------------------------------

class FavoritesHubSettingsPanel(gui.SettingsPanel):
    """NVDA Settings panel for the Favorites Hub add-on (§12)."""

    # Translators: Title of the Favorites Hub category in the NVDA Settings dialog
    title: str = _("Favorites Hub")

    def makeSettings(self, settingsSizer: wx.BoxSizer) -> None:
        """Populate the panel with the two v1 checkboxes."""
        helper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

        # Checkbox 1: confirm before delete
        self._confirmDeleteCb: wx.CheckBox = helper.addItem(
            wx.CheckBox(
                self,
                # Translators: Label for the "confirm before delete" checkbox
                # in the Favorites Hub settings panel.
                label=_("&Confirm before deleting an entry"),
            )
        )
        try:
            self._confirmDeleteCb.SetValue(
                config.conf[CONFIG_SECTION][CONFIG_KEY_CONFIRM_DELETE]
            )
        except Exception as exc:
            log.debugWarning(
                "Favorites Hub settingsPanel: could not read confirmBeforeDelete: %s", exc
            )
            self._confirmDeleteCb.SetValue(True)

        # Checkbox 2: context-aware path capturing
        self._contextCaptureCb: wx.CheckBox = helper.addItem(
            wx.CheckBox(
                self,
                # Translators: Label for the "enable context capture" checkbox
                # in the Favorites Hub settings panel.
                label=_("&Enable context-aware path capturing"),
            )
        )
        try:
            self._contextCaptureCb.SetValue(
                config.conf[CONFIG_SECTION][CONFIG_KEY_CONTEXT_CAPTURE]
            )
        except Exception as exc:
            log.debugWarning(
                "Favorites Hub settingsPanel: could not read contextCaptureEnabled: %s", exc
            )
            self._contextCaptureCb.SetValue(True)

        # Descriptive note about context capture
        helper.addItem(
            wx.StaticText(
                self,
                # Translators: Helper text shown below the context-capture checkbox
                # in the Favorites Hub settings panel.
                label=_(
                    "When enabled, the \u201cCapture from active window\u201d "
                    "button in the Add Folder dialog will be available."
                ),
            )
        )

    def onSave(self) -> None:
        """Persist both checkbox values to NVDA configuration."""
        try:
            config.conf[CONFIG_SECTION][CONFIG_KEY_CONFIRM_DELETE] = (
                self._confirmDeleteCb.GetValue()
            )
            config.conf[CONFIG_SECTION][CONFIG_KEY_CONTEXT_CAPTURE] = (
                self._contextCaptureCb.GetValue()
            )
            log.debug(
                "Favorites Hub settingsPanel: saved — confirmDelete=%s, contextCapture=%s",
                self._confirmDeleteCb.GetValue(),
                self._contextCaptureCb.GetValue(),
            )
        except Exception as exc:
            log.error("Favorites Hub settingsPanel: error saving settings: %s", exc)
