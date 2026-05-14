## [1.0.0] - 2026-05-14

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
