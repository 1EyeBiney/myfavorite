# Favorites Hub — NVDA 2026.1 Global Plugin
## Authoritative Project Brief (v1.0, immutable)

> **Audience:** An LLM coding agent implementing this add-on end-to-end.
> **Status:** This document is the single source of truth. Deviations require an explicit written change to this brief.

---

## 0. Target Environment (non-negotiable)

| Item | Value |
|---|---|
| NVDA version | **2026.1** (64-bit, Python 3.13) |
| `minimumNVDAVersion` | `2026.1` |
| `lastTestedNVDAVersion` | `2026.1` |
| Architecture | **AMD64 only**. No 32-bit assumptions, no 32-bit ctypes layouts. |
| Build system | scons via the standard NVDA AddonTemplate (already present in `AddonTemplate-master/`). |
| License | GPL v2 (required for NVDA add-ons). |
| Third-party pip packages | **None vendored unless absolutely required**. Use NVDA-bundled modules only (`comtypes`, `wx`, stdlib). If a vendor becomes necessary, it must live under `globalPlugins/favoritesHub/_vendor/` and be imported via path manipulation, not `sys.path` global pollution. |

---

## 1. Identity & Packaging

- **Add-on internal name:** `favoritesHub`
- **Summary (displayed):** `Favorites Hub`
- **Author:** as configured in `buildVars.py`
- **Add-on package name:** `favoritesHub-1.0.0.nvda-addon`
- **Top-level module path:** `addon/globalPlugins/favoritesHub/`
- The plugin **MUST** be a package (directory with `__init__.py`), not a single `.py` file, because it ships multiple modules.

---

## 2. File & Module Layout

```
addon/
├── globalPlugins/
│   └── favoritesHub/
│       ├── __init__.py              # GlobalPlugin class, script bindings, settings panel registration
│       ├── constants.py             # Category enums, default gestures, schema version, file names
│       ├── storage.py               # JSON load/save, atomic writes, schema migration, locking
│       ├── schema.py                # Dataclasses / TypedDicts for entries; validation
│       ├── contextCapture.py       # Active-Explorer / Open-Save dialog path capture (COM + UIA)
│       ├── snippets.py              # Token expansion engine ({{date}}, {{clipboard}}, {{cursor}})
│       ├── cli.py                   # Subprocess execution wrapper (background thread, output speak)
│       ├── macros.py                # Keystroke macro player (uses keyboardHandler)
│       ├── fuzzy.py                 # Fuzzy match scoring (pure Python, no deps)
│       ├── settingsPanel.py         # gui.SettingsPanel subclass
│       └── gui/
│           ├── __init__.py
│           ├── mainDialog.py        # Listbook-based main dialog
│           ├── quickPick.py         # Borderless fuzzy-search overlay
│           ├── entryDialogs.py      # Add/Edit modal dialogs (one per category)
│           ├── tagsView.py          # Tags & Smart Groups view (a Listbook page)
│           └── widgets.py           # Shared helpers (virtual ListCtrl, accelerator handlers)
├── doc/
│   └── en/
│       └── readme.md
└── installTasks.py                  # Optional; only if migration on install is needed
```

**Rule:** No top-level imports from `bar` re-exports (per NVDA API stability). All imports must come from the defining module.

---

## 3. JSON Data Schema — Version 1

### 3.1 Storage Location

- **Path:** `<NVDA user config dir>/favoritesHub/data.json`
- Resolved via `globalVars.appArgs.configPath` joined with `favoritesHub/data.json`.
- The `favoritesHub` directory is created on first save with `os.makedirs(..., exist_ok=True)`.
- This location ensures profile syncing and portable-NVDA compatibility.

### 3.2 Top-Level Document

```json
{
  "schemaVersion": 1,
  "createdUtc": "2026-05-14T00:00:00Z",
  "modifiedUtc": "2026-05-14T00:00:00Z",
  "entries": {
    "folders":  [ ... FolderEntry ... ],
    "links":    [ ... LinkEntry ... ],
    "snippets": [ ... SnippetEntry ... ],
    "clis":     [ ... CliEntry ... ],
    "macros":   [ ... MacroEntry ... ]
  }
}
```

