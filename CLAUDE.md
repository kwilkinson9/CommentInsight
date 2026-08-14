# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Comment Insight is a small FastAPI app that ingests Word (`.docx`) documents, extracts reviewer comments (author, anchored text, surrounding paragraph, section heading, reply-thread links) with a dependency-free parser, stores them in SQLite, and exposes them through both a JSON API and a server-rendered HTML dashboard.

## Commands

Set up a virtualenv and install dependencies (no lockfile, just `requirements.txt`):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Run the app locally:

```bash
uvicorn app.main:app --reload
```

Run all tests (`unittest`, not pytest — there's no pytest dependency):

```bash
python3 -m unittest discover -s tests -v
```

Run a single test module / class / test:

```bash
python3 -m unittest tests.test_docx_parser -v
python3 -m unittest tests.test_docx_parser.FragmentedRunsTests -v
python3 -m unittest tests.test_dashboard.DashboardTests.test_search_filters_comments -v
```

`tests/test_docx_parser.py` only needs the standard library and will run even without `requirements.txt` installed; `tests/test_documents_api.py` and `tests/test_dashboard.py` need `fastapi`/`httpx` (via `TestClient`).

Run the parser as a standalone CLI (useful for debugging extraction against a real file without going through the app/DB):

```bash
python3 -m app.ingestion.docx_parser path/to/file.docx
```

There is no linter or formatter configured in this repo.

## Architecture

Request flow: `app/routers/*.py` (HTTP layer) → `app/storage.py` (persistence + orchestration) → `app/ingestion/docx_parser.py` (pure extraction) → `app/database.py` (SQLite connection/schema).

- **`app/ingestion/docx_parser.py`** — The core extraction logic, and the most intricate part of the codebase. A `.docx` is a zip of XML parts; this module reads three of them directly with `xml.etree.ElementTree` (no python-docx or similar): `word/document.xml` for comment anchors and paragraph/section context, `word/comments.xml` for comment text/author/date, and `word/commentsExtended.xml` for reply-thread parent links. It has **zero third-party dependencies by design** — keep it that way so `extract_comments()` stays independently testable and runnable as a CLI. Reply threads are linked by matching each comment's Word-native `paraId` (from `commentsExtended.xml`) to the owning comment's own `paraId` (from `comments.xml`) — comment ids themselves are never the thread key. Section headings are tracked as a "trail" keyed by heading level while walking the document in order, so a comment's `section` is a breadcrumb like `"5.3 Summary of Clinical Safety Findings > 5.3.3 Laboratory Findings"`. Only Word's default built-in heading style ids (`Heading1`-`Heading5`) are recognized; documents using custom heading styles won't populate `section`. Anchor and paragraph text must be reassembled across run boundaries — real Word documents frequently split a single sentence across many `<w:r>` runs (formatting changes, spell-check, autosave), so a comment range can start in one run and end in another; `tests/test_docx_parser.py`'s `FragmentedRunsTests` exists specifically to guard this.

- **`app/storage.py`** — Bridges parsing and the database. `ingest_uploaded_file()` is the single shared entry point used by *both* the JSON API (`routers/documents.py`) and the HTML upload form (`routers/dashboard.py`), so extraction/storage behavior can't drift between the two. It validates the extension, writes the raw upload to `data/uploads/{document_id}_{filename}` unmodified (extraction always re-reads from disk, nothing is derived from a mutated copy), then extracts and persists comments. `save_comments()` does parent-link resolution in two passes: comments are inserted first to get database row ids, then a second pass resolves `parent_comment_id` — because `Comment.parent_id` from the parser is a docx-native id that's only unique *within a single document*, not a database id.

- **`app/database.py`** — Raw `sqlite3` (no ORM). `get_connection()` creates the DB file/parent dirs on demand and applies `SCHEMA` (two tables: `documents`, `comments`) via `executescript`, so schema changes just mean editing the `SCHEMA` string — there are no migrations. `get_db()` is a FastAPI dependency (yields a connection, closes it after the request); tests override this dependency via `app.dependency_overrides[get_db]` to point at a temp DB file instead of the real one (see any test's `setUp`).

- **Two parallel HTTP surfaces over the same storage layer**:
  - `app/routers/documents.py` — JSON API under `/api/documents` (upload, list, get, list comments).
  - `app/routers/dashboard.py` — server-rendered HTML under `/` and `/documents/{id}`, using Jinja2 templates from `app/templates/` (`base.html`, `index.html`, `document.html`). Supports `?q=` free-text search (matches comment/anchor/paragraph text) and `?author=` filtering, both implemented in `storage.list_comments()`.

- **Data directory**: `data/` (uploaded files under `data/uploads/`, SQLite DB at `data/comment_insight.db`) is created at runtime and git-ignored — never assume it pre-exists.

- **Sample fixtures**: `tests/sample_docs/*.docx` are real `.docx` files used as parser/API/dashboard test fixtures (a full synthetic sample with 9 comments and a reply thread, a fragmented-runs edge case, and a no-comments case). When testing changes to the parser, prefer running against these before writing new ones.
