"""Makes `tests` a package so `python -m unittest discover -s tests` imports
this before any individual test module -- needed to set a test-only
SESSION_SECRET_KEY before any test file does `from app.main import app`,
since app/main.py refuses to start without one (see SECURITY.md)."""

import os

os.environ.setdefault("SESSION_SECRET_KEY", "test-secret-key-not-for-production")
# bcrypt's minimum cost factor -- the suite creates test accounts on every
# setUp, and their passwords don't need production-grade hashing cost.
os.environ.setdefault("BCRYPT_ROUNDS", "4")