- `schemaVersion` is an **integer**. The loader MUST refuse to open a document whose `schemaVersion` is greater than the version this build supports, and log an error to NVDA's log.
- On read, an absent top-level key MUST be treated as an empty list, not an error.

### 3.3 Common Entry Fields (every entry, all categories)

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string (UUID4) | yes | Generated on creation; immutable. |
| `name` | string | yes | Display name; non-empty after strip. |
| `tags` | array of string | yes | May be empty `[]`. Tags are case-insensitive on match, original case preserved on display. |
| `createdUtc` | string (ISO-8601 Z) | yes | |
| `modifiedUtc` | string (ISO-8601 Z) | yes | |
| `notes` | string | no | Free-form user notes. |

### 3.4 Category-Specific Fields

**FolderEntry**
```json
{ "path": "C:\\Users\\me\\Documents", "openWith": null }
```
- `path`: absolute filesystem path or UNC. Validation deferred (do not stat at load time).
- `openWith`: reserved for future use; MUST be `null` in v1.

**LinkEntry**
```json
{ "url": "https://example.com", "browser": null }
```
- `url`: must start with `http://`, `https://`, or `mailto:`. Other schemes rejected at add/edit time.
- `browser`: reserved; `null` in v1 (always uses system default).

**SnippetEntry**
```json
{ "body": "Hello {{date}}", "pasteMode": "clipboard" }
```
- `body`: arbitrary text, may contain expansion tokens (see §7).
- `pasteMode`: `"clipboard"` only in v1. Future: `"typed"`.

**CliEntry**
```json
{ "command": "ipconfig", "args": ["/all"], "shell": false, "cwd": null, "timeoutSec": 15, "speakOutput": true }
```
- `shell` **MUST default to `false`**. UI MUST warn when user enables it.
- `timeoutSec`: integer 1–120. Hard cap enforced.
- `args`: list of strings; never a single concatenated string.

**MacroEntry**
```json
{ "gestures": ["kb:control+c", "kb:alt+tab", "kb:control+v"], "interStepDelayMs": 50 }
```
- Each gesture string MUST be parseable by `keyboardHandler.KeyboardInputGesture.fromName()`.
- `interStepDelayMs`: 0–2000.

### 3.5 Forbidden Content

- The schema MUST NOT accept any field named `password`, `credential`, `secret`, `token`, or `apiKey`. The loader and validator MUST strip such fields and log a warning. This is a hard security boundary; no exceptions.

---

## 4. Atomic Persistence & Concurrency

### 4.1 Atomic Write Protocol (`storage.save_atomic`)

1. Serialize document to UTF-8 bytes with `json.dumps(..., ensure_ascii=False, indent=2, sort_keys=False)`.
2. Write to `data.json.tmp` in the same directory (must be same volume for `os.replace` atomicity).
3. `fsync` the temp file's file descriptor.
4. `os.replace("data.json.tmp", "data.json")` — atomic on Windows NTFS.
5. On any exception during steps 1–4, the temp file MUST be unlinked and the original `data.json` left untouched. The error is logged and surfaced to the user via `gui.messageBox` (queued via `wx.CallAfter`).

### 4.2 Read Protocol

- Open with `encoding="utf-8"`, `errors="strict"`.
- If file does not exist: return a fresh empty document, do NOT auto-create the file (creation happens on first save).
- If JSON parse fails: rename the corrupt file to `data.json.corrupt-<timestamp>`, return empty document, log error, notify user on next GUI cycle.

### 4.3 In-Process Locking

- A single `threading.RLock` (`storage._lock`) MUST guard every read and write.
- The lock MUST be acquired for the entire span of "load → mutate → save". Callers obtain a context manager via `with storage.mutating() as doc: ...`.

### 4.4 Cross-Process

- No multi-process locking in v1. Two concurrent NVDA instances writing to the same config dir is out of scope (NVDA itself does not support this).

---

## 5. Thread-Safety Constraints

