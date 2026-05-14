# Favorites Hub — NVDA 2026.1 Global Plugin
# contextCapture.py: Detect the folder path for the currently active window.
#
# Priority order (§8 of project_brief.md):
#   1. Active Explorer window via Shell.Application COM (IShellWindows)
#   2. Win32 common dialog with class "#32770" via CDM_GETFOLDERPATH,
#      with an Edit-child fallback.
#   3. Desktop directory as last resort.
#
# Thread-safety (§5): ALL functions in this module MUST be called from the
# GUI / main thread.  COM objects are created and released on the same call
# stack; no COM pointers are stored at module scope.
#
# Wall-clock budget: CONTEXT_CAPTURE_BUDGET_SEC (0.5 s) is enforced via
# time.monotonic() checks before every potentially slow operation.
#
# Copyright (C) 2026 1EyeBiney
# This file is covered by the GNU General Public License version 2.
# See the file COPYING for more details.

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import time
import urllib.parse
from typing import Callable

import addonHandler
from logHandler import log

from .constants import CONTEXT_CAPTURE_BUDGET_SEC

addonHandler.initTranslation()

# ---------------------------------------------------------------------------
# Win32 constants
# ---------------------------------------------------------------------------

# Common-dialog message range (CommDlg.h):
#   CDM_FIRST = WM_USER + 100 = 0x0464
#   CDM_GETSPEC       = CDM_FIRST + 0  (filename only)
#   CDM_GETFILEPATH   = CDM_FIRST + 1  (full file path)
#   CDM_GETFOLDERPATH = CDM_FIRST + 2  (current folder path)
_CDM_GETFOLDERPATH: int = 0x0466

_MAX_PATH: int = 32768  # generous buffer for long UNC paths


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_active_folder_path() -> str | None:
	"""Return the folder path for the currently active window, or None.

	Enforces a wall-clock budget of CONTEXT_CAPTURE_BUDGET_SEC (0.5 s).
	MUST be called on the GUI / main thread.
	"""
	deadline: float = time.monotonic() + CONTEXT_CAPTURE_BUDGET_SEC

	# Priority 1: active Explorer window via Shell.Application COM
	if not _budget_expired(deadline, "before Explorer COM probe"):
		try:
			path = _from_explorer(deadline)
			if path:
				log.debug("Favorites Hub contextCapture: got path from Explorer: %s", path)
				return path
		except Exception as exc:
			log.debug("Favorites Hub contextCapture: Explorer COM probe failed: %s", exc)

	# Priority 2: Win32 common dialog (#32770)
	if not _budget_expired(deadline, "before dialog probe"):
		try:
			path = _from_dialog(deadline)
			if path:
				log.debug("Favorites Hub contextCapture: got path from dialog: %s", path)
				return path
		except Exception as exc:
			log.debug("Favorites Hub contextCapture: dialog probe failed: %s", exc)

	# Priority 3: desktop fallback
	return _desktop_fallback()


# ---------------------------------------------------------------------------
# Priority 1 — Shell.Application COM (Explorer windows)
# ---------------------------------------------------------------------------

def _from_explorer(deadline: float) -> str | None:
	"""Return the LocationURL of the active Explorer window as a Windows path.

	Iterates IShellWindows to find the window whose HWND matches the
	foreground window.  Returns None if no match or budget exhausted.
	"""
	import comtypes.client  # noqa: PLC0415 — lazy import; comtypes is NVDA-bundled

	foreground_hwnd: int = ctypes.windll.user32.GetForegroundWindow()
	if not foreground_hwnd:
		return None

	if _budget_expired(deadline, "after GetForegroundWindow"):
		return None

	# CreateObject is synchronous; wrap the whole block in try/except so any
	# COM initialisation failure degrades gracefully.
	shell = comtypes.client.CreateObject("Shell.Application")
	windows = shell.Windows()

	if _budget_expired(deadline, "after Shell.Application.Windows()"):
		return None

	try:
		count: int = windows.Count
	except Exception:
		return None

	for i in range(count):
		if _budget_expired(deadline, f"iterating window {i}/{count}"):
			break
		try:
			win = windows.Item(i)
			if win is None:
				continue
			if int(win.HWND) == foreground_hwnd:
				url: str = win.LocationURL or ""
				return _file_url_to_path(url)
		except Exception:
			# Window may have closed between Count and Item; skip silently.
			continue

	return None


# ---------------------------------------------------------------------------
# Priority 2 — Win32 common dialog (#32770)
# ---------------------------------------------------------------------------

