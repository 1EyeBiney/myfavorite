# Favorites Hub — NVDA 2026.1 Global Plugin
# constants.py: Category enums, default gestures, schema/file name constants,
#               and the module-level script category label.
#
# Copyright (C) 2026 1EyeBiney
# This file is covered by the GNU General Public License version 2.
# See the file COPYING for more details.

import addonHandler
from enum import IntEnum, unique

addonHandler.initTranslation()

# ---------------------------------------------------------------------------
# Schema & file-system constants
# ---------------------------------------------------------------------------

#: Integer schema version embedded in every data.json document.
#: Increment this (and provide a migration path) when the document shape changes.
SCHEMA_VERSION: int = 1

#: Name of the subdirectory created inside the NVDA user config dir.
DATA_DIR_NAME: str = "favoritesHub"

#: Name of the primary data file inside DATA_DIR_NAME.
DATA_FILE_NAME: str = "data.json"

#: Suffix used while writing; must be on the same volume as DATA_FILE_NAME.
DATA_FILE_TMP_SUFFIX: str = ".tmp"

#: Suffix appended to a quarantined corrupt file, e.g. data.json.corrupt-20260514T120000Z
DATA_FILE_CORRUPT_SUFFIX: str = ".corrupt"

# ---------------------------------------------------------------------------
# Category identifiers
# ---------------------------------------------------------------------------

@unique
class Category(IntEnum):
	"""Ordered enumeration of the six Listbook pages.

	The integer value maps 1-to-1 with the wx.Listbook page index and also
	serves as the digit-key shortcut (pages 1–5; Tags is page 6 / index 5).
	"""
	FOLDERS = 0
	LINKS = 1
	SNIPPETS = 2
	CLIS = 3
	MACROS = 4
	TAGS = 5


#: Human-readable labels shown on the Listbook spine (translatable).
CATEGORY_LABELS: dict[Category, str] = {
	# Translators: Label for the Folders category in the Favorites Hub dialog
	Category.FOLDERS: _("Folders"),
	# Translators: Label for the Links category in the Favorites Hub dialog
	Category.LINKS: _("Links"),
	# Translators: Label for the Snippets category in the Favorites Hub dialog
	Category.SNIPPETS: _("Snippets"),
	# Translators: Label for the CLIs category in the Favorites Hub dialog
	Category.CLIS: _("CLIs"),
	# Translators: Label for the Macros category in the Favorites Hub dialog
	Category.MACROS: _("Macros"),
	# Translators: Label for the Tags category in the Favorites Hub dialog
	Category.TAGS: _("Tags"),
}

#: JSON key names used in the "entries" object — must stay in sync with schema.py.
CATEGORY_KEYS: dict[Category, str] = {
	Category.FOLDERS: "folders",
	Category.LINKS: "links",
	Category.SNIPPETS: "snippets",
	Category.CLIS: "clis",
	Category.MACROS: "macros",
}

#: Set of all content categories (excludes Tags which is a view, not a data key).
CONTENT_CATEGORIES: tuple[Category, ...] = (
	Category.FOLDERS,
	Category.LINKS,
	Category.SNIPPETS,
	Category.CLIS,
	Category.MACROS,
)

# ---------------------------------------------------------------------------
# Forbidden field names (security boundary — §3.5 of project_brief.md)
# ---------------------------------------------------------------------------

#: Fields that MUST be stripped from any incoming JSON entry, regardless of category.
#: The set is case-insensitive; comparison is performed after .lower() on field names.
FORBIDDEN_FIELDS: frozenset[str] = frozenset({
	"password",
	"credential",
	"secret",
	"token",
	"apikey",
})

# ---------------------------------------------------------------------------
# Default gesture strings (§11 of project_brief.md)
# ---------------------------------------------------------------------------

#: Default gesture for script_openHub.
GESTURE_OPEN_HUB: str = "kb:NVDA+alt+f"

#: Default gesture for script_openQuickPick.
GESTURE_OPEN_QUICK_PICK: str = "kb:NVDA+alt+q"

#: script_captureFolderHere is intentionally unbound by default.
GESTURE_CAPTURE_FOLDER_HERE: str | None = None

# ---------------------------------------------------------------------------
# Layered-gesture follow-up keys (§11.1 of project_brief.md)
# ---------------------------------------------------------------------------

#: Milliseconds the plugin waits for a follow-up key after NVDA+Alt+F.
LAYERED_GESTURE_TIMEOUT_MS: int = 1500

#: Mapping of follow-up key name → Category to open.
LAYERED_KEYS: dict[str, Category] = {
	"f": Category.FOLDERS,
	"l": Category.LINKS,
	"s": Category.SNIPPETS,
	"c": Category.CLIS,
	"m": Category.MACROS,
	"t": Category.TAGS,
}

# ---------------------------------------------------------------------------
# Script category label (§11 of project_brief.md)
# ---------------------------------------------------------------------------

# Translators: Category name shown in NVDA's Input Gestures dialog for all
# Favorites Hub scripts.
SCRIPT_CATEGORY: str = _("Favorites Hub")

# ---------------------------------------------------------------------------
# CLI constraints (§9 of project_brief.md)
# ---------------------------------------------------------------------------

#: Minimum and maximum values for CliEntry.timeoutSec.
CLI_TIMEOUT_MIN: int = 1
CLI_TIMEOUT_MAX: int = 120
CLI_TIMEOUT_DEFAULT: int = 15

# ---------------------------------------------------------------------------
# Macro constraints (§10 of project_brief.md)
# ---------------------------------------------------------------------------

#: Bounds for MacroEntry.interStepDelayMs.
MACRO_DELAY_MIN: int = 0
MACRO_DELAY_MAX: int = 2000
MACRO_DELAY_DEFAULT: int = 50

# ---------------------------------------------------------------------------
# Context capture budget (§8.2 of project_brief.md)
# ---------------------------------------------------------------------------

#: Maximum wall-clock seconds allowed for the Shell.Application enumeration.
CONTEXT_CAPTURE_BUDGET_SEC: float = 0.5

# ---------------------------------------------------------------------------
# NVDA config section and keys (§12 of project_brief.md)
# ---------------------------------------------------------------------------

CONFIG_SECTION: str = "favoritesHub"
CONFIG_KEY_CONFIRM_DELETE: str = "confirmBeforeDelete"
CONFIG_KEY_CONTEXT_CAPTURE: str = "contextCaptureEnabled"
CONFIG_KEY_LAST_TAB: str = "lastUsedTab"