These rules are **absolute**. The code review will reject any violation.

1. **wxPython is GUI-thread-only.** No `wx.*` call from a background thread except `wx.CallAfter` and `wx.CallLater`.
2. **NVDA `ui.message` and `speech.*` are thread-safe** (they enqueue), but for ordering certainty after background work, prefer `wx.CallAfter(ui.message, text)`.
3. **All blocking I/O runs off the GUI thread:**
   - Path existence checks (`os.path.isdir` against UNC).
   - Subprocess execution (CLI category).
   - Any DNS / network resolution.
   Use `threading.Thread(daemon=True)` or `concurrent.futures.ThreadPoolExecutor(max_workers=2)` owned by the GlobalPlugin and shut down in `terminate()`.
4. **COM (Shell.Application, UIAutomation) MUST be called from the GUI/main thread.** NVDA's main thread is STA-initialized. Background-thread COM is forbidden in v1.
5. **JSON save** is called synchronously on the GUI thread (file is small; <10 ms typical). Do NOT background it — risk of save-after-shutdown races outweighs the latency cost.
6. **Macro playback** uses `keyboardHandler.KeyboardInputGesture.fromName(...).send()` and MUST be invoked from the GUI thread (`wx.CallAfter`). Inter-step delays use `wx.CallLater`, NOT `time.sleep`.

---

## 6. User Interface Specification

### 6.1 Main Dialog (`gui.mainDialog.MainDialog`)

- **Container:** `wx.Dialog` parented to `gui.mainFrame`, modal=False (modeless so the user can switch apps for context capture).
- **Construction:** Always via `wx.CallAfter(MainDialog.show_singleton)`. The dialog is a singleton; re-invoking the hotkey raises and focuses the existing instance.
- **Layout:** `wx.Listbook` with **6 pages in this exact order**:
  1. Folders
  2. Links
  3. Snippets
  4. CLIs
  5. Macros
  6. Tags

- **Each category page (1–5) layout:**
  - Top: filter `wx.TextCtrl` (label "Filter") — narrows the ListCtrl as the user types.
  - Middle: virtual `wx.ListCtrl` with `LC_REPORT | LC_VIRTUAL | LC_SINGLE_SEL`. Columns:
    - Folders: Name, Path, Tags
    - Links: Name, URL, Tags
    - Snippets: Name, Preview (first 60 chars, single line), Tags
    - CLIs: Name, Command, Tags
    - Macros: Name, Steps (count), Tags
  - Bottom button row: **Add**, **Edit**, **Delete**, **Activate**, **Close**.
  - All buttons reachable by Tab. Tab order: filter → list → Add → Edit → Delete → Activate → Close.

- **Tags page (page 6):**
  - Left: `wx.ListBox` of unique tags (sorted, case-insensitive).
  - Right: virtual `wx.ListCtrl` of all entries (any category) matching the selected tag. Columns: Name, Category, Tags.
  - Activating an entry here behaves identically to activating it on its native page.

### 6.2 Global Accelerators inside the dialog

Implemented via a single `wx.EVT_CHAR_HOOK` handler on the dialog:

| Key | Action |
|---|---|
| `1` | Switch to Folders page |
| `2` | Switch to Links page |
| `3` | Switch to Snippets page |
| `4` | Switch to CLIs page |
| `5` | Switch to Macros page |
| `6` | Switch to Tags page |
| `Escape` | Close dialog |
| `Enter` (on a list item) | Activate the entry |
| `Applications` / `Shift+F10` (on a list item) | Open context menu |
| `Delete` (on a list item) | Trigger Delete button (with confirmation if setting enabled) |
| `F2` (on a list item) | Trigger Edit |

- The `1`–`6` shortcuts MUST be suppressed when focus is inside an editable text control (`wx.TextCtrl`, `wx.ComboBox` in editable mode). Detection via `isinstance(focus, (wx.TextCtrl, wx.ComboBox))`.

### 6.3 Context Menu (per row)

Items, in order: **Activate**, **Edit**, **Delete**, separator, **Duplicate**, **Copy name to clipboard**, **Copy value to clipboard** (path / URL / body / command), separator, **Move to tab…** (submenu, for non-tag context).

