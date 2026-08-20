# Comment Insight

Part of **Dossentra**. Ingests reviewer comments from `.docx` files, classifies
them, flags reviewer disagreements, tracks resolution decisions, and finds
patterns across documents -- built to speed up prepping for a Comment
Resolution Meeting (CRM).

## First-time setup

You need Python 3.11+ and an [Anthropic API key](https://console.anthropic.com).

```
git clone <this repo's URL>
cd CommentInsight
python -m venv .venv
```

**Windows (cmd):**
```
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

**Mac/Linux:**
```
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Then open `.env` in a text editor and paste your Anthropic API key in place of
`sk-ant-...`. Never share this file or commit it -- it's already listed in
`.gitignore`.

## Running the server

Every time you want to use the app:

```
cd CommentInsight
.venv\Scripts\activate        (Mac/Linux: source .venv/bin/activate)
python -m uvicorn app.main:app --reload
```

Then open **http://127.0.0.1:8000** in your browser. Leave the terminal window
open while you're using the app -- closing it stops the server. To stop it on
purpose, click into the terminal and press `Ctrl+C`.

If you'd rather not open a terminal every time, see **Always-on setup
(Windows)** below -- it starts the server automatically whenever you log in.

## Always-on setup (Windows)

This sets the server up to start automatically, hidden in the background,
every time you log in to Windows -- no cmd prompt needed. It runs while
you're logged in to your computer; it's not a cloud server, so it doesn't run
when your computer is off. (Hosting this somewhere that's reachable even when
your computer is off is a bigger step -- see `SECURITY.md` for why that's not
set up yet.)

One-time setup, after you've done the first-time setup above:

1. In File Explorer, go to `CommentInsight\scripts\windows`.
2. Double-click **`install_startup_task.bat`**. A window will flash up,
   confirm, and start the server right away.
3. Open **http://127.0.0.1:8000** to confirm it's running.

If step 2 says **"ERROR: Access is denied"**, Task Scheduler is locked down
on this computer -- common on managed/work machines. Double-click
**`install_startup_shortcut.bat`** instead; it does the same thing a
different way (a shortcut in your own Startup folder) that doesn't need
those permissions.

From now on, the server starts by itself whenever you log in -- just open
that same address in your browser.

**Other scripts in that folder:**
- **`stop_server.bat`** -- stops the server if it's currently running.
  Use this before an update (see below), or any time you want it off.
- **`uninstall_startup_task.bat`** / **`uninstall_startup_shortcut.bat`** --
  removes whichever auto-start method you used. Run `stop_server.bat` too
  if it's currently running.

## Getting updates

When you're told there's a new version to pick up:

```
cd CommentInsight
git pull
.venv\Scripts\activate        (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

`pip install` is safe to run every time -- it does nothing if nothing changed,
and picks up any new dependencies if something did. Your uploaded documents
and all your classification/resolution work are untouched by an update; that
data lives in `data/`, which isn't part of the repo.

If you're using the always-on setup, the running server won't pick up an
update by itself -- run `stop_server.bat`, then either double-click
`run_server.bat` or just log out and back in to let it restart itself.

## Your data

- Uploaded `.docx` files and the SQLite database live in `data/` (created
  automatically, gitignored -- never pushed anywhere).
- To back up your work, copy the whole `data/` folder somewhere safe.
- Deleting a document from the app is permanent (after a confirmation
  prompt) -- there's no undo, so back up first if you're not sure.

## What it does

- **Upload** one or more `.docx` files with Word comments on them.
- **Classify** comments by category (Editorial, Scientific/Content,
  Clarification Needed, Decision Required, Other) using AI.
- **Detect disagreements** between reviewers on the same document.
- **Track resolution status** (Accepted / Rejected / CRM) per comment, plus a
  free-text note for how it was actually handled (e.g. "edited directly in
  the document," "replied in Word").
- **Analyze across documents** -- combined charts, a per-document summary,
  and an AI-generated overview of patterns and recurring themes.
- **Export** a branded Word report (single document or cross-document) and,
  for cross-document analysis, an Excel workbook.

## Running tests

```
python -m unittest discover -s tests -p "test_*.py"
```

Tests use fake AI implementations -- running them never makes a real,
paid API call.

## Security & data handling

See `SECURITY.md` for what currently happens to your data (including what's
sent to Anthropic) and what would need to change before this could be shared
with other people.
