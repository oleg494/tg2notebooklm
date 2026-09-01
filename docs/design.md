# tg2notebooklm design

## Objective

Convert Telegram Desktop's JSON and paginated HTML chat exports into a deterministic folder that can be uploaded to Gemini Notebook (formerly NotebookLM) while preserving as much analyzable information as the configured source limit permits.

## Evidence driving the design

As of 2026-09-01, Google's official limits are 500,000 words and 200 MB per uploaded source. Source limits are 50/100/300/500/600 per notebook depending on plan. Local audio is transcribed on import; supported images can be uploaded directly. A notebook cannot query another notebook.

The supplied private corpus contains both Telegram formats. The JSON sample has 39,672 records, including service messages, replies, forwards, reactions, polls, rich-text entities, and 5,042 media references. Most absent media is explicitly represented by Telegram placeholders rather than broken paths. The HTML sample spans 100 linked pages and uses default, joined-author, service, reply, forward, reaction, bot-button, and media-placeholder DOM variants.

Existing tools cover only parts of the problem: TeleLore and tg-parser handle JSON; separate HTML converters are brittle or omit media; no maintained project combines both inputs with source-budgeted multimodal packing. The implementation is therefore greenfield MIT code, with external projects used only as compatibility references.

## Architecture

1. **Input adapters** parse either `result.json` or `messages*.html` one page at a time.
2. **Normalized model** represents messages, service events, reply/forward links, reactions, polls, and attachments without format-specific assumptions.
3. **Safe enrichment** resolves attachment references only inside the export root. Small text-like attachments are decoded and inserted at the original message. Missing, unsafe, truncated, or unsupported files remain visible in the manifest.
4. **Markdown renderer** emits chronological message blocks with stable Telegram IDs and date headers, giving Gemini Notebook useful retrieval and citation anchors.
5. **Source packer** splits only at semantic boundaries and stays below a conservative configurable word target, never above Google's 500,000-word ceiling.
6. **Image atlases** place many photos into captioned PDF pages, preserving pixels and message context while consuming few source slots.
7. **Native source budget** uses remaining slots for complex documents and speech-bearing audio/video files. Everything not selected is recorded with a reason.
8. **Output contract** separates `sources/` (upload every file in this directory) from `manifest.json` and `report.md` (local audit artifacts).

## Security and privacy

- Processing is local and performs no network requests.
- Export paths are untrusted. Canonical paths must remain below the export root; traversal and escaping symlinks are rejected.
- Text extraction has configurable byte ceilings to prevent memory exhaustion.
- HTML is parsed as data and never executed.
- Existing output is replaced only through an explicit `--force` option.

## Determinism

Given identical input bytes and options, source filenames, ordering, Markdown, manifest records, and image selection are stable. This makes reruns diffable and allows users to replace changed sources manually.

## Non-goals

- Automating the consumer Gemini Notebook browser with session cookies.
- Uploading through an unofficial consumer API.
- Downloading media omitted by Telegram Desktop.
- Inventing transcripts or image descriptions when no local enrichment engine is available.

## Acceptance criteria

- Auto-detect and convert both supplied exports.
- Preserve all parsed text and structural metadata; never silently drop unavailable content.
- Emit no more than the configured number of files in `sources/`.
- Keep generated text sources under the configured target and hard Google ceiling.
- Reject attachment path traversal.
- Produce identical output on repeated runs with the same inputs and options.
- Pass unit tests and smoke conversion of both supplied exports.