def _from_dialog(deadline: float) -> str | None:
	"""Try to extract the current folder from a Win32 #32770 dialog.

	Strategy:
	  a) Verify the foreground window has class "#32770".
	  b) Send CDM_GETFOLDERPATH (OFN_EXPLORER-style dialogs only).
	  c) If that fails, enumerate child Edit / ComboBoxEx32 controls for a
	     path-like string (works for SHBrowseForFolder and custom dialogs).
	"""
	hwnd: int = ctypes.windll.user32.GetForegroundWindow()
	if not hwnd:
		return None

	cls_buf = ctypes.create_unicode_buffer(64)
	ctypes.windll.user32.GetClassNameW(hwnd, cls_buf, 64)
	if cls_buf.value != "#32770":
		return None

	if _budget_expired(deadline, "after class check"):
		return None

	# Attempt (a): CDM_GETFOLDERPATH
	path_buf = ctypes.create_unicode_buffer(_MAX_PATH)
	ret: int = ctypes.windll.user32.SendMessageW(
		hwnd,
		_CDM_GETFOLDERPATH,
		_MAX_PATH,
		path_buf,
	)
	if ret >= 0 and path_buf.value:
		path = path_buf.value.strip()
		if _looks_like_path(path):
			return path

	if _budget_expired(deadline, "after CDM_GETFOLDERPATH"):
		return None

	# Attempt (b): enumerate child edit controls
	return _path_from_child_controls(hwnd, deadline)


def _path_from_child_controls(parent_hwnd: int, deadline: float) -> str | None:
	"""Walk child windows looking for an Edit or ComboBoxEx32 with a path value."""
	candidates: list[str] = []

	# ctypes callback type for EnumChildWindows
	_EnumProc = ctypes.WINFUNCTYPE(
		ctypes.c_bool,
		ctypes.wintypes.HWND,
		ctypes.wintypes.LPARAM,
	)

	def _on_child(child_hwnd: int, _lparam: int) -> bool:
		if _budget_expired(deadline, "EnumChildWindows callback"):
			return False  # stop enumeration

		cls_buf = ctypes.create_unicode_buffer(64)
		ctypes.windll.user32.GetClassNameW(child_hwnd, cls_buf, 64)
		cls = cls_buf.value

		if cls in ("Edit", "ComboBoxEx32", "ComboBox"):
			length: int = ctypes.windll.user32.GetWindowTextLengthW(child_hwnd)
			# Minimum meaningful path length is 3 ("C:\") or 2 ("\\")
			if 2 < length < _MAX_PATH:
				text_buf = ctypes.create_unicode_buffer(length + 1)
				ctypes.windll.user32.GetWindowTextW(child_hwnd, text_buf, length + 1)
				text = text_buf.value.strip()
				if _looks_like_path(text):
					candidates.append(text)
		return True

	proc = _EnumProc(_on_child)
	ctypes.windll.user32.EnumChildWindows(parent_hwnd, proc, 0)

	if not candidates:
		return None
	# Prefer the longest plausible path (most specific)
	return max(candidates, key=len)


# ---------------------------------------------------------------------------
# Priority 3 — Desktop fallback
# ---------------------------------------------------------------------------

def _desktop_fallback() -> str:
	"""Return the user's Desktop directory as a last-resort answer."""
	# Try SHGetKnownFolderPath for FOLDERID_Desktop (more robust than expanduser)
	try:
		_FOLDERID_Desktop = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"
		import comtypes.client  # noqa: PLC0415
		import comtypes.shell  # noqa: PLC0415
		# This may not always work; fall through on any error.
	except Exception:
		pass
	return os.path.join(os.path.expanduser("~"), "Desktop")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _file_url_to_path(url: str) -> str | None:
	"""Convert a file:/// URL to an absolute Windows path.

	Example: "file:///C:/Users/Alice/Documents" → "C:\\Users\\Alice\\Documents"
	"""
	if not url:
		return None
	if url.startswith("file:///"):
		# Strip scheme; decode percent-encoding; normalise slashes
		raw = urllib.parse.unquote(url[8:])
		path = raw.replace("/", "\\").rstrip("\\")
		return path if path else None
	return None


def _looks_like_path(text: str) -> bool:
	"""Heuristic check: does the string resemble an absolute Windows path?"""
	if len(text) < 2:
		return False
	# Drive-letter path: "C:\" or "C:/" or just "C:"
	if len(text) >= 2 and text[1] == ":" and text[0].isalpha():
		return True
	# UNC path: "\\server\share" or "//server/share"
	if text.startswith("\\\\") or text.startswith("//"):
		return True
	return False


def _budget_expired(deadline: float, context: str = "") -> bool:
	"""Return True (and log a debug message) if the deadline has passed."""
	if time.monotonic() >= deadline:
		log.debug(
			"Favorites Hub contextCapture: budget exhausted%s.",
			(f" ({context})" if context else ""),
		)
		return True
	return False
