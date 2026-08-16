# Security & Data Handling

This document tracks what Comment Insight currently does with data, and what
still needs to happen before this is offered to other medical writers as a
product. It's a running checklist, not a finished policy — update it as
decisions get made.

## Why this matters

Comment Insight is meant to handle confidential documents (clinical study
reports, regulatory submissions, and similar) for medical writers. That's a
different bar than a personal side project: the documents themselves, and the
comments on them, can be commercially or medically sensitive.

## Current state (personal/single-user use)

- **AI calls (Anthropic API).** Classification and conflict detection send
  comment text plus limited surrounding context (the anchored phrase and the
  paragraph it appears in — not the whole document) to Anthropic's API.
  Under Anthropic's standard commercial API terms:
  - This data is **never used to train Anthropic's models**.
  - It's retained for a short window (currently around 7 days) for abuse
    monitoring, then automatically deleted.
  - This is *not* Zero Data Retention — see "Before commercializing" below.
- **Local storage.** Uploaded `.docx` files and the SQLite database
  (`app/data/`) are stored unencrypted on whatever machine runs the server.
  For local personal use this is fine — it's your machine. It is not
  currently suitable for storing other people's confidential documents.
- **Secrets.** The Anthropic API key lives only in a local `.env` file
  (gitignored, never committed). It is never typed into chat or committed to
  source control. If a key is ever exposed, revoke and rotate it immediately
  at console.anthropic.com.
- **Architecture.** Single-user, single-tenant. One API key, one local
  database. There is no concept of separate customer accounts or data
  isolation between users yet.

## Before commercializing (offering this to other medical writers)

These are business and architecture steps, not code changes I can make
unilaterally — flagging them here so they don't get lost.

1. **Zero Data Retention (ZDR) agreement with Anthropic.**
   Standard API terms (no training, ~7-day retention) may not be strong
   enough to market to medical writers handling confidential documents. ZDR
   means Anthropic does not store prompts/responses at rest at all after the
   response is returned. This requires contacting Anthropic's sales team and
   is enabled per organization, on the Anthropic account making the API
   calls. Not configurable from application code — do this when ready to
   commercialize: https://claude.com/contact-sales

2. **Multi-tenant data isolation.**
   If multiple customers use a hosted version of this app, their documents
   need to be kept separate — both in storage and in whatever gets sent to
   Anthropic. Right now there's no per-customer boundary at all.

3. **Encryption at rest for local/hosted storage.**
   Uploaded documents and the database need real protection wherever they're
   stored — this is separate from and not covered by Anthropic's ZDR, which
   only covers the API call itself, not what happens to files before or
   after.

4. **Data Processing Agreements (DPAs) with customers.**
   Once other people's confidential documents flow through this app, you
   become a data processor for them. That's a legal/contractual
   relationship, not a technical one, but it depends on the technical
   answers above (where data is stored, who can access it, how long it's
   kept).

5. **Access controls / authentication.**
   The app currently has no login system — anyone with network access to the
   server can use it. Needed before any hosted, multi-user deployment.

## Reporting a concern

This is a personal project in active development, not a published product
yet. If you're reading this as a collaborator and spot a security issue,
raise it directly rather than filing a public issue.