### 6.4 Add / Edit Dialogs (`gui.entryDialogs`)

- One modal `wx.Dialog` per category, all subclassing a shared `_BaseEntryDialog`.
- Built with `gui.guiHelper.BoxSizerHelper` for label association.
- All free-text fields are `wx.TextCtrl`. Tags use a single `wx.TextCtrl` with comma-separated values (parsed/trimmed on save).
- **FolderEntry dialog** has an extra button **"Capture from active window"** that invokes `contextCapture.get_active_folder_path()` (see §8) — only enabled if the setting is on.

### 6.5 Quick-Pick Overlay (`gui.quickPick.QuickPick`)

- `wx.Frame` with `wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP | wx.BORDER_SIMPLE`.
- Centered on the active monitor.
- Contents: a single `wx.TextCtrl` and a virtual `wx.ListCtrl` (columns: Name, Category, Tag preview).
- Fuzzy matching across **all categories simultaneously**, scoring by `fuzzy.score(query, entry.name) * 2 + score(query, " ".join(tags))`.
- `Enter` activates top result; `Up/Down` change selection; `Escape` closes.
- Closes automatically on lose-focus.
- Must be openable while another app (e.g., Word) has focus. After activation, focus returns to the previously focused window (capture via `wx.Window.FindFocus()` before showing, restore on close).

### 6.6 Accessibility Requirements

- Every control has a label or `SetName()` set, including the filter TextCtrl and both ListCtrls on the Tags page.
- All buttons use `&Mnemonic` (e.g., `&Add`, `&Edit`, `&Delete`).
- All user-facing strings wrapped in `_()` with a preceding `# Translators:` comment.
- The dialog and entry modals MUST NOT use `gui.message.MessageDialog` for the entry forms — `wx.Dialog` is correct. `gui.messageBox` is used for confirmations only.

---

## 7. Snippet Token Expansion (`snippets.py`)

Supported tokens, expanded left-to-right at activation time:

| Token | Expands to |
|---|---|
| `{{date}}` | Local date, ISO format `YYYY-MM-DD` |
| `{{time}}` | Local time, `HH:MM` 24-hour |
| `{{datetime}}` | `YYYY-MM-DD HH:MM` |
| `{{utc}}` | UTC ISO-8601 with `Z` suffix |
| `{{clipboard}}` | Current clipboard text (empty string if non-text) |
| `{{cursor}}` | Marker for final caret position (only one allowed; if present, set caret via `Left` arrow key presses after paste) |
| `{{nl}}` | Newline `\n` |
| `{{tab}}` | Tab `\t` |
| `{{user}}` | `os.environ["USERNAME"]` |
| `{{host}}` | `os.environ["COMPUTERNAME"]` |

- Unknown tokens are left literal and a single log warning is emitted.
- Expansion is pure and synchronous (no I/O).
- Final text is placed on clipboard via `api.copyToClip(text, notify=False)`, then NVDA announces `_("Snippet copied to clipboard")` via `ui.message`. v1 does NOT auto-paste; user pastes with Ctrl+V.

---

## 8. Context-Aware Path Capture (`contextCapture.py`)

### 8.1 Strategy (in priority order)

1. **Active File Explorer window:** Iterate `Shell.Application.Windows()` via `comtypes.client.CreateObject("Shell.Application")`. For each entry compare `HWND` to `winUser.getForegroundWindow()`. On match, return `window.Document.Folder.Self.Path`.
2. **Open/Save common dialog:** If the foreground window's class is `#32770` (standard Win32 dialog) and contains an address bar (`ToolbarWindow32` with role UIA breadcrumb), use UIA to read its value.
3. **Desktop fallback:** If foreground is the desktop (class `Progman` or `WorkerW`), return the desktop folder via `winreg`-backed `SHGetKnownFolderPath` equivalent. Simplest acceptable v1 implementation: `os.path.join(os.environ["USERPROFILE"], "Desktop")`.
4. Otherwise: return `None`. The caller surfaces `_("No folder path could be detected from the active window.")`.

