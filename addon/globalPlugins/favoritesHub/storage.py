# Favorites Hub — NVDA 2026.1 Global Plugin
# storage.py: JSON persistence layer — atomic saves, corrupt-file quarantine,
#             schema-version gating, in-process RLock, and the mutating()
#             context manager.
#
# Thread-safety contract (§5 of project_brief.md):
#   • All calls to load() and save_atomic() happen on the GUI thread.
#   • _lock is an RLock so that nested calls within the same thread are safe.
#   • No background I/O is performed in this module.
#
# Copyright (C) 2026 1EyeBiney
# This file is covered by the GNU General Public License version 2.
# See the file COPYING for more details.

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

import addonHandler
import globalVars
import wx
from gui import messageBox
from logHandler import log

from .constants import (
	CONFIG_SECTION,
	DATA_DIR_NAME,
	DATA_FILE_CORRUPT_SUFFIX,
	DATA_FILE_NAME,
	DATA_FILE_TMP_SUFFIX,
	FORBIDDEN_FIELDS,
	SCHEMA_VERSION,
)
from .schema import (
	ENTRY_FACTORIES,
	AnyEntry,
	FolderEntry,
	LinkEntry,
	MacroEntry,
	SnippetEntry,
	CliEntry,
	_utc_now_iso,
	_strip_forbidden,
)

addonHandler.initTranslation()

# ---------------------------------------------------------------------------
# Internal lock — one per process (NVDA runs as a single process, §4.4)
# ---------------------------------------------------------------------------

_lock: threading.RLock = threading.RLock()

# ---------------------------------------------------------------------------
# Document type alias
# ---------------------------------------------------------------------------

#: A "document" is the full in-memory representation of data.json.
Document = dict[str, Any]


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _data_dir() -> str:
	"""Return the absolute path to the favoritesHub data directory.

	The directory is *not* created here; creation happens inside save_atomic().
	"""
	return os.path.join(globalVars.appArgs.configPath, DATA_DIR_NAME)


def _data_path() -> str:
	"""Absolute path to data.json."""
	return os.path.join(_data_dir(), DATA_FILE_NAME)


def _tmp_path() -> str:
	"""Absolute path to the in-progress temp file."""
	return _data_dir() + os.sep + DATA_FILE_NAME + DATA_FILE_TMP_SUFFIX


def _corrupt_path() -> str:
	"""Absolute path to the quarantine destination for a corrupt file.

	Uses a UTC timestamp so multiple corruption events don't collide.
	"""
	ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
	return os.path.join(
		_data_dir(),
		DATA_FILE_NAME + DATA_FILE_CORRUPT_SUFFIX + "-" + ts,
	)


# ---------------------------------------------------------------------------
# Fresh (empty) document factory
# ---------------------------------------------------------------------------

def _fresh_document() -> Document:
	"""Return a valid empty document conforming to schema version 1."""
	now = _utc_now_iso()
	return {
		"schemaVersion": SCHEMA_VERSION,
		"createdUtc": now,
		"modifiedUtc": now,
		"entries": {
			"folders": [],
			"links": [],
			"snippets": [],
			"clis": [],
			"macros": [],
		},
	}


# ---------------------------------------------------------------------------
# Security: strip forbidden fields from raw entry dicts before hydration
# ---------------------------------------------------------------------------

