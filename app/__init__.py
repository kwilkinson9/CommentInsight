from pathlib import Path

from dotenv import load_dotenv

# Explicit path (not the default stack-frame guessing) so this works the same
# regardless of how the app is launched. encoding="utf-8-sig" strips a BOM if
# Notepad (or another editor) added one when saving .env -- with plain "utf-8"
# a BOM silently prevents the first variable in the file from being read at
# all, with no error, which is easy to mistake for a missing/wrong API key.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", encoding="utf-8-sig")
