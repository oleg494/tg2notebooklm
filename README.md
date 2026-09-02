# tg2notebooklm

**[→ Open the web edition (no install)](https://oleg494.github.io/tg2notebooklm/)** · [Документация на русском](README.ru.md)

Convert Telegram Desktop chat exports into a compact, deterministic set of
[Gemini Notebook](https://notebooklm.google.com/) (formerly NotebookLM) sources — locally, with no uploads, and with a strict source budget.

Telegram's own export gives you either a 28 MB `result.json` or a hundred paginated
HTML files. Gemini Notebook accepts neither well: it has per-notebook source limits
(50/100/300/500/600 depending on plan), a 500,000-word and 200 MB ceiling per source,
and no way to bulk-import thousands of chat photos. This tool reshapes **both** export
formats into a folder you can drag-and-drop in one go.

## What it does

- **Auto-detects** both Telegram Desktop export formats: machine-readable JSON
  (`result.json`, single chat or full account export) and paginated HTML
  (`messages.html`, `messages2.html`, …).
- **Preserves structure**: Telegram message IDs, timestamps, authors, replies
  (including cross-chat and dangling targets), forwards with original sender and date,
  edits, reactions with counts and recent reactors, polls, service events, forum topics,
  bot buttons, and rich-text entities (bold/italic/code/pre/blockquote/spoilers/links).
- **Packs chat text** into chronological Markdown sources, split only at message
  boundaries, under your word target and never above 500k words.
- **Packs images** into captioned PDF atlases (many photos per source slot, each with
  chat name, message ID, date, author, and caption text for citation and retrieval).
- **Spends leftover slots** on native sources: documents (PDF/DOCX/PPTX/EPUB) first,
  then large texts, then audio/video (Gemini Notebook transcribes audio on import).
- **Inlines small text attachments** (code, configs, CSV, notes, HTML) directly at the
  message position, so they are analyzable without spending a source slot.
- **Records every decision**: `manifest.json` + `report.md` + an in-package
  `01_attachments.csv` explain each attachment — included, inlined, atlas-packed,
  unavailable (Telegram's own "File not included" placeholders), or excluded because
  the budget was full. Nothing disappears silently.
- **Deterministic**: identical input and flags produce byte-identical outputs, so you
  can re-run, diff, and replace updated sources manually.
- **Local & private**: no network requests; OCR and audio transcription are optional
  local extras.
- **Runs in the browser**: a static GitHub Pages edition (Python via Pyodide in a
  Web Worker) converts the same exports with no upload — see
  [Browser edition](#browser-edition-github-pages).

## Install

```bash
pip install tg2notebooklm        # or: uv tool install tg2notebooklm
```

Or from source (Python 3.11+):

```bash
git clone https://github.com/oleg494/tg2notebooklm
cd tg2notebooklm
uv sync
```

## Quick start

1. In Telegram Desktop: chat → ⋮ → *Export chat history* → pick **Machine-readable
   JSON** (with photos/files) or **HTML**.
2. Inspect what you have (no content is printed):

   ```bash
   tg2notebooklm inspect path/to/ChatExport_2026-09-01 --plan standard
   ```

3. Convert:

   ```bash
   tg2notebooklm convert path/to/ChatExport_2026-09-01 \
     --output my-notebook-package \
     --plan standard
   ```

4. Open [notebooklm.google.com](https://notebooklm.google.com/), create a notebook,
   and upload **every file inside `my-notebook-package/sources/`**.
   Keep `manifest.json` and `report.md` locally (they are not source slots).

### Any folder of files (no Telegram needed)

Point `convert` at an ordinary folder — documents, notes, code, media — and it
becomes the same source-budgeted package: small text files are inlined into
Markdown chunks, images go to PDF atlases, born-digital PDFs get merged, and
everything else is copied natively:

```bash
tg2notebooklm convert path/to/my-folder --plan standard
```

Detection is automatic: folders with `result.json`/`messages.html` are parsed
as Telegram exports; any other non-empty folder becomes a file dump.

### Plans and budgets

| Flag | Sources per notebook |
|---|---|
| `--plan standard` (default) | 50 |
| `--plan plus` | 100 |
| `--plan pro` | 300 |
| `--plan ultra20` / `--plan ultra30` | 500 / 600 |

Override with `--source-limit N` for any custom budget. The converter reserves one
slot for the index and one for the attachment catalog, then fits chat Markdown,
image atlases, and native files into what remains — never exceeding the limit.
Official limits: [Google support](https://support.google.com/gemininotebook/answer/16213268).

## Browser edition (GitHub Pages)

The same converter runs fully local in your browser as a static page: Python
executes in a Web Worker via [Pyodide](https://pyodide.org/) (fetched from a CDN on
first use, then browser-cached), and your export folder is mounted read-only
(WORKERFS) — nothing is uploaded anywhere. The output is a deterministic ZIP with
the same layout as the CLI: `sources/` + `manifest.json` + `report.md`.

Prefer the CLI when:

- the export is multi-gigabyte — a browser tab holds far less in memory than a
  script;
- you want the optional local extras: OCR (Tesseract) or Whisper transcription;
- you want automation (scripts, CI, batch runs).

**Deploying your own:** on push to `main`, `.github/workflows/pages.yml` builds the
wheel and the static site (`_site/`) and publishes it via GitHub Pages Actions.
Enable this once in repo settings: *Settings* → *Pages* → *Source: GitHub Actions*.

## How the source budget is spent

1. `00_index.md` — package index, chat overview, query hints.
2. `chat_*.md` — chronological message corpus (with inlined small text attachments).
3. `01_attachments.csv` — every attachment decision, queryable as a source.
4. `images_*.pdf` — image atlases (default 160 images per PDF, 8 per page).
5. `native_*` — copied original files: documents first, then large texts,
   then audio/video by size.

Anything that doesn't fit is listed in the manifest with the reason
(`excluded_source_budget`, `unavailable`, `metadata_only`, …).

## Optional local enrichment

```bash
# Speech-to-text for voice messages / audio (needs: pip install tg2notebooklm[transcribe])
tg2notebooklm convert EXPORT --output OUT --plan pro --transcribe-audio --whisper-model small

# OCR for photos (needs the tesseract executable on PATH)
tg2notebooklm convert EXPORT --output OUT --plan pro --ocr-images --ocr-languages eng+rus

# Cap enrichment work on huge exports
--enrichment-max-files 50
```

Transcripts land inline at the original message position.

## Privacy

- The converter makes **no network requests** (whisper models are loaded locally).
- Export paths are treated as untrusted: traversal and absolute paths are rejected.
- Generated sources contain real chat content and participant names — review before
  uploading or publishing anything.

## Development

```bash
uv sync --extra dev
uv run pytest
```

Architecture and the evidence behind every design decision:
[`docs/design.md`](docs/design.md).

## Limitations

- Media that Telegram itself did not export (placeholders like "File not included.
  Change data exporting settings to download.") cannot be recovered; the converter
  records them as `unavailable` with metadata intact.
- Stickers/animations/videos omitted from the export stay metadata-only.
- Consumer Gemini Notebook has no official upload API; automation is out of scope
  (Enterprise users can feed the same `sources/` folder through the official API).

## License

MIT — see [LICENSE](LICENSE). Made by [@oleg494](https://github.com/oleg494).
