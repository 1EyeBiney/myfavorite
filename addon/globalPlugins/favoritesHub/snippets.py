# Favorites Hub — NVDA 2026.1 Global Plugin
# snippets.py: Token expansion engine for SnippetEntry items.
#
# Supported tokens (§7.3 of project_brief.md):
#   {{date}}       — Current date, ISO format YYYY-MM-DD
#   {{time}}       — Current time, HH:MM:SS (24-hour, local time)
#   {{datetime}}   — Combined ISO-8601 local datetime YYYY-MM-DDTHH:MM:SS
#   {{clipboard}}  — Current clipboard text at the moment of expansion
#   {{cursor}}     — Cursor-position marker; stripped in v1 clipboard mode
#                    (meaningful only in a future "typed" paste mode)
#   {{nl}}         — Newline character (\n)
#   {{tab}}        — Tab character (\t)
#   {{name}}       — The entry's display name
#   {{year}}       — Current 4-digit year
#   {{month}}      — Current 2-digit month (01–12)
#   {{day}}        — Current 2-digit day (01–31)
#   Unknown tokens are left unchanged (pass-through).
#
# Thread-safety: expand() and push_to_clipboard() MUST be called on the GUI
# thread because they access wx.TheClipboard and call ui.message.
#
# Copyright (C) 2026 1EyeBiney
# This file is covered by the GNU General Public License version 2.
# See the file COPYING for more details.

from __future__ import annotations

import re
from datetime import datetime

import addonHandler
import api
import ui
import wx
from logHandler import log

from .schema import SnippetEntry

addonHandler.initTranslation()

# ---------------------------------------------------------------------------
# Token regex — matches {{word}} where word is one or more word characters.
# ---------------------------------------------------------------------------
_TOKEN_RE: re.Pattern[str] = re.compile(r"\{\{(\w+)\}\}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def expand_and_copy(entry: SnippetEntry) -> None:
	"""Expand all tokens in *entry.body* and push the result to the clipboard.

	Flow:
	  1. Read the current clipboard text (needed for {{clipboard}} token).
	  2. Expand all recognised tokens.
	  3. Copy the expanded text to the clipboard via api.copyToClip().
	  4. Announce success (or failure) via ui.message.

	MUST be called on the GUI thread (§5).
	"""
	# Step 1 — snapshot the clipboard BEFORE we overwrite it, so {{clipboard}}
	# reflects the user's original content rather than our own output.
	prior_clipboard = _read_clipboard()

	# Step 2 — expand tokens
	try:
		expanded = expand(entry.body, entry_name=entry.name, prior_clipboard=prior_clipboard)
	except Exception as exc:
		log.error(
			"Favorites Hub snippets: token expansion failed for %r: %s",
			entry.name,
			exc,
		)
		# Translators: Spoken when snippet token expansion fails.
		# {name} is the entry name.
		ui.message(_("Failed to expand snippet \u201c{name}\u201d.").format(name=entry.name))
		return

	# Step 3 — push to clipboard
	try:
		api.copyToClip(expanded, notify=False)
	except Exception as exc:
		log.error(
			"Favorites Hub snippets: clipboard write failed for %r: %s",
			entry.name,
			exc,
		)
		# Translators: Spoken when copying a snippet to the clipboard fails.
		ui.message(_("Could not copy snippet to clipboard."))
		return

	# Step 4 — success announcement
	log.debug(
		"Favorites Hub snippets: copied %r (%d chars) to clipboard.",
		entry.name,
		len(expanded),
	)
	# Translators: Spoken after a snippet has been successfully copied to the clipboard.
	ui.message(_("Snippet copied to clipboard"))


def expand(
	body: str,
	*,
	entry_name: str = "",
	prior_clipboard: str = "",
) -> str:
	"""Expand all {{token}} placeholders in *body* and return the result.

	Unrecognised tokens are left in their original ``{{token}}`` form so that
	the user can see them and correct the entry rather than silently losing
	data.

	This function is pure (no side effects) and may be called from unit tests
	without a wx application running, as long as *prior_clipboard* is supplied
	explicitly.
	"""
	now = datetime.now()

	# Build a context dict once so the lambda closure is fast per-token.
	ctx: dict[str, str] = {
		"date":      now.strftime("%Y-%m-%d"),
		"time":      now.strftime("%H:%M:%S"),
		"datetime":  now.strftime("%Y-%m-%dT%H:%M:%S"),
		"year":      now.strftime("%Y"),
		"month":     now.strftime("%m"),
		"day":       now.strftime("%d"),
		"clipboard": prior_clipboard,
		"cursor":    "",          # stripped in v1 clipboard mode
		"nl":        "\n",
		"tab":       "\t",
		"name":      entry_name,
	}

	def _replace(match: re.Match[str]) -> str:
		token = match.group(1)
		if token in ctx:
			return ctx[token]
		# Unknown token: log once and pass through unchanged.
		log.debug("Favorites Hub snippets: unknown token {{%s}} — leaving as-is.", token)
		return match.group(0)

	return _TOKEN_RE.sub(_replace, body)


# ---------------------------------------------------------------------------
# Clipboard helpers (GUI thread only)
# ---------------------------------------------------------------------------

def _read_clipboard() -> str:
	"""Return the current plain-text clipboard content, or "" on any error.

	MUST be called on the GUI thread.
	"""
	try:
		if wx.TheClipboard.Open():
			try:
				data_obj = wx.TextDataObject()
				if wx.TheClipboard.GetData(data_obj):
					return data_obj.GetText()
			finally:
				wx.TheClipboard.Close()
	except Exception as exc:
		log.debug("Favorites Hub snippets: could not read clipboard: %s", exc)
	return ""