def _sanitize_entries(raw_entries: dict[str, Any]) -> dict[str, Any]:
	"""Walk every entry in every category and strip forbidden fields.

	Returns a new dict; the original is not mutated.
	"""
	sanitized: dict[str, Any] = {}
	for key, items in raw_entries.items():
		if not isinstance(items, list):
			sanitized[key] = []
			continue
		clean_items = []
		for item in items:
			if isinstance(item, dict):
				clean_items.append(_strip_forbidden(item, context=key))
			# Non-dict items are silently dropped (corrupt data)
		sanitized[key] = clean_items
	return sanitized


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load() -> Document:
	"""Load and return the document from data.json.

	Behaviour per §4.2:
	  • File absent  → return fresh empty document (do NOT create the file).
	  • Schema version too high → log error, return fresh empty document.
	  • JSON parse error → quarantine the file, return fresh empty document,
	    queue a user-visible warning.
	  • Any other read error → same as parse error.

	MUST be called on the GUI thread (§5).
	"""
	path = _data_path()

	if not os.path.isfile(path):
		log.debug("Favorites Hub storage: data.json not found; starting fresh.")
		return _fresh_document()

	try:
		with open(path, encoding="utf-8", errors="strict") as fh:
			raw: Any = json.load(fh)
	except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
		log.error(
			"Favorites Hub storage: failed to parse data.json (%s). "
			"Quarantining and returning empty document.",
			exc,
		)
		_quarantine(path)
		_notify_corrupt()
		return _fresh_document()

	if not isinstance(raw, dict):
		log.error(
			"Favorites Hub storage: data.json is not a JSON object. Quarantining."
		)
		_quarantine(path)
		_notify_corrupt()
		return _fresh_document()

	# Schema-version gate
	stored_version = raw.get("schemaVersion", 0)
	try:
		stored_version = int(stored_version)
	except (TypeError, ValueError):
		stored_version = 0

	if stored_version > SCHEMA_VERSION:
		log.error(
			"Favorites Hub storage: data.json schemaVersion %d is newer than "
			"supported version %d. Cannot open. Returning empty document.",
			stored_version,
			SCHEMA_VERSION,
		)
		_notify_future_schema(stored_version)
		return _fresh_document()

	# Sanitize & hydrate
	raw_entries = raw.get("entries", {})
	if not isinstance(raw_entries, dict):
		raw_entries = {}

	sanitized_entries = _sanitize_entries(raw_entries)

	doc = _fresh_document()
	doc["schemaVersion"] = stored_version or SCHEMA_VERSION
	doc["createdUtc"] = str(raw.get("createdUtc", doc["createdUtc"]))
	doc["modifiedUtc"] = str(raw.get("modifiedUtc", doc["modifiedUtc"]))
	doc["entries"] = sanitized_entries

	# Ensure every known category key exists (absent key = empty list)
	for key in ("folders", "links", "snippets", "clis", "macros"):
		doc["entries"].setdefault(key, [])

	log.debug("Favorites Hub storage: loaded %d entries.", _count_entries(doc))
	return doc


# ---------------------------------------------------------------------------
# Save (atomic, §4.1)
# ---------------------------------------------------------------------------

def save_atomic(doc: Document) -> None:
	"""Persist *doc* to data.json using a write-fsync-replace sequence.

	Behaviour per §4.1:
	  1. Serialize to UTF-8 JSON.
	  2. Write to data.json.tmp (same directory = same NTFS volume).
	  3. fsync the file descriptor.
	  4. os.replace(tmp, data.json) — atomic on NTFS.
	  5. On any error: unlink the tmp file, leave data.json intact, log, notify.

	MUST be called on the GUI thread (§5).
	"""
	data_dir = _data_dir()
	tmp = _tmp_path()
	dest = _data_path()

	try:
		os.makedirs(data_dir, exist_ok=True)
	except OSError as exc:
		log.error("Favorites Hub storage: cannot create data directory: %s", exc)
		_notify_save_error(str(exc))
		return

	# Update the top-level timestamp
	doc["modifiedUtc"] = _utc_now_iso()

	try:
		payload = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=False)
	except (TypeError, ValueError) as exc:
		log.error("Favorites Hub storage: JSON serialization failed: %s", exc)
		_notify_save_error(str(exc))
		return

	fd: int | None = None
	try:
		# Step 2: write to tmp
		fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
		os.write(fd, payload.encode("utf-8"))
		# Step 3: fsync
		os.fsync(fd)
		os.close(fd)
		fd = None
		# Step 4: atomic replace
		os.replace(tmp, dest)
		log.debug("Favorites Hub storage: saved successfully to %s", dest)
	except OSError as exc:
		log.error("Favorites Hub storage: atomic save failed: %s", exc)
		# Step 5: cleanup
		if fd is not None:
			try:
				os.close(fd)
			except OSError:
				pass
		_unlink_safe(tmp)
		_notify_save_error(str(exc))


# ---------------------------------------------------------------------------
# Mutating context manager (§4.3)
# ---------------------------------------------------------------------------

#: Module-level in-memory document cache.  Initialized to None; populated on
#: first call to mutating() or an explicit load() call.
_cached_doc: Document | None = None


def get_document() -> Document:
	"""Return the current in-memory document, loading from disk if needed.

	MUST be called on the GUI thread.
	"""
	global _cached_doc
	with _lock:
		if _cached_doc is None:
			_cached_doc = load()
		return _cached_doc


