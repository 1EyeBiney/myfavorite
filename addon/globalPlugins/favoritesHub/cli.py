# Favorites Hub — NVDA 2026.1 Global Plugin
# cli.py: Subprocess execution engine for CliEntry items.
#
# Thread-safety contract (§5):
#   • execute() is called from the GUI thread (e.g. from a dialog button
#     handler via wx.CallAfter).
#   • The actual subprocess.run() call happens inside a daemon background
#     thread so the GUI remains responsive.
#   • All result announcements are dispatched back to the GUI thread via
#     wx.CallAfter so that ui.message / ui.browseableMessage are called
#     on the correct thread.
#   • shell=True entries generate a warning log but are not blocked here;
#     the UI is responsible for the confirmation dialog (§9.3).
#
# Copyright (C) 2026 1EyeBiney
# This file is covered by the GNU General Public License version 2.
# See the file COPYING for more details.

from __future__ import annotations

import subprocess
import threading

import addonHandler
import ui
import wx
from logHandler import log

from .schema import CliEntry

addonHandler.initTranslation()

# ---------------------------------------------------------------------------
# Threshold: output longer than this many characters is shown in a browseable
# message rather than spoken inline.
# ---------------------------------------------------------------------------
_BROWSE_THRESHOLD: int = 500


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def execute(entry: CliEntry) -> None:
	"""Spawn a daemon thread to run *entry*'s command.

	Returns immediately.  Results are dispatched to the GUI thread via
	wx.CallAfter.  MUST be called from the GUI thread (§5).
	"""
	if entry.shell:
		log.warning(
			"Favorites Hub CLI: running %r with shell=True — "
			"caller should have confirmed this with the user.",
			entry.command,
		)

	thread = threading.Thread(
		target=_worker,
		args=(entry,),
		daemon=True,
		name="favhub-cli-%s" % entry.id[:8],
	)
	thread.start()
	log.debug(
		"Favorites Hub CLI: spawned thread for %r (timeout=%ds)",
		entry.command,
		entry.timeoutSec,
	)


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def _worker(entry: CliEntry) -> None:
	"""Execute the command and dispatch the result to the GUI thread.

	Runs in a daemon thread.  Must not touch wx or NVDA's speech directly.
	"""
	cmd: list[str] = [entry.command] + list(entry.args)

	run_kwargs: dict = {
		"capture_output": True,
		"shell": entry.shell,
		"timeout": entry.timeoutSec,
		"text": True,
		"encoding": "utf-8",
		"errors": "replace",
	}
	if entry.cwd:
		run_kwargs["cwd"] = entry.cwd

	try:
		result = subprocess.run(cmd, **run_kwargs)
	except subprocess.TimeoutExpired:
		log.warning(
			"Favorites Hub CLI: %r timed out after %d s",
			entry.command,
			entry.timeoutSec,
		)
		wx.CallAfter(_announce_timeout, entry.name, entry.timeoutSec)
		return
	except FileNotFoundError as exc:
		log.error("Favorites Hub CLI: command not found %r: %s", entry.command, exc)
		wx.CallAfter(
			_announce_launch_error,
			entry.name,
			# Translators: CLI error detail when the executable is not found
			_("Command not found: {cmd}").format(cmd=entry.command),
		)
		return
	except OSError as exc:
		log.error("Favorites Hub CLI: OS error launching %r: %s", entry.command, exc)
		wx.CallAfter(_announce_launch_error, entry.name, str(exc))
		return
	except Exception as exc:  # noqa: BLE001
		log.error(
			"Favorites Hub CLI: unexpected error running %r: %s",
			entry.command,
			exc,
		)
		wx.CallAfter(_announce_launch_error, entry.name, str(exc))
		return

	stdout: str = result.stdout or ""
	stderr: str = result.stderr or ""
	exit_code: int = result.returncode

	log.debug(
		"Favorites Hub CLI: %r exited %d, stdout=%d chars, stderr=%d chars",
		entry.command,
		exit_code,
		len(stdout),
		len(stderr),
	)

	if entry.speakOutput:
		wx.CallAfter(_announce_output, entry.name, stdout, stderr, exit_code)
	else:
		# When speakOutput=False, only announce failures so the user knows
		# something went wrong.
		if exit_code != 0:
			wx.CallAfter(_announce_silent_failure, entry.name, exit_code, stderr)


# ---------------------------------------------------------------------------
# GUI-thread announcement helpers
# All functions below MUST be called via wx.CallAfter (or already on GUI thread).
# ---------------------------------------------------------------------------

def _announce_output(
	name: str,
	stdout: str,
	stderr: str,
	exit_code: int,
) -> None:
	"""Announce the combined stdout/stderr output of a completed command."""
	# Build the body text
	body = stdout.strip()
	if stderr.strip():
		# Translators: Separator label in CLI output between stdout and stderr
		body = body + "\n" + _("--- stderr ---") + "\n" + stderr.strip() if body else stderr.strip()
	if not body:
		# Translators: Placeholder spoken when a CLI command produces no output
		body = _("(no output)")

	# Build the title / prefix
	if exit_code != 0:
		# Translators: CLI announcement prefix when the command exits non-zero.
		# {name} is the entry name; {code} is the exit code number.
		title = _("{name} (exit {code})").format(name=name, code=exit_code)
	else:
		title = name

	if len(body) > _BROWSE_THRESHOLD:
		# Long output: open a browseable/scrollable read-only window.
		ui.browseableMessage(
			body,
			# Translators: Title of the browseable CLI output window.
			# {name} is the entry name.
			_("CLI Output: {name}").format(name=name),
		)
	else:
		ui.message(f"{title}: {body}")


def _announce_silent_failure(name: str, exit_code: int, stderr: str) -> None:
	"""Announce a non-zero exit code when speakOutput=False."""
	detail = stderr.strip()[:200] if stderr.strip() else ""
	# Translators: Spoken when a CLI command (with speakOutput=False) fails.
	# {name} is the entry name; {code} is the numeric exit code.
	msg = _("{name} exited with code {code}.").format(name=name, code=exit_code)
	if detail:
		msg += " " + detail
	ui.message(msg)


def _announce_timeout(name: str, timeout: int) -> None:
	"""Announce that a command was killed because it exceeded its timeout."""
	# Translators: Spoken when a CLI command times out.
	# {name} is the entry name; {timeout} is the number of seconds.
	ui.message(
		_("{name} timed out after {timeout} seconds.").format(
			name=name, timeout=timeout
		)
	)


def _announce_launch_error(name: str, detail: str) -> None:
	"""Announce that the command could not be started at all."""
	# Translators: Spoken when a CLI command cannot be launched.
	# {name} is the entry name; {detail} is the OS error description.
	ui.message(
		_("Could not run \u201c{name}\u201d: {detail}").format(
			name=name, detail=detail
		)
	)
