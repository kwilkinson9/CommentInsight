# Security & Data Handling

This document tracks what Comment Insight currently does with data, and what
still needs to happen before real sponsor data flows through it. It's a
running checklist, not a finished policy — update it as decisions get made.

## Why this matters

Comment Insight is meant to handle confidential documents (clinical study
reports, regulatory submissions, and similar) for medical writers. That's a
different bar than a personal side project: the documents themselves, and the
comments on them, can be commercially or medically sensitive.

## Now built: accounts and per-user isolation

As of the multi-tester pilot, the app requires a login and every document
belongs to exactly one account:

- **Authentication.** Email + password, bcrypt-hashed, session cookies
  signed with `SESSION_SECRET_KEY`. Accounts are admin-created
  (`scripts/create_user.py`) — no open self-signup, so the tester list stays
  a known, small group.
- **Per-user data isolation.** Every document (and everything derived from
  it — comments, classifications, resolutions, conflicts, cross-document
  insights) is scoped to the account that uploaded it. Every route that
  takes a document_id or comment_id verifies ownership before touching the
  database; a mismatched owner returns 404, indistinguishable from the
  document not existing at all, so a guessed ID can't be used to probe what
  exists under another account. This includes the case where a request
  names *your own* document but a comment_id belonging to someone else's —
  tested explicitly, see `tests/test_auth.py`.
- **Filesystem isolation.** Uploaded files are also split into per-user
  subdirectories on disk, on top of the database-level filtering.
- **Login hardening.** Repeated failed logins against one email are rate
  limited (in-memory — resets on restart, doesn't coordinate across
  multiple worker processes; fine for a single-process pilot, a real
  scaling need would want a shared store like Redis instead). The session
  cookie is `SameSite=Lax`; `SESSION_COOKIE_SECURE=true` marks it
  HTTPS-only once actually deployed behind TLS. Basic security headers
  (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, HSTS when
  the secure-cookie flag is on) are set on every response.
- **Migration safety.** A database from before accounts existed doesn't
  lose its documents — they're folded into one freshly-created account on
  first startup, with generated credentials printed once. See
  `app/database.py`'s `_migrate_to_multi_user`.

None of this is provisioned or hosted anywhere yet — it's the application
code, ready to run wherever it's deployed. See "Still outstanding" below for
what deploying it for real still needs.

## Now built: optional local scrubbing before AI calls

Classification, conflict detection, and cross-document insights each have
an opt-in "Scrub likely patient identifiers first" checkbox. When checked:

- `app/deidentify.py` scans the specific text about to be sent to Claude
  (comment text, and the anchored document text/paragraph context where
  applicable — never the reviewer's own name, which is professional
  metadata the app needs, not patient data) for emails, phone numbers,
  SSNs, specific dates, explicitly-labeled identifiers ("MRN:", "DOB:"),
  and names/places via a small local NLP model (spaCy's `en_core_web_sm`).
  This runs **entirely on the machine running the app — no network call,
  no external service** — since the point is to avoid sending raw
  identifying text anywhere external in the first place.
- If anything is found, the writer sees exactly what, on a review screen,
  and has to explicitly confirm before the redacted version is actually
  sent. Nothing sends silently.
- If nothing is found, it proceeds normally — no extra friction for
  documents that don't need it.

**This is a mitigation, not a guarantee.** Pattern-matching and a small
local model will both miss things a person would catch (an unusual name,
an indirectly identifying combination of details) and can occasionally
over-flag things that aren't actually identifying. It's meant to sit
alongside a human confirmation step and good judgment about what gets
uploaded in the first place — not to be the reason real, unredacted
patient data is considered safe to test with. See
`tests/test_deidentify.py` and `tests/test_redaction.py` for what's
actually verified to work.

## Current state: AI calls and secrets

- **AI calls (Anthropic API).** Classification, conflict detection, and
  cross-document insights send comment text plus limited surrounding
  context (the anchored phrase, the paragraph it appears in, and — for
  insights — which document/section it came from) to Anthropic's API. Under
  Anthropic's standard commercial API terms:
  - This data is **never used to train Anthropic's models**.
  - It's retained for a short window (currently around 7 days) for abuse
    monitoring, then automatically deleted.
  - This is *not* Zero Data Retention — see "Still outstanding" below.
- **Secrets.** The Anthropic API key and the session-signing key both live
  only in a local `.env` file (gitignored, never committed). Neither is
  ever typed into chat or committed to source control. If either is ever
  exposed, rotate it immediately (API key at console.anthropic.com;
  session key by generating a new one and restarting the app, which logs
  everyone out).

## Still outstanding — before real sponsor data is involved

These are mostly business/infrastructure steps, not application code:

1. **Zero Data Retention (ZDR) agreement with Anthropic.**
   Standard API terms (no training, ~7-day retention) may not be strong
   enough for confidential sponsor documents. ZDR means Anthropic does not
   store prompts/responses at rest at all after the response is returned.
   Requires contacting Anthropic's sales team, enabled per organization on
   the account making the API calls — not configurable from application
   code: https://claude.com/contact-sales
   **This is the one to start soonest — it has the longest lead time and
   the current pilot round is deliberately using only synthetic/de-identified
   test documents while it's in progress.**

2. **Actual hosting, with TLS.** The app is ready to run behind HTTPS
   (`SESSION_COOKIE_SECURE=true` enforces it for the session cookie), but
   provisioning the server, domain, and certificate is a separate,
   infrastructure-level task outside this repo.

3. **Encryption at rest.** Uploaded documents and the SQLite database still
   have no encryption of their own. In practice this is usually a hosting
   platform setting (e.g. an encrypted disk/volume) rather than something
   the application needs to implement itself — worth confirming explicitly
   with whatever host is chosen, rather than assuming it's on by default.

4. **Data Processing Agreements (DPAs) with sponsors/customers.**
   Once real confidential documents flow through this app, whoever operates
   it becomes a data processor for the sponsor. That's a legal/contractual
   relationship, not a technical one, but it depends on the technical
   answers above (where data is stored, who can access it, how long it's
   kept).

5. **Password reset.** There's currently no self-service way to reset a
   forgotten password — re-running `scripts/create_user.py` for the same
   email just reports it already exists. Fine for a small, admin-managed
   pilot; would need a real flow (email-based reset token) before wider use.

6. **Rate limiting beyond login.** Only failed logins are currently rate
   limited. If this is ever opened beyond a small known group, the upload
   and AI-triggering endpoints would want limits too, both for cost control
   (AI calls aren't free) and abuse resistance.

## Reporting a concern

This is a personal project in active development, not a published product
yet. If you're reading this as a collaborator and spot a security issue,
raise it directly rather than filing a public issue.
