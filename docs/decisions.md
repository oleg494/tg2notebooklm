# Project decisions and known limitations

Decision log for tg2notebooklm. Each entry names the decision, the evidence, and the
rejected alternatives. Dates are 2026-09-01 unless noted.

## D1 — Greenfield MIT project instead of forking

**Decision:** build from scratch; reuse ideas (not code) from existing tools.

**Evidence:** survey of maintained repos — TeleLore (JSON→MD only, browser worker),
tg-parser (JSON only, LLM-oriented), telegram-markdown-converter (HTML only, 3 stars,
1 open issue), tg2obsidian (per-message files, unmaintained 2y), chat-miner (drops
everything except timestamp/author/message). None cover: both export formats,
source-budget packing, image atlases, attachment audit. License conflicts avoided
(GPL projects excluded).

**Rejected:** forking TeleLore (Next.js browser app forces browser-only processing,
no media pipeline); forking tg-parser (Python but JSON-only, DDD layering overhead
for a CLI tool).

## D2 — Markdown for chat text, PDF atlases for images, native files for the rest

**Decision:** three content lanes. Chat corpus → chronological Markdown chunks under
400k target words (500k hard Google ceiling). Images → captioned multi-image PDF
pages (Unicode font embedded via Pillow's bundled DejaVu). Documents/audio/video →
copied originals in leftover slots, documents prioritized over music.

**Evidence:** Google support (answer/16215270, 16269187, 16213268): 500k words / 200
MB per source; 50/100/300/500/600 sources per plan tier; audio transcribed on import;
image types listed separately ("certain types of images may not work as well").
Bundling many images per PDF page beats individual image uploads: 330 images cost 3
slots instead of 330. Whole-document citation failure for too-short sources argues
for fewer, larger, well-anchored sources (H2/H3 headers + msg IDs) over per-day
micro-chunks.

**Rejected:** per-message or per-day files (citations break, slots exhausted);
single monolithic file (one source = one retrieval unit, poor precision); pure
text-only conversion (user requirement: maximum information, including visual).

## D3 — Strict source budget: 1 index + 1 attachment catalog + adaptive text + media

**Decision:** `_fit_text_chunks` binary-searches the words-per-chunk size between
target and hard ceiling so chat text fits the slots minus two reserved (index +
`01_attachments.csv` CSV catalog). Remaining slots: image atlases (160 images each,
auto-halving on the 200 MB ceiling), then native files by priority (documents →
texts → voice/audio → other media, largest first within category). Overflow is
recorded per-attachment as `excluded_source_budget`, never silently dropped.

**Evidence:** user hard requirement — "ноутбук поддерживает максимум 300 источников,
все фотки с чата не получится загрузить". A queryable CSV of every attachment
decision spends one slot but makes the loss itself analyzable inside the notebook.

**Rejected:** best-effort packing without a catalog (violates auditability);
reserving no slots and failing at the end (bad UX after minutes of work).

## D4 — Determinism as a hard contract

**Decision:** identical input + flags → byte-identical package. Achieved via:
sorted candidate ordering, the pure-Pillow PDF atlas writer with `_pin_pdf_dates`
pinning Creation/ModDate to a constant, stable filename digests, `newline="\n"`
output, no timestamps in artifacts. Verified: `diff -r` of two consecutive full
rebuilds of the real-exports JSON conversion (39,672 records, 2026-09-01) exits 0.

**Evidence:** consumer Gemini Notebook treats local uploads as static copies; there
is no update-in-place. Diffable outputs let users replace only changed sources on
re-export. Known tradeoff: Pillow's PDF encoder rasterizes captions into the page
image, so atlas captions are not text-selectable/searchable in the PDF — fine for
Gemini Notebook's visual ingestion and citation via caption content, but not
machine-selectable text.

## D5 — Local-only processing; enrichment optional

**Decision:** zero network requests in the core. Optional extras: faster-whisper
transcription (`[transcribe]` extra) and tesseract OCR (external binary), both with
`--enrichment-max-files` caps; results are inlined at the message position.

**Evidence:** Telegram exports are private by definition; shipping a converter that
phones home would be unacceptable for a public GitHub tool. Whisper model loading is
local-only (faster-whisper loads from disk/HF cache; no data leaves the machine).

## D6 — Placeholder media is preserved as metadata, never fabricated

**Decision:** Telegram's own "(File not included. Change data exporting settings to
download.)" and "(File exceeds maximum size…)" placeholders become `unavailable`
attachment records with full declared metadata (name, mime, size, dimensions,
duration). Real JSON sample: 3,951 of 5,042 records are placeholders (3,046 photos
were never exported as files at all).

**Evidence:** direct observation of both test exports; assuming a path exists
because a field is present is the classic naive-parser bug (scout findings: 16 edge
cases listed, including 10 null authors, 823 dangling reply targets, 2 distinct
placeholder strings).

## D7 — Browser edition architecture

**Decision:** a static GitHub Pages site runs the same converter with Pyodide
314.0.6 inside a module Web Worker. The user-selected export is mounted read-only
via WORKERFS — zero-copy, nothing is uploaded. The converter ships as the same
PyPI wheel, installed via `micropip.install(..., deps=False)`; beautifulsoup4 and
Pillow come from the Pyodide package repo. The result is zipped in-Python with
fixed `ZipInfo` timestamps, preserving the byte-identical rerun contract (D4).
reportlab was removed so the pure-Pillow PDF atlas writer runs identically on
CPython and wasm.

