# tg2notebooklm implementation plan

**Goal:** Ship a tested Python CLI that converts Telegram Desktop JSON or HTML exports into deterministic, source-budgeted Gemini Notebook files.

**Architecture:** JSON and HTML adapters normalize to one message model. Rendering and media packing operate only on that model. Audit artifacts explain every inclusion, exclusion, missing file, and safety rejection.

**Tech stack:** Python 3.11+, Beautiful Soup, Pillow, pytest, standard-library CLI and JSON.

**Spec:** `docs/design.md`

## Tasks

1. Define normalized message, attachment, chat, package-config, and manifest records; test serialization and safe path resolution.
2. Implement JSON parsing for single-chat and account exports; test mixed rich text, replies, forwards, reactions, polls, service events, and missing-media placeholders.
3. Implement paginated HTML parsing; test joined authors, page boundaries, replies, forwards, reactions, local media links, and placeholders.
4. Implement Markdown rendering and word-boundary packing; test metadata preservation, oversized message continuation, deterministic filenames, and source limits.
5. Implement text-attachment extraction, native-file classification, PDF image atlases, source budgeting, and audit manifest; test traversal rejection and budget decisions.
6. Implement `inspect` and `convert` CLI commands; run end-to-end fixtures.
7. Smoke-convert both supplied private exports, validate limits and determinism without inspecting or publishing private content.
8. Add GitHub-facing README, license, examples, and CI; run tests, build, CLI smoke, and security checks.
