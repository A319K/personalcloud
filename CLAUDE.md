# personalcloud — Developer Guide

## Project Status

- **Phase 1 (CLI + FastAPI backend) — COMPLETE.** Tagged `v1.0-cli`.
- **Phase 2 (Mac Menu Bar App) — COMPLETE.** Tagged `v2.0-menubar`.

---

## Phase 1 Architecture

```
personalcloud/
├── cli/main.py           — Typer CLI (init, sync, watch, search, status, ls)
├── api/
│   ├── main.py           — FastAPI app with lifespan, mounts all routers
│   ├── routes/
│   │   ├── files.py      — GET /files, GET /files/{id}, DELETE /files/{id}
│   │   ├── search.py     — GET /search/?q=...&top_k=5
│   │   └── status.py     — GET /status, POST /watcher/start, POST /watcher/stop
│   └── services/
│       ├── storage.py    — R2 / MinIO abstraction via boto3
│       ├── embeddings.py — all-MiniLM-L6-v2 embedding + pgvector cosine search
│       ├── ocr.py        — Text extraction (PDF, DOCX, XLSX, images, text)
│       └── watcher.py    — Watchdog file system event handler
├── db/
│   ├── models.py         — SyncedFile, FileEmbedding ORM models
│   └── database.py       — Engine, session, init_db (creates pgvector extension)
└── config/settings.py    — .env-backed Settings singleton
```

**Start the API server:**
```bash
source .venv/bin/activate
uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

---

## Phase 2 Architecture — Native Mac Menu Bar App

### Tech Stack
- **Language:** Swift 5.9 / SwiftUI
- **macOS target:** 13.0+
- **Xcode:** 15.0+
- **No external Swift dependencies** — uses only system frameworks

### Project Location
```
personalcloud/
└── menubar/
    ├── personalcloud.xcodeproj/   — Xcode project
    ├── Sources/
    │   ├── App.swift              — @main entry point, MenuBarExtra, AppDelegate
    │   ├── MenuBarView.swift      — Dropdown menu (status, watcher, actions)
    │   ├── SearchWindow.swift     — NSPanel controller + vibrancy background
    │   ├── SearchView.swift       — Search bar + results list
    │   ├── PreviewView.swift      — Hover-triggered file preview panel
    │   ├── SettingsView.swift     — Hotkey, watch folder, backend URL, login
    │   ├── APIClient.swift        — Async/await HTTP client for FastAPI
    │   └── Models.swift           — Swift structs + AppState ObservableObject
    ├── Assets.xcassets/
    │   └── AppIcon.appiconset/
    └── Info.plist                 — LSUIElement=true (no Dock icon)
```

### How It Works

1. `App.swift` defines `PersonalCloudApp` (`@main`) with two scenes:
   - `MenuBarExtra` — the cloud icon dropdown (native menu style)
   - `Settings` — preferences window
2. `AppDelegate` (via `@NSApplicationDelegateAdaptor`) manages:
   - Global hotkey via `NSEvent.addGlobalMonitorForEvents` (needs Accessibility)
   - `SearchWindowController` — the floating NSPanel
3. `AppState` is a `@MainActor ObservableObject` shared via `environmentObject`:
   - 30-second status polling timer
   - 300ms debounced search
   - 500ms hover-to-preview
4. `APIClient.shared` is a singleton that calls the Phase 1 FastAPI backend.

### API Contract (Phase 2 endpoints added to Phase 1)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/status` | SyncStatus JSON (files, storage, watcher state) |
| GET | `/files/{id}` | FileDetail JSON (metadata + text preview) |
| POST | `/watcher/start` | Start background watchdog thread |
| POST | `/watcher/stop` | Stop background watchdog thread |
| GET | `/search/?q=...` | SearchResult array (extended with `id`, `extension`) |

### Running Phase 2

1. **Start Phase 1 backend first:**
   ```bash
   cd personalcloud
   source .venv/bin/activate
   uvicorn api.main:app --host 127.0.0.1 --port 8000
   ```

2. **Open in Xcode:**
   ```
   open menubar/personalcloud.xcodeproj
   ```

3. **Build and run:** `Cmd+R`

4. **First launch:** macOS will prompt for Accessibility permission for the global hotkey (Cmd+Shift+F). Grant it in System Settings → Privacy & Security → Accessibility.

### UserDefaults Keys

| Key | Type | Default | Purpose |
|-----|------|---------|---------|
| `backendURL` | String | `http://localhost:8000` | FastAPI base URL |
| `watchFolder` | String | (empty) | Watch folder path shown in Settings |
| `hotkeyCode` | Int | `3` (F key) | Key code for global hotkey |
| `hotkeyModifiers` | Int | Cmd+Shift | Modifier flags for global hotkey |
| `launchAtLogin` | Bool | false | SMAppService launch-at-login |

---

## Configuration

### EXCLUDE_PATHS

Set `EXCLUDE_PATHS` in `.env` as a comma-separated list of directory names to skip during sync and live watching. Any file whose path contains one of these segments is silently ignored — not uploaded, not embedded, not indexed.

```env
EXCLUDE_PATHS=node_modules,.venv,venv,__pycache__,.git,dist,build,.next,.egg-info
```

**Default value** (used when `EXCLUDE_PATHS` is not set):
```
node_modules, .venv, venv, __pycache__, .git, dist, build, .next, .egg-info
```

The exclusion logic also permanently skips files whose names match known noise patterns regardless of directory:
- `LICENSE`, `LICENSE.md`, `LICENSE.txt`, `LICENSE-MIT`, `LICENSE-APACHE`
- `NOTICE`, `NOTICE.txt`
- `CHANGELOG`, `CHANGELOG.md`, `CHANGELOG.txt`, `CHANGES`
- `CopyrightNotice.txt`
- `*.LICENSE.txt` (e.g. `react.LICENSE.txt`)

The check is implemented in `api/services/watcher.py:is_excluded()` and is called by both the `sync` command and the live watcher before any file is processed.

### `personalcloud clean`

Removes already-indexed junk from the database without touching files on disk or in storage.

```bash
personalcloud clean --confirm
```

- Requires `--confirm` to prevent accidental runs.
- Iterates all indexed records and removes any whose paths contain an `EXCLUDE_PATHS` segment or whose filenames match the junk patterns above.
- Prints: `Removed X file(s) from index`.
- Does **not** delete files from disk or from the R2/MinIO bucket.

---

## Coding Standards

- Every function must have a descriptive docstring
- Use type hints on all Python function signatures; doc comments on all Swift functions
- Handle all exceptions gracefully — never crash with raw tracebacks
- No placeholder functions — every function is fully implemented

## Commit Style

Conventional commits: `feat:`, `fix:`, `docs:`, `chore:`

## Environment Config (`.env`)

```env
STORAGE_BACKEND=r2              # "r2" or "minio"
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=
DATABASE_URL=postgresql://...
WATCH_FOLDER=~/Documents
API_HOST=127.0.0.1
API_PORT=8000
```