**Evidence:** Pillow and beautifulsoup4 are published in the Pyodide package repo,
so only the pinned tg2notebooklm wheel is fetched from the Pages origin — no
unpinned transitive wheels from PyPI at runtime. WORKERFS wraps the browser `File`
handles directly, so a multi-gigabyte export is never copied into JS memory.

**Rejected:** running Pyodide on the page's main thread (the tab freezes during
conversion); resolving the full dependency closure through micropip (network
fetches, non-reproducible).

## D8 — Document packing roadmap (evidence-based, researched 2026-09-01)

**Decision:** Gemini Notebook natively ingests docx/pptx/epub/pdf/csv/md/txt
([support.google.com/gemininotebook/answer/16215270](https://support.google.com/gemininotebook/answer/16215270)),
so re-converting such documents while native slots remain is wasted fidelity.
Accepted roadmap:

1. **Pack small born-digital PDFs** into merged native PDFs, one generated cover
   page per original (pypdf, pure-Python). Provenance is preserved at the citation
   landing point; N documents cost 1 slot.
2. **Optional `[docs]` extra via markitdown** (MIT, pure-Python:
   pdfminer.six + pdfplumber + mammoth — no ML runtime, no network) converting
   small DOCX/PPTX/EPUB/HTML/CSV to Markdown, packed into `docs_*.md` with
   `# doc-NN: <original name>` boundary headers plus a manifest mapping.
3. **Scan gate:** PDFs without a text layer route to native upload, never to
   conversion (markitdown's PDF path is text-layer only).

**Rejected:** docling (PyTorch + ~358 MB of first-run model downloads — breaks the
no-network privacy claim, D5); marker (OpenRAIL-M weights + an external inference
server); pandoc-wasm in core (GPL-2.0+ license, 58.6 MB, no PDF input; acceptable
only in a future standalone sibling tool).

**Merge-vs-provenance rule:** merging is safe only with in-source boundary headers
naming the original document; individually citable artifacts (contracts, reports)
stay single-slot.

## D9 — Performance within Python (2026-09-02)

**Decision:** stay in Python; measured hotspots were fixed in place. A Rust/Go
rewrite was rejected: the browser edition runs this same code in Pyodide (D7),
and a compiled rewrite would orphan it or double the maintenance surface.

Profile on the real 39,672-message export, before → after:

- `code_fence_for` per-char loop (9.0 s) → regex `` `+ `` scan: 6.7× faster,
  equivalence proven on all 37k real texts.
- `count_words` via `re.findall(r"\S+")` (3.9 s) → `len(text.split())`
  (3.4× faster; whitespace semantics identical for `str.split`).
- `_fit_text_chunks` re-counts every block on each binary-search iteration →
  word/byte counts precomputed once per `TextBlock`.
- Windows `Path.resolve()` storm in `collect_candidates` (~2.3 s) → per-run
  resolve cache; `file_digest` recomputed up to 3× per file → `digest_of` cache.

End-to-end: 28.6 s → 13.4 s (2.1×). Output verified byte-identical to the
pre-optimization build (D4 holds; chunk boundaries unchanged).

**Parallelism rule (future):** any worker must be pure (input candidate →
output result); all mutation, ordinal assignment, and assembly stay serial in
the existing sorted order, gated by the two-run byte-diff test. PIL releases
the GIL, so a ThreadPool for image normalization is the only sanctioned form;
skip it under Pyodide (`sys.platform == "emscripten"`, no crossOriginIsolated
on GitHub Pages).

## D10 — Universal file-dump mode (shipped 2026-09-02)

**Decision:** `convert`/`inspect` now accept any non-empty folder of files in
addition to Telegram exports. A parser (`parsers/file_dump.py`) wraps the
folder in a synthetic `Chat(input_format="file_dump", kind="folder_dump")`
with one metadata-only `Message` per file (id `file-NNNNNN`, deterministic
casefolded-path order, 20k file cap); every existing packing lane applies
unchanged: small text files inline into Markdown chunks, images go to PDF
atlases, born-digital PDFs merge via pypdf, DOCX/PPTX convert via `[docs]`,
the rest copy natively.

Detection order in `detect.py`: `result.json` → JSON export;
`messages.html` → HTML export; any other folder containing at least one file
→ file dump. Wording in chunk headers, corpus header, index, and query hints
is format-driven (no "Telegram" claims for dumps). Cap rationale: a dump is a
manual selection, not an export; beyond ~20k files the source budget excludes
most of it anyway.

Web edition: `normalizeExport` falls back to `kind: "file_dump"` when neither
export marker is present; the worker's `parse_export` picks the same path.

**Not built (YAGNI):** per-subfolder chats, mtime-based ordering, glob
filters. None requested; the source budget dominates at this scale.

## Known limitations

1. **Unexportable media is unrecoverable** — if Telegram Desktop did not download
   the photo/video/sticker, no converter can. Re-export with media enabled.
2. **Stickers (.tgs/.webp animations) and videos stay metadata-only** when absent
   from the export; GIFs are packed as first-frame atlas images when present.
3. **HEIC/HEIF images in atlases** depend on Pillow build (may lack libheif);
   failures are recorded as `metadata_only` with reason, not crashes.
4. **Consumer upload is manual** — Google offers no official consumer API; the
   `sources/` folder is the contract for both manual upload and the Enterprise API.
5. **`inspect` word estimates are lower bounds** — actual chunk counts depend on
   Markdown metadata overhead; `convert` enforces exact limits and fails loudly
   rather than exceeding them.
6. **Single notebook scope** — Gemini Notebook cannot query across notebooks; for
   huge multi-chat account exports, split by chat across notebooks (converter
   already keys chunk filenames by chat slug).
