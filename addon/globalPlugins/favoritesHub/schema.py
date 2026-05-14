# Favorites Hub — NVDA 2026.1 Global Plugin
# schema.py: Dataclasses for all five entry categories plus validation helpers.
#             Enforces the §3 JSON schema (version 1) and the §3.5 security
#             boundary (forbidden field names).
#
# Copyright (C) 2026 1EyeBiney
# This file is covered by the GNU General Public License version 2.
# See the file COPYING for more details.

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from logHandler import log

from .constants import (
	CLI_TIMEOUT_DEFAULT,
	CLI_TIMEOUT_MAX,
	CLI_TIMEOUT_MIN,
	FORBIDDEN_FIELDS,
	MACRO_DELAY_DEFAULT,
	MACRO_DELAY_MAX,
	MACRO_DELAY_MIN,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
	"""Return the current UTC time as an ISO-8601 string with 'Z' suffix."""
	return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id() -> str:
	"""Generate a new UUID4 string."""
	return str(uuid.uuid4())


def _strip_forbidden(data: dict[str, Any], context: str = "") -> dict[str, Any]:
	"""Remove any key whose lowercase name is in FORBIDDEN_FIELDS.

	Logs a warning for each stripped field.  Returns a new dict; the original
	is not mutated.  This is the primary enforcement point for §3.5.
	"""
	clean: dict[str, Any] = {}
	for key, value in data.items():
		if key.lower() in FORBIDDEN_FIELDS:
			log.warning(
				"Favorites Hub: stripped forbidden field %r from %s entry (security boundary §3.5)",
				key,
				context,
			)
		else:
			clean[key] = value
	return clean


def _coerce_tags(raw: Any) -> list[str]:
	"""Coerce any tag value to a list of stripped, non-empty strings."""
	if not isinstance(raw, list):
		return []
	return [str(t).strip() for t in raw if str(t).strip()]


# ---------------------------------------------------------------------------
# Base entry
# ---------------------------------------------------------------------------

@dataclass
class BaseEntry:
	"""Fields common to every entry regardless of category (§3.3)."""

	id: str = field(default_factory=_new_id)
	name: str = ""
	tags: list[str] = field(default_factory=list)
	createdUtc: str = field(default_factory=_utc_now_iso)
	modifiedUtc: str = field(default_factory=_utc_now_iso)
	notes: str = ""

	# ------------------------------------------------------------------
	# Serialisation helpers
	# ------------------------------------------------------------------

	def to_dict(self) -> dict[str, Any]:
		"""Return a plain dict suitable for json.dumps."""
		return {
			"id": self.id,
			"name": self.name,
			"tags": self.tags,
			"createdUtc": self.createdUtc,
			"modifiedUtc": self.modifiedUtc,
			"notes": self.notes,
		}

	def touch(self) -> None:
		"""Update modifiedUtc to the current UTC time."""
		self.modifiedUtc = _utc_now_iso()

	# ------------------------------------------------------------------
	# Validation
	# ------------------------------------------------------------------

	def validate(self) -> list[str]:
		"""Return a list of human-readable error strings (empty = valid)."""
		errors: list[str] = []
		if not self.name.strip():
			errors.append("name must not be empty")
		if not self.id:
			errors.append("id must not be empty")
		return errors

	# ------------------------------------------------------------------
	# Deserialization helpers (used by from_dict on subclasses)
	# ------------------------------------------------------------------

	@classmethod
	def _base_kwargs(cls, data: dict[str, Any]) -> dict[str, Any]:
		"""Extract and sanitize common fields from a raw dict."""
		safe = _strip_forbidden(data, context=cls.__name__)
		return {
			"id": str(safe.get("id", _new_id())),
			"name": str(safe.get("name", "")),
			"tags": _coerce_tags(safe.get("tags", [])),
			"createdUtc": str(safe.get("createdUtc", _utc_now_iso())),
			"modifiedUtc": str(safe.get("modifiedUtc", _utc_now_iso())),
			"notes": str(safe.get("notes", "")),
		}


# ---------------------------------------------------------------------------
# FolderEntry (§3.4)
# ---------------------------------------------------------------------------

@dataclass
class FolderEntry(BaseEntry):
	"""An entry representing a filesystem path or UNC path."""

	path: str = ""
	#: Reserved for v2; MUST be None in v1.
	openWith: None = None

	def to_dict(self) -> dict[str, Any]:
		base = super().to_dict()
		base["path"] = self.path
		base["openWith"] = None
		return base

	def validate(self) -> list[str]:
		errors = super().validate()
		if not self.path.strip():
			errors.append("path must not be empty")
		return errors

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> "FolderEntry":
		kwargs = cls._base_kwargs(data)
		safe = _strip_forbidden(data, context="FolderEntry")
		kwargs["path"] = str(safe.get("path", ""))
		# openWith is reserved; always force to None regardless of stored value
		kwargs["openWith"] = None
		return cls(**kwargs)


# ---------------------------------------------------------------------------
# LinkEntry (§3.4)
# ---------------------------------------------------------------------------

_ALLOWED_LINK_SCHEMES: tuple[str, ...] = ("http://", "https://", "mailto:")


@dataclass
class LinkEntry(BaseEntry):
	"""An entry representing a web URL or mailto address."""

	url: str = ""
	#: Reserved for v2; MUST be None in v1.
	browser: None = None

	def to_dict(self) -> dict[str, Any]:
		base = super().to_dict()
		base["url"] = self.url
		base["browser"] = None
		return base

	def validate(self) -> list[str]:
		errors = super().validate()
		if not any(self.url.startswith(s) for s in _ALLOWED_LINK_SCHEMES):
			errors.append(
				"url must start with http://, https://, or mailto: — got: %r" % self.url
			)
		return errors

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> "LinkEntry":
		kwargs = cls._base_kwargs(data)
		safe = _strip_forbidden(data, context="LinkEntry")
		kwargs["url"] = str(safe.get("url", ""))
		kwargs["browser"] = None
		return cls(**kwargs)


# ---------------------------------------------------------------------------
# SnippetEntry (§3.4)
# ---------------------------------------------------------------------------

@dataclass
class SnippetEntry(BaseEntry):
	"""An entry representing an expandable text snippet."""

	body: str = ""
	#: v1 only supports "clipboard"; field reserved for future "typed" mode.
	pasteMode: str = "clipboard"

	def to_dict(self) -> dict[str, Any]:
		base = super().to_dict()
		base["body"] = self.body
		base["pasteMode"] = "clipboard"
		return base

	def validate(self) -> list[str]:
		errors = super().validate()
		if not self.body:
			errors.append("body must not be empty")
		return errors

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> "SnippetEntry":
		kwargs = cls._base_kwargs(data)
		safe = _strip_forbidden(data, context="SnippetEntry")
		kwargs["body"] = str(safe.get("body", ""))
		# Force pasteMode to "clipboard" in v1 regardless of stored value
		kwargs["pasteMode"] = "clipboard"
		return cls(**kwargs)


# ---------------------------------------------------------------------------
# CliEntry (§3.4)
# ---------------------------------------------------------------------------

@dataclass
class CliEntry(BaseEntry):
	"""An entry representing a command-line command to execute."""

	command: str = ""
	args: list[str] = field(default_factory=list)
	#: MUST default to False.  UI warns when user sets True.
	shell: bool = False
	cwd: str | None = None
	timeoutSec: int = CLI_TIMEOUT_DEFAULT
	speakOutput: bool = True

	def to_dict(self) -> dict[str, Any]:
		base = super().to_dict()
		base["command"] = self.command
		base["args"] = self.args
		base["shell"] = self.shell
		base["cwd"] = self.cwd
		base["timeoutSec"] = self.timeoutSec
		base["speakOutput"] = self.speakOutput
		return base

	def validate(self) -> list[str]:
		errors = super().validate()
		if not self.command.strip():
			errors.append("command must not be empty")
		if not CLI_TIMEOUT_MIN <= self.timeoutSec <= CLI_TIMEOUT_MAX:
			errors.append(
				"timeoutSec must be between %d and %d" % (CLI_TIMEOUT_MIN, CLI_TIMEOUT_MAX)
			)
		if not isinstance(self.args, list):
			errors.append("args must be a list of strings")
		else:
			for i, a in enumerate(self.args):
				if not isinstance(a, str):
					errors.append("args[%d] must be a string, got %r" % (i, type(a).__name__))
		return errors

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> "CliEntry":
		kwargs = cls._base_kwargs(data)
		safe = _strip_forbidden(data, context="CliEntry")

		kwargs["command"] = str(safe.get("command", ""))

		raw_args = safe.get("args", [])
		kwargs["args"] = [str(a) for a in raw_args] if isinstance(raw_args, list) else []

		kwargs["shell"] = bool(safe.get("shell", False))

		raw_cwd = safe.get("cwd", None)
		kwargs["cwd"] = str(raw_cwd) if raw_cwd is not None else None

		raw_timeout = safe.get("timeoutSec", CLI_TIMEOUT_DEFAULT)
		try:
			timeout = int(raw_timeout)
		except (TypeError, ValueError):
			timeout = CLI_TIMEOUT_DEFAULT
		kwargs["timeoutSec"] = max(CLI_TIMEOUT_MIN, min(CLI_TIMEOUT_MAX, timeout))

		kwargs["speakOutput"] = bool(safe.get("speakOutput", True))
		return cls(**kwargs)


# ---------------------------------------------------------------------------
# MacroEntry (§3.4)
# ---------------------------------------------------------------------------

@dataclass
class MacroEntry(BaseEntry):
	"""An entry representing a sequence of simulated keystrokes."""

	gestures: list[str] = field(default_factory=list)
	interStepDelayMs: int = MACRO_DELAY_DEFAULT

	def to_dict(self) -> dict[str, Any]:
		base = super().to_dict()
		base["gestures"] = self.gestures
		base["interStepDelayMs"] = self.interStepDelayMs
		return base

	def validate(self) -> list[str]:
		errors = super().validate()
		if not self.gestures:
			errors.append("gestures list must not be empty")
		if not isinstance(self.gestures, list):
			errors.append("gestures must be a list of strings")
		else:
			for i, g in enumerate(self.gestures):
				if not isinstance(g, str) or not g.strip():
					errors.append("gestures[%d] must be a non-empty string" % i)
		if not MACRO_DELAY_MIN <= self.interStepDelayMs <= MACRO_DELAY_MAX:
			errors.append(
				"interStepDelayMs must be between %d and %d"
				% (MACRO_DELAY_MIN, MACRO_DELAY_MAX)
			)
		return errors

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> "MacroEntry":
		kwargs = cls._base_kwargs(data)
		safe = _strip_forbidden(data, context="MacroEntry")

		raw_gestures = safe.get("gestures", [])
		kwargs["gestures"] = (
			[str(g) for g in raw_gestures] if isinstance(raw_gestures, list) else []
		)

		raw_delay = safe.get("interStepDelayMs", MACRO_DELAY_DEFAULT)
		try:
			delay = int(raw_delay)
		except (TypeError, ValueError):
			delay = MACRO_DELAY_DEFAULT
		kwargs["interStepDelayMs"] = max(MACRO_DELAY_MIN, min(MACRO_DELAY_MAX, delay))

		return cls(**kwargs)


# ---------------------------------------------------------------------------
# Union type alias used by storage.py
# ---------------------------------------------------------------------------

AnyEntry = FolderEntry | LinkEntry | SnippetEntry | CliEntry | MacroEntry

# ---------------------------------------------------------------------------
# Per-category from_dict dispatcher
# ---------------------------------------------------------------------------

#: Maps the JSON key name to its from_dict constructor.
ENTRY_FACTORIES: dict[str, type[AnyEntry]] = {
	"folders": FolderEntry,
	"links": LinkEntry,
	"snippets": SnippetEntry,
	"clis": CliEntry,
	"macros": MacroEntry,
}
