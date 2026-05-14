# Favorites Hub — NVDA 2026.1 Global Plugin
# __init__.py: GlobalPlugin stub — gesture bindings, settings panel
#              registration, and lifecycle management.
#
# Thread-safety contract (§5):
#   • All wx calls happen on the GUI thread via @script callbacks.
#   • COM calls (context capture) are also dispatched on the GUI/main thread.
#   • No blocking I/O is performed in this module.
#
# Copyright (C) 2026 1EyeBiney
# This file is covered by the GNU General Public License version 2.
# See the file COPYING for more details.

import addonHandler
import globalPluginHandler
import gui
import wx
from logHandler import log
from scriptHandler import script

from .constants import (
	GESTURE_CAPTURE_FOLDER_HERE,
	GESTURE_OPEN_HUB,
	GESTURE_OPEN_QUICK_PICK,
	SCRIPT_CATEGORY,
)

addonHandler.initTranslation()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	"""Favorites Hub global plugin entry-point for NVDA 2026.1."""

	# Declared here so NVDA's gesture infrastructure picks it up.
	scriptCategory = SCRIPT_CATEGORY

	def __init__(self) -> None:
		super().__init__()
		self._registerSettingsPanel()
		log.debug("Favorites Hub: GlobalPlugin initialised.")

	def terminate(self) -> None:
		"""Called by NVDA when the add-on is unloaded or NVDA is exiting."""
		self._unregisterSettingsPanel()
		log.debug("Favorites Hub: GlobalPlugin terminated.")

	# ------------------------------------------------------------------
	# Settings panel (§12)
	# ------------------------------------------------------------------

	def _registerSettingsPanel(self) -> None:
		"""Register the Favorites Hub settings panel with the NVDA Settings dialog."""
		try:
			from .gui.settingsPanel import FavoritesHubSettingsPanel  # type: ignore[import]
			gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(
				FavoritesHubSettingsPanel
			)
		except ImportError:
			# Panel module not yet implemented; silently skip during bootstrap.
			log.debug("Favorites Hub: settings panel module not yet available.")

	def _unregisterSettingsPanel(self) -> None:
		"""Remove the Favorites Hub panel from the NVDA Settings dialog."""
		try:
			from .gui.settingsPanel import FavoritesHubSettingsPanel  # type: ignore[import]
			if FavoritesHubSettingsPanel in gui.settingsDialogs.NVDASettingsDialog.categoryClasses:
				gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(
					FavoritesHubSettingsPanel
				)
		except ImportError:
			pass

	# ------------------------------------------------------------------
	# Script: open main Favorites Hub dialog (§7)
	# ------------------------------------------------------------------

	@script(
		# Translators: Description of the script that opens the Favorites Hub dialog
		description=_("Opens the Favorites Hub dialog"),
		category=SCRIPT_CATEGORY,
		gesture=GESTURE_OPEN_HUB,
	)
	def script_openHub(self, gesture) -> None:
		"""Open the main Favorites Hub Listbook dialog."""
		wx.CallAfter(self._showHubDialog)

	def _showHubDialog(self) -> None:
		"""Instantiate and show the main dialog (GUI-thread only)."""
		try:
			from .gui.mainDialog import FavoritesHubDialog  # type: ignore[import]
			dlg = FavoritesHubDialog(gui.mainFrame)
			gui.mainFrame.prePopup()
			dlg.ShowModal()
			gui.mainFrame.postPopup()
		except ImportError:
			# Main dialog not yet implemented; placeholder announcement.
			import ui
			# Translators: Spoken when the Favorites Hub dialog is not yet available
			ui.message(_("Favorites Hub dialog is not yet available."))

	# ------------------------------------------------------------------
	# Script: open Quick-Pick overlay (§6)
	# ------------------------------------------------------------------

	@script(
		# Translators: Description of the script that opens the Quick-Pick overlay
		description=_("Opens the Favorites Hub Quick-Pick overlay"),
		category=SCRIPT_CATEGORY,
		gesture=GESTURE_OPEN_QUICK_PICK,
	)
	def script_openQuickPick(self, gesture) -> None:
		"""Open the floating Quick-Pick overlay for fuzzy search across all entries."""
		wx.CallAfter(self._showQuickPickDialog)

	def _showQuickPickDialog(self) -> None:
		"""Instantiate and show the Quick-Pick overlay (GUI-thread only)."""
		try:
			from .gui.quickPick import QuickPickDialog  # type: ignore[import]
			dlg = QuickPickDialog(gui.mainFrame)
			gui.mainFrame.prePopup()
			dlg.ShowModal()
			gui.mainFrame.postPopup()
		except ImportError:
			import ui
			# Translators: Spoken when the Quick-Pick overlay is not yet available
			ui.message(_("Favorites Hub Quick-Pick is not yet available."))

	# ------------------------------------------------------------------
	# Script: capture current folder and add to Favorites (§8)
	# ------------------------------------------------------------------

	@script(
		# Translators: Description of the script that captures the current folder
		description=_("Captures the currently focused folder and adds it to Favorites Hub"),
		category=SCRIPT_CATEGORY,
		# Intentionally unbound by default (§11); user assigns via Input Gestures
		gesture=GESTURE_CAPTURE_FOLDER_HERE,
	)
	def script_captureFolderHere(self, gesture) -> None:
		"""Detect the active Explorer path and open the Add Folder dialog pre-filled."""
		wx.CallAfter(self._captureFolderHere)

	def _captureFolderHere(self) -> None:
		"""Perform context capture and show the Add dialog (GUI-thread only)."""
		try:
			from .context import capture_active_folder  # type: ignore[import]
			from .gui.mainDialog import FavoritesHubDialog  # type: ignore[import]
			path = capture_active_folder()
			if path:
				dlg = FavoritesHubDialog(gui.mainFrame, prefillPath=path)
				gui.mainFrame.prePopup()
				dlg.ShowModal()
				gui.mainFrame.postPopup()
			else:
				import ui
				# Translators: Spoken when no folder path could be detected
				ui.message(_("No folder could be detected from the current window."))
		except ImportError:
			import ui
			# Translators: Spoken when the capture feature is not yet available
			ui.message(_("Folder capture is not yet available."))
