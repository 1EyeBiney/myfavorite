# Favorites Hub — NVDA 2026.1 Global Plugin
# macros.py: Keystroke replay engine for MacroEntry items.
#
# Design rules (§5 and §10):
#   • Re-entry is blocked by a module-level boolean flag (_running).
#     All code that reads or writes _running runs on the GUI thread, so no
#     threading primitives are needed for the flag itself.
#   • Inter-step delays are implemented with wx.CallLater chains.
#     time.sleep() is strictly forbidden here.
#   • Gestures are parsed via keyboardHandler.KeyboardInputGesture.fromName()
#     and validated before playback begins (fail-fast, not mid-sequence).
#   • A cancel() function is provided so __init__.py can abort playback on
#     terminate().
#
# Thread-safety: play(), cancel(), and all _play_step() callbacks MUST be
# called on the GUI thread (wx.CallLater guarantees this automatically).
#
# Copyright (C) 2026 1EyeBiney
# This file is covered by the GNU General Public License version 2.
# See the file COPYING for more details.

from __future__ import annotations

import addonHandler
import keyboardHandler
import ui
import wx
from logHandler import log

from .schema import MacroEntry

addonHandler.initTranslation()

# ---------------------------------------------------------------------------
# Module-level state (GUI thread only)
# ---------------------------------------------------------------------------

#: True while a macro is in the middle of playback.
_running: bool = False

#: Reference to the pending wx.CallLater timer so cancel() can stop it.
_pending_timer: wx.CallLater | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def play(entry: MacroEntry) -> None:
	"""Begin replaying *entry*'s gesture sequence on the GUI thread.

	If a macro is already running, announces a warning and returns without
	starting a new sequence.  Parses and validates all gestures up front so
	that an invalid name is caught before any keystrokes are sent.

	MUST be called from the GUI thread.
	"""
	global _running

	if _running:
		# Translators: Spoken when the user tries to run a macro while one is
		# already in progress.
		ui.message(_("A macro is already running. Please wait."))
		return

	parsed = _parse_gestures(entry)
	if parsed is None:
		# _parse_gestures already announced the error.
		return

	_running = True
	log.debug(
		"Favorites Hub macros: starting playback of %r (%d steps, %d ms delay)",
		entry.name,
		len(parsed),
		entry.interStepDelayMs,
	)
	_play_step(parsed, 0, entry.interStepDelayMs, entry.name)


def cancel() -> None:
	"""Abort any in-progress macro playback immediately.

	Safe to call even when no macro is running.  MUST be called from the
	GUI thread (e.g. from GlobalPlugin.terminate()).
	"""
	global _running, _pending_timer

	if _pending_timer is not None:
		try:
			if _pending_timer.IsRunning():
				_pending_timer.Stop()
		except Exception:
			pass
		_pending_timer = None

	if _running:
		log.debug("Favorites Hub macros: playback cancelled externally.")
		_running = False


# ---------------------------------------------------------------------------
# Gesture parsing (called before any step is sent)
# ---------------------------------------------------------------------------

def _parse_gestures(entry: MacroEntry) -> list[keyboardHandler.KeyboardInputGesture] | None:
	"""Validate and parse all gesture strings in *entry*.

	Returns the list of gesture objects on success, or None on the first
	validation error (an error message is announced to the user).
	"""
	if not entry.gestures:
		# Translators: Spoken when a macro entry has an empty gesture list.
		# {name} is the entry name.
		ui.message(_("Macro \u201c{name}\u201d has no gestures.").format(name=entry.name))
		return None

	parsed: list[keyboardHandler.KeyboardInputGesture] = []
	for gesture_name in entry.gestures:
		try:
			gesture = keyboardHandler.KeyboardInputGesture.fromName(gesture_name)
			parsed.append(gesture)
		except Exception as exc:
			log.warning(
				"Favorites Hub macros: cannot parse gesture %r in %r: %s",
				gesture_name,
				entry.name,
				exc,
			)
			# Translators: Spoken when a gesture string in a macro is invalid.
			# {name} is the entry name; {gesture} is the bad gesture string.
			ui.message(
				_(
					"Invalid gesture in macro \u201c{name}\u201d: {gesture}"
				).format(name=entry.name, gesture=gesture_name)
			)
			return None

	return parsed


# ---------------------------------------------------------------------------
# Playback chain (wx.CallLater-based, GUI thread only)
# ---------------------------------------------------------------------------

def _play_step(
	gestures: list[keyboardHandler.KeyboardInputGesture],
	index: int,
	delay_ms: int,
	macro_name: str,
) -> None:
	"""Send the gesture at *index*, then schedule the next step.

	This function is the wx.CallLater callback target.  It runs on the GUI
	thread.  After sending the gesture it either schedules the next step via
	wx.CallLater (using delay_ms) or, if this was the last step, finalises
	playback.
	"""
	global _running, _pending_timer

	# Guard: playback may have been cancelled between the timer firing and this
	# callback executing (unlikely but possible during rapid terminate()).
	if not _running:
		log.debug(
			"Favorites Hub macros: step %d of %r skipped (playback was cancelled).",
			index,
			macro_name,
		)
		return

	gesture = gestures[index]
	try:
		gesture.send()
	except Exception as exc:
		log.error(
			"Favorites Hub macros: error sending step %d of %r: %s",
			index,
			macro_name,
			exc,
		)
		_running = False
		_pending_timer = None
		# Translators: Spoken when a macro gesture fails during playback.
		# {name} is the entry name; {step} is the 1-based step number.
		ui.message(
			_("Macro \u201c{name}\u201d failed at step {step}.").format(
				name=macro_name, step=index + 1
			)
		)
		return

	next_index = index + 1
	if next_index < len(gestures):
		# Schedule the next step.  Clamp delay to at least 1 ms to avoid
		# potential wx.CallLater edge cases with a zero timeout.
		effective_delay = max(delay_ms, 1)
		_pending_timer = wx.CallLater(
			effective_delay,
			_play_step,
			gestures,
			next_index,
			delay_ms,
			macro_name,
		)
	else:
		# All steps completed successfully.
		_running = False
		_pending_timer = None
		log.debug(
			"Favorites Hub macros: finished playing %r (%d steps).",
			macro_name,
			len(gestures),
		)