@contextmanager
def mutating() -> Generator[Document, None, None]:
	"""Context manager for atomic load → mutate → save cycles.

	Usage::

		with storage.mutating() as doc:
			doc["entries"]["folders"].append(entry.to_dict())

	The RLock is held for the entire block.  The document is saved atomically
	when the block exits without raising.  On exception the in-memory cache is
	left in the mutated state but the disk file is unchanged; the caller should
	handle the exception appropriately.

	MUST be called on the GUI thread (§5).
	"""
	global _cached_doc
	with _lock:
		if _cached_doc is None:
			_cached_doc = load()
		try:
			yield _cached_doc
			save_atomic(_cached_doc)
		except Exception:
			# Leave cache intact; caller decides whether to reload.
			raise


def invalidate_cache() -> None:
	"""Force the next get_document() call to reload from disk.

	Useful after an external modification (e.g., import).
	"""
	global _cached_doc
	with _lock:
		_cached_doc = None


# ---------------------------------------------------------------------------
# Typed helpers for callers
# ---------------------------------------------------------------------------

def hydrate_document(doc: Document) -> dict[str, list[AnyEntry]]:
	"""Convert the raw 'entries' dict into typed dataclass instances.

	Returns a dict keyed by category name with lists of strongly-typed entries.
	Entries that fail deserialization are dropped with a warning.
	"""
	result: dict[str, list[AnyEntry]] = {}
	for key, factory in ENTRY_FACTORIES.items():
		raw_list = doc["entries"].get(key, [])
		typed: list[AnyEntry] = []
		for raw in raw_list:
			try:
				typed.append(factory.from_dict(raw))
			except Exception as exc:
				log.warning(
					"Favorites Hub storage: skipping malformed %s entry: %s", key, exc
				)
		result[key] = typed
	return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _quarantine(path: str) -> None:
	"""Rename a corrupt file to a timestamped quarantine name."""
	dest = _corrupt_path()
	try:
		os.replace(path, dest)
		log.warning("Favorites Hub storage: quarantined corrupt file to %s", dest)
	except OSError as exc:
		log.error(
			"Favorites Hub storage: could not quarantine %s → %s: %s", path, dest, exc
		)


def _unlink_safe(path: str) -> None:
	"""Remove a file, suppressing errors."""
	try:
		os.unlink(path)
	except OSError:
		pass


def _count_entries(doc: Document) -> int:
	"""Return total number of entries across all categories."""
	return sum(
		len(v) for v in doc.get("entries", {}).values() if isinstance(v, list)
	)


# ---------------------------------------------------------------------------
# User-facing notifications (queued to the GUI thread via wx.CallAfter)
# ---------------------------------------------------------------------------

def _notify_corrupt() -> None:
	"""Queue a dialog informing the user that data.json was corrupt."""
	def _show() -> None:
		messageBox(
			# Translators: Message shown when the Favorites Hub data file is corrupt
			_(
				"The Favorites Hub data file could not be read and has been quarantined. "
				"Your entries have been reset. The corrupt file has been renamed for inspection."
			),
			# Translators: Title of the Favorites Hub data corruption dialog
			_("Favorites Hub — Data Error"),
			wx.OK | wx.ICON_ERROR,
		)
	wx.CallAfter(_show)


def _notify_save_error(detail: str) -> None:
	"""Queue a dialog informing the user that a save failed."""
	def _show() -> None:
		messageBox(
			# Translators: Message shown when saving Favorites Hub data fails.
			# {detail} is the OS error message.
			_("Favorites Hub could not save your data. Your previous data is intact.\n\nDetail: {detail}").format(
				detail=detail
			),
			# Translators: Title of the Favorites Hub save error dialog
			_("Favorites Hub — Save Error"),
			wx.OK | wx.ICON_ERROR,
		)
	wx.CallAfter(_show)


def _notify_future_schema(version: int) -> None:
	"""Queue a dialog informing the user that the schema is from a newer add-on."""
	def _show() -> None:
		messageBox(
			# Translators: Message shown when data.json was written by a newer version.
			# {version} is the schema version number found in the file.
			_(
				"The Favorites Hub data file was created by a newer version of this add-on "
				"(schema version {version}) and cannot be opened. "
				"Please update the add-on, or remove the data file to start fresh."
			).format(version=version),
			# Translators: Title of the Favorites Hub schema version mismatch dialog
			_("Favorites Hub — Incompatible Data"),
			wx.OK | wx.ICON_ERROR,
		)
	wx.CallAfter(_show)