### 8.2 Rules

- All COM calls on the GUI thread only.
- The capture call has a hard **500 ms wall-clock budget**; if exceeded, abort and return `None`. (Implement by running the Shell.Application enumeration synchronously but with a simple `time.monotonic()` deadline check; do NOT use a thread-based timeout.)
- Result is validated: if not a real filesystem path (e.g., `::{...}` shell namespace), return `None`.

---

## 9. CLI Execution (`cli.py`)

- Always executed in a **background daemon thread**.
- Use `subprocess.run(..., capture_output=True, text=True, timeout=entry.timeoutSec, shell=entry.shell, cwd=entry.cwd)`.
- On the GUI thread (`wx.CallAfter`), after completion:
  - If `speakOutput`: `ui.browseableMessage(stdout or stderr, title=entry.name, isHtml=False)`.
  - If not: `ui.message(_("Command {name} completed with exit code {code}").format(...))`.
- Timeout → user-facing message `_("Command timed out after {n} seconds")`.
- The Settings Panel's "shell=True" warning text MUST appear in the Add/Edit dialog adjacent to the checkbox.

---

## 10. Macros (`macros.py`)

- Replay sequence: build a list of `KeyboardInputGesture` objects up front; abort the entire macro if any gesture fails to parse (log + user message).
- Send each via `gesture.send()` on the GUI thread, scheduling subsequent steps with `wx.CallLater(interStepDelayMs, _send_next)`.
- A macro in flight MUST set a module-level "macro running" flag and refuse re-entry until done.

---

## 11. Scripts & Gestures (`__init__.py`)

```text
SCRIPT_CATEGORY = _("Favorites Hub")
```
`GlobalPlugin.scriptCategory = SCRIPT_CATEGORY`

| Script | Default gesture | Description (translatable) | Notes |
|---|---|---|---|
| `script_openHub` | `kb:NVDA+alt+f` | Opens the Favorites Hub main dialog | Layered: after press, waits up to 1500 ms for a follow-up letter. |
| `script_openQuickPick` | `kb:NVDA+alt+q` | Opens the Favorites Hub Quick-Pick overlay | |
| `script_captureFolderHere` | _(unbound)_ | Add the current folder to Favorites Hub | Uses contextCapture, opens Add Folder dialog pre-filled. |

### 11.1 Layered Gestures

After `script_openHub` is invoked, the GlobalPlugin temporarily binds (via `inputCore.manager.userGestureMap` or a transient handler) the following keys for 1500 ms:

| Key | Action |
|---|---|
| `f` | Open dialog on Folders |
| `l` | Open dialog on Links |
| `s` | Open dialog on Snippets |
| `c` | Open dialog on CLIs |
| `m` | Open dialog on Macros |
| `t` | Open dialog on Tags |

If no follow-up arrives within the window, open the dialog on the last-used tab (persisted in settings).

- None of these scripts set `speakOnDemand=True` (they open dialogs / change state).
- All are reprogrammable via NVDA's Input Gestures dialog because of the `@script` decorator with `description` and `category`.

---

## 12. Settings Panel (`settingsPanel.py`)

Registered via `gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(...)` in `GlobalPlugin.__init__`; removed in `terminate()`.

**v1 contents (exactly these, no more):**

1. Checkbox: **"Confirm before deleting an entry"** — default `True`.
2. Checkbox: **"Enable context-aware path capturing"** — default `True`. When off, the "Capture from active window" button in the Folder add/edit dialog is hidden.

Persisted via NVDA's `config` module under section `favoritesHub` with a confspec:

```
[favoritesHub]
    confirmBeforeDelete = boolean(default=True)
    contextCaptureEnabled = boolean(default=True)
    lastUsedTab = integer(default=0)
```

User content (entries, tags) is **NOT** stored in `config.conf` — it lives in `data.json` per §3.1.

---

## 13. Error Boundaries

