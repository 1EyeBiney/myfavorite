## [1.1.0] - 2026-05-14

### Operational Engines (The Active Core)
* **Context-Aware Folder Capture:** Introduced a highly optimized, COM-based path detection engine. The add-on can now instantly read the path of the currently active File Explorer window or standard Windows Open/Save dialog (enforcing a strict 500ms budget to guarantee zero screen-reader lag).
* **Background CLI Execution:** Added a daemon-threaded subprocess runner for `CliEntry` items. Users can execute terminal commands silently in the background. Short outputs are spoken directly; outputs exceeding 500 characters automatically trigger NVDA's scrollable/browseable message window.
* **Keystroke Macro Player:** Implemented a non-blocking macro engine using NVDA's native `KeyboardInputGesture` routing and `wx.CallLater` chaining, allowing for complex, multi-step system automations with precise inter-step millisecond delays.
* **Dynamic Snippet Expansion:** Added a pure-Python token expansion engine. Text snippets can now dynamically inject variables (e.g., `{{date}}`, `{{time}}`, `{{clipboard}}`) at the exact moment of activation before pushing to the system clipboard.
* **Fuzzy Search Algorithm:** Built a zero-dependency, pure-Python fuzzy matching algorithm. This 5-tier scoring engine will power the upcoming Quick-Pick overlay, prioritizing exact, prefix, and sequential character matches.

### Architecture & Stability
* Verified thread-safety across all engines: blocking I/O is strictly sandboxed to daemon threads, while all COM, clipboard, and NVDA speech interactions are correctly marshaled back to the GUI thread via `wx.CallAfter`.## [1.0.0] - 2026-05-14

### Architecture & Foundation
* **Initial Release:** Established the core `Favorites Hub` architecture, targeting strict compatibility with NVDA 2026.1 (64-bit / Python 3.13).
* **Extensible Data Schema:** Implemented a strongly-typed JSON backend supporting five initial asset categories: Folders, Web Links, Text Snippets, CLI Commands, and Keystroke Macros.
* **Bulletproof Storage:** Engineered a thread-safe storage layer (`storage.py`) utilizing atomic writes (`os.replace` and `fsync`) to guarantee `data.json` cannot be corrupted during unexpected system power loss or NVDA crashes.
* **Automated Recovery:** Added auto-quarantine functionality. If a user manually breaks the JSON formatting, the add-on safely renames the corrupt file and loads a fresh slate rather than crashing the screen reader.

### Security
* **Credential Firewall:** Implemented a strict schema security boundary that actively detects and strips sensitive fields (e.g., "password", "secret", "apiKey") if they are manually injected into the configuration file.

### Under the Hood
* Built the `GlobalPlugin` stub with graceful GUI degradation, allowing the add-on to load and register safely during development.
* Registered foundational Input Gestures (`NVDA+Alt+F` for the main Hub, `NVDA+Alt+Q` for the Quick-Pick overlay) to the NVDA routing engine.
