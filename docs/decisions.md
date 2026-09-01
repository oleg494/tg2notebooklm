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
sorted candidate ordering, `reportlab ... invariant=1`, stable filename digests,
`newline="\n"` output, no timestamps in artifacts. Verified: `diff -r` of two
independent real-exports conversions (39,672-record JSON) exits 0.

**Evidence:** consumer Gemini Notebook treats local uploads as static copies; there
is no update-in-place. Diffable outputs let users replace only changed sources on
re-export.

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