| Layer | Behavior on exception |
|---|---|
| Storage load | Quarantine corrupt file (§4.2), return empty doc, log `log.error`, queue user-facing `gui.messageBox` via `wx.CallAfter`. |
| Storage save | Leave original intact, delete tmp, log, queue user message. **Never** corrupt user data. |
| Context capture | Catch all exceptions, log at `log.debugWarning`, return `None`. Capture failure is never user-visible as an error. |
| Subprocess | Capture `TimeoutExpired`, `FileNotFoundError`, `OSError`; report user-friendly messages. |
| Macro send | On per-step exception, abort remaining steps and notify user. |
| Quick-Pick fuzzy | Pure-function; exceptions are bugs and propagate (caught by wx event loop and logged). |
| GUI event handlers | Wrap top-level handlers in try/except that log and show a generic error message; do not crash NVDA. |

**Logging:** All log calls go through `from logHandler import log`. Use `log.info` sparingly; prefer `log.debug` / `log.debugWarning` for routine events. Never log entry contents (privacy).

---

## 14. Internationalization

- `addonHandler.initTranslation()` is called at the top of every `.py` file that uses `_()`.
- Every user-visible string is wrapped: `_("...")` with a `# Translators: ...` comment on the immediately preceding line.
- Compiled `.mo` files placed under `addon/locale/<lang>/LC_MESSAGES/nvda.mo` per the AddonTemplate convention.

---

## 15. Manifest (`buildVars.py` → `manifest.ini.tpl`)

Required fields (template variables filled by scons):

```ini
name = "favoritesHub"
summary = "Favorites Hub"
description = "Centralized hub for favorite folders, links, snippets, CLI commands, and keystroke macros — with tags, fuzzy quick-pick, and context-aware capture."
author = "<from buildVars.py>"
version = "1.0.0"
url = "<from buildVars.py>"
docFileName = "readme.md"
minimumNVDAVersion = "2026.1"
lastTestedNVDAVersion = "2026.1"
```

---

## 16. Testing & Acceptance Checklist

The implementation is considered complete only when **all** of the following are demonstrably true:

1. Add-on installs cleanly into NVDA 2026.1 and appears in the Add-on Store list.
2. `NVDA+Alt+F` opens the main dialog. `1`–`6` switch pages. `Escape` closes.
3. Add → Edit → Delete works for every category; entries persist across NVDA restart.
4. Corrupting `data.json` (manually inserting garbage) causes the file to be quarantined and the dialog to open empty without crashing NVDA.
5. Activating a Folder opens Explorer to that path. Activating a Link opens default browser. Activating a Snippet places expanded text on clipboard with `{{date}}` resolved. Activating a CLI runs and shows output. Activating a Macro sends keystrokes.
6. Context-aware capture pre-fills the path when the foreground is an Explorer window; returns gracefully when it isn't.
7. Quick-Pick (`NVDA+Alt+Q`) opens borderless, filters across all categories, activates on Enter, restores prior focus on close.
8. Tags page shows aggregate view; activating an entry there matches behavior on its native page.
9. All scripts appear under "Favorites Hub" in NVDA's Input Gestures dialog and are remappable.
10. No `wx` calls occur on background threads (verified by code review).
11. No `password`/`credential`/`secret` fields can be introduced via the GUI; loader strips them if present in a hand-edited file.
12. Settings panel checkboxes function and persist through `config.conf`.
13. NVDA log shows no `ERROR` entries during a 10-minute use session.

---

## 17. Out of Scope (v1)

- Credential / password storage (permanent — security boundary).
- Cloud sync.
- Per-link browser overrides.
- Per-folder "open with" applications.
- Typed (non-clipboard) snippet paste mode.
- Multi-process file locking.
- Cross-NVDA-instance synchronization.
- Drag-and-drop reordering.
- Import/export `.fhub` bundle (deferred to v1.1).

---

## 18. Change Control

Any change to:
- The JSON schema (§3),
- The thread-safety rules (§5),
- The security boundary (§3.5),
- Or the default gesture set (§11)

requires a version bump to `schemaVersion` (where applicable) **and** a written amendment to this brief. The implementation agent MUST NOT silently broaden any of the above.

— *End of brief.*
