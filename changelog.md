## [1.2.0] - 2026-05-14

### Graphical User Interface (The Hub)
* **Unified Listbook Interface:** Introduced the main modeless `FavoritesHubDialog`. Navigable via native first-letter routing across six dedicated views: Folders, Links, Snippets, CLIs, Macros, and a unified Tags dashboard.
* **Global Hub Navigation:** Added global `1` through `6` numeric accelerators to instantly jump between category pages from anywhere within the dialog, bypassing standard tab-traversal delays.
* **Quick-Pick Overlay:** Introduced a borderless, floating fuzzy-search dialog (`NVDA+Alt+Q`). It automatically centers on the active monitor, filters across all asset categories simultaneously, and seamlessly restores previous window focus upon closure.
* **Contextual Data Management:** Implemented dedicated Add/Edit modal dialogs for each asset type, complete with rigorous input validation (e.g., URL scheme verification, CLI timeout clamping, and fail-fast gesture parsing for macros).
* **Smart Tags View:** Added a split-pane Tags dashboard, allowing users to cross-reference workflows (e.g., viewing a local folder, a web link, and a text template simultaneously under a single project tag).
* **Native Context Menus:** Integrated standard Win32 context menus (`Applications` key or `Shift+F10`) on all list items, featuring actions to Activate, Edit, Delete, Duplicate, and Copy values directly to the clipboard.
* **Configuration Panel:** Registered a native NVDA Settings Panel under Preferences, allowing users to toggle delete-confirmation prompts and context-aware path capturing.## [1.1.0] - 2026-05-14

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
