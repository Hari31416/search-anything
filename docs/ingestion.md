# Ingestion and indexing

The durable worker owns extraction and the pinned local EmbeddingGemma model.
Each generation snapshots its chunk target, overlap, and OCR language options.
Text input is checked with the model's actual processor with truncation disabled;
an input over 8,192 processed tokens is split at structural or sentence
boundaries, or fails with an explicit context error if even its required heading
context cannot fit.

The first supported formats are UTF-8 `.txt` and `.md`, `.html`/`.htm`, `.pdf`,
`.docx`, `.py`, and PNG/JPEG/WebP/TIFF images. PDF pages retain page numbers;
scanned pages fall back to local Tesseract OCR. DOCX paragraphs and tables keep
document order. Python source is segmented at top-level functions and classes
using the AST parser, with a line-preserving fallback for invalid source.
Markdown headings and fenced code are retained as context; tables stay intact
when they fit and repeat column headers when split into multiple segments.
Oversized single table rows and code lines use token-safe bounded splitting.

Images create a visual representation and a separate OCR text representation.
OCR text retains per-line bounding boxes and confidence values. Document text
segments retain page, heading, table, or source-offset metadata. Each textual
representation and image representation gets its own finite, normalized 768d
vector. A GIN index over `to_tsvector('simple', text_content)` supplies lexical
indexing for text and OCR; hybrid retrieval is part of phase 3.

The current HTTP upload path still defaults to the single `automatic` profile.
Profile management, retry/cancel/reprocess endpoints, presets, and complete
audio/video extraction with Whisper are not yet available. These are phase 2
work; unsupported audio/video formats fail explicitly instead of being marked
searchable.
