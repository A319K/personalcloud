# personalcloud

A self-hosted, AI-powered personal cloud backup and search CLI tool for Mac/Linux. Syncs your files to Cloudflare R2 or a local MinIO instance and enables natural language semantic search across all your documents — running entirely locally with no OpenAI API key needed.

## Demo

```
$ personalcloud search "quarterly budget projections"

Searching: quarterly budget projections

1. Q3_Budget_Final.xlsx   91.4% match
   /Users/aiden/Documents/Finance/Q3_Budget_Final.xlsx
   Revenue projections for Q3 show a 14% increase over prior year. OPEX targets
   remain flat at $2.1M. Headcount budget approved for 3 new hires in engineering…

2. board_meeting_notes.docx   78.2% match
   /Users/aiden/Documents/Meetings/board_meeting_notes.docx
   CFO presented updated financial outlook. Budget revision approved pending
   review of Q4 projections. Next review scheduled for November 12th…

3. annual_plan.md   61.7% match
   /Users/aiden/Documents/annual_plan.md
   Financial goals for the year: reduce burn by 20%, hit $5M ARR by Q3,
   maintain 18-month runway based on current projections…
```

---

## Prerequisites

- **Python 3.11+**
- **Docker & Docker Compose** — only required if using MinIO (local storage)
- **Tesseract OCR**
  - macOS: `brew install tesseract`
  - Linux: `sudo apt install tesseract-ocr`
- A **Neon** account for the managed PostgreSQL database with pgvector: [console.neon.tech](https://console.neon.tech)

---

## Quickstart

### 1. Clone the repo

```bash
git clone https://github.com/A319K/personalcloud.git
cd personalcloud
```

### 2. Copy the example env file

```bash
cp .env.example .env
```

### 3. Install the CLI

```bash
pip install --upgrade setuptools
pip install -e .
```

### 4. Run the setup wizard

```bash
personalcloud init
```

This wizard will ask you:
- **R2 or MinIO?** — Choose your storage backend and enter credentials
- **Watch folder** — Which folder to sync (default: `~/Documents`)
- **Neon DATABASE_URL** — Your Neon connection string (get it from [console.neon.tech](https://console.neon.tech))

It then creates all database tables automatically.

### 5. Start MinIO (if using local storage)

```bash
docker compose up -d
```

### 6. Sync your files

```bash
personalcloud sync
```

---

## All Commands

| Command | Description |
|---|---|
| `personalcloud init` | Interactive setup wizard — configure storage, watch folder, and database |
| `personalcloud sync` | Manually sync all files in the watch folder to storage + generate embeddings |
| `personalcloud watch` | Start a live file watcher that auto-syncs on any file change |
| `personalcloud search "query"` | Natural language semantic search across all synced files |
| `personalcloud status` | Show sync statistics: total files, storage used, backend info |
| `personalcloud ls` | List all synced files with paths and sizes |

### Search options

```bash
personalcloud search "meeting notes from last quarter" --top 10
```

- `--top` / `-n` — number of results (default: 5, max: 50)

---

## Supported File Types

| Extension | Extraction Method |
|---|---|
| `.pdf` | PyMuPDF (text layer) → Tesseract OCR fallback |
| `.docx` | python-docx |
| `.xlsx` | openpyxl |
| `.txt`, `.md`, `.csv` | Direct UTF-8 read |
| `.png`, `.jpg`, `.jpeg` | Tesseract OCR |

---

## R2 vs MinIO — Which Should I Use?

### Cloudflare R2 (recommended for most users)
- Files are stored durably in Cloudflare's global network
- No local disk space required
- No Docker needed
- Free tier: 10 GB storage, 1M Class A ops/month
- Best for: syncing important files you want backed up off-device

**Setup:** Create an R2 bucket in the [Cloudflare Dashboard](https://dash.cloudflare.com/), generate an API token with R2 permissions, and enter the credentials during `personalcloud init`.

### MinIO (local storage)
- Runs on your own machine via Docker
- Files stay entirely local — nothing leaves your network
- No internet required after setup
- Best for: privacy-first setups, air-gapped environments, or testing

**Setup:** Run `docker compose up -d` before your first sync. MinIO console is available at `http://localhost:9001` (credentials: `minioadmin` / `minioadmin`).

---

## Architecture

```
personalcloud/
├── cli/main.py           — Typer CLI commands
├── api/
│   ├── main.py           — FastAPI app (for programmatic access)
│   ├── routes/           — REST endpoints (files, search)
│   └── services/
│       ├── storage.py    — R2 / MinIO abstraction via boto3
│       ├── embeddings.py — sentence-transformers embedding + pgvector search
│       ├── ocr.py        — Text extraction (PyMuPDF, Tesseract, docx, xlsx)
│       └── watcher.py    — Watchdog-based live folder monitoring
├── db/
│   ├── models.py         — SQLAlchemy ORM (SyncedFile, FileEmbedding)
│   └── database.py       — Engine, session, init_db
└── config/settings.py    — .env-backed settings singleton
```

**Embedding model:** [`all-MiniLM-L6-v2`](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) — 384-dimensional, fast, runs entirely locally.

**Vector database:** Neon PostgreSQL with the `pgvector` extension. Cosine similarity search via the `<=>` operator.

---

## Configuration Reference (`.env`)

```env
STORAGE_BACKEND=r2              # "r2" or "minio"

# Cloudflare R2
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=

# MinIO
MINIO_ENDPOINT=http://localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET_NAME=personalcloud

# Database (Neon)
DATABASE_URL=postgresql://user:pass@host/db?sslmode=require

# General
WATCH_FOLDER=~/Documents
SUPPORTED_EXTENSIONS=.pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.xlsx,.csv

# API
API_HOST=127.0.0.1
API_PORT=8000
```

---

## Coming Soon

### Phase 2 — Mac Menu Bar App
A native macOS menu bar companion that shows sync status, triggers manual syncs, and lets you search from anywhere on your desktop — no terminal required.

### Phase 3 — Web UI + Mobile
A web dashboard for browsing and searching your files from any browser, plus a mobile app (iOS/Android) for on-the-go access to your personal cloud.

---

## Contributing

Issues and PRs welcome. This is an open-source project — please open an issue before starting large changes.

## License

MIT
