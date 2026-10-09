"""Local document extraction, OCR, and tokenizer-bounded segmentation."""

from __future__ import annotations

import csv
import io
import re
import subprocess
import zipfile
import ast
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any, Literal

from PIL import Image, ImageOps
from docx import Document
from pypdf import PdfReader
from pydantic import BaseModel, Field, model_validator

from search_anything.embeddings import ContextLimitError, LocalEmbeddingModel
from search_anything.media import media_settings

MAX_DOCUMENT_BYTES = 64 * 1024 * 1024
MAX_DOCUMENT_PAGES = 2000
MAX_IMAGE_PIXELS = 24_000_000
MAX_DOCX_ENTRIES = 4096
MAX_DOCX_EXPANDED_BYTES = 100 * 1024 * 1024
SUPPORTED_DOCUMENT_SUFFIXES = {
    ".txt",
    ".md",
    ".html",
    ".htm",
    ".pdf",
    ".docx",
    ".py",
}
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
_SKIP_HTML = {"script", "style", "noscript", "nav", "footer"}


class IngestionOptions(BaseModel):
    strategy: Literal["automatic"] = "automatic"
    version: int = 1
    media_preset: Literal[
        "automatic",
        "speech_lectures",
        "general_video",
        "music_sounds",
        "camera_footage",
    ] = "automatic"
    media_window_seconds: float | None = Field(default=None, ge=1, le=300)
    media_overlap_seconds: float | None = Field(default=None, ge=0, le=29)
    video_sampling_fps: float | None = Field(default=None, ge=0.05, le=30)
    transcription_language: str | None = None
    text_chunk_tokens: int = Field(default=700, ge=64, le=4096)
    text_overlap_tokens: int = Field(default=80, ge=0, le=512)
    ocr_languages: str = Field(default="eng", min_length=1, max_length=100)
    combined_media_text: bool = False

    def resolved_media_preset(self, content_type: str) -> str:
        if self.media_preset != "automatic":
            return self.media_preset
        return (
            "general_video" if content_type.startswith("video/") else "speech_lectures"
        )

    @model_validator(mode="after")
    def check_overlap(self) -> "IngestionOptions":
        if self.text_overlap_tokens >= self.text_chunk_tokens:
            raise ValueError("text overlap must be smaller than the chunk target")
        if not re.fullmatch(r"[A-Za-z0-9_+.-]+", self.ocr_languages):
            raise ValueError("OCR language list contains unsupported characters")
        if (
            self.media_window_seconds is not None
            and self.media_overlap_seconds is not None
            and self.media_overlap_seconds >= self.media_window_seconds
        ):
            raise ValueError("media overlap must be smaller than the window")
        presets = (
            [self.media_preset]
            if self.media_preset != "automatic"
            else ["speech_lectures", "general_video"]
        )
        for preset in presets:
            media_settings(
                preset,
                self.media_window_seconds,
                self.media_overlap_seconds,
                self.video_sampling_fps,
            )
        return self


class IngestionError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TextBlock:
    text: str
    heading: str | None
    location: dict[str, Any]
    source_start: int | None = None
    source_end: int | None = None
    kind: str = "text"
    time_start: float | None = None
    time_end: float | None = None


@dataclass(frozen=True)
class TextChunk:
    text: str
    title: str | None
    heading: str | None
    location: dict[str, Any]
    source_start: int | None
    source_end: int | None
    token_count: int
    kind: str
    time_start: float | None = None
    time_end: float | None = None


@dataclass(frozen=True)
class OcrResult:
    text: str
    words: list[dict[str, Any]]
    language: str


def _markdown_blocks(text: str) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    lines = text.splitlines(keepends=True)
    headings: list[tuple[int, str]] = []
    buffer: list[str] = []
    buffer_start = 0
    buffer_kind = "text"
    cursor = 0
    table_id = 0
    code_fence: str | None = None
    in_table = False

    def flush(end: int, kind: str | None = None) -> None:
        nonlocal buffer, buffer_kind, table_id
        joined = "".join(buffer)
        leading = len(joined) - len(joined.lstrip())
        value = joined.strip()
        if value:
            start = buffer_start + leading
            actual_kind = kind or buffer_kind
            location = {"offset_unit": "unicode_codepoint"}
            if actual_kind == "table":
                location["table_id"] = table_id
                table_id += 1
            blocks.append(
                TextBlock(
                    value,
                    " / ".join(item[1] for item in headings) or None,
                    location,
                    start,
                    start + len(value),
                    actual_kind,
                )
            )
        buffer = []
        buffer_kind = "text"

    for line in lines:
        stripped = line.strip()
        heading_match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", stripped)
        fence_match = re.match(r"^(```+|~~~+)", stripped)
        is_table_line = stripped.startswith("|") and stripped.count("|") >= 2
        if code_fence:
            if not buffer:
                buffer_start = cursor
            buffer.append(line)
            if fence_match and fence_match.group(1)[0] == code_fence[0]:
                flush(cursor + len(line), "code")
                code_fence = None
            cursor += len(line)
            continue
        if fence_match:
            flush(cursor)
            code_fence = fence_match.group(1)
            buffer_start = cursor
            buffer_kind = "code"
            buffer.append(line)
        elif heading_match:
            flush(cursor)
            level = len(heading_match.group(1))
            headings = [item for item in headings if item[0] < level]
            headings.append((level, heading_match.group(2).strip()))
            blocks.append(
                TextBlock(
                    heading_match.group(2).strip(),
                    " / ".join(item[1] for item in headings),
                    {"offset_unit": "unicode_codepoint"},
                    cursor,
                    cursor + len(line),
                    "heading",
                )
            )
        elif is_table_line:
            if not in_table:
                flush(cursor)
                buffer_start = cursor
                buffer_kind = "table"
                in_table = True
            buffer.append(line)
        elif not stripped:
            flush(cursor)
            in_table = False
        else:
            if in_table:
                flush(cursor, "table")
                in_table = False
            if not buffer:
                buffer_start = cursor
                buffer_kind = "text"
            buffer.append(line)
        cursor += len(line)
    flush(cursor, "code" if code_fence else "table" if in_table else None)
    return blocks


def _python_blocks(text: str) -> list[TextBlock]:
    lines = text.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [
            TextBlock(
                text.strip(),
                "Python source (line-boundary fallback)",
                {"offset_unit": "unicode_codepoint", "parser": "line_fallback"},
                len(text) - len(text.lstrip()),
                len(text.rstrip()),
                "code",
            )
        ]
    definitions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    if not definitions:
        return [
            TextBlock(
                text.strip(),
                "Python module",
                {"offset_unit": "unicode_codepoint", "parser": "python_ast"},
                len(text) - len(text.lstrip()),
                len(text.rstrip()),
                "code",
            )
        ]
    blocks: list[TextBlock] = []
    cursor_line = 0
    for node in definitions:
        start_line = min(
            [node.lineno]
            + [decorator.lineno for decorator in getattr(node, "decorator_list", [])]
        )
        start = max(cursor_line, start_line - 1)
        end = node.end_lineno or start_line
        if start > cursor_line:
            prelude = "".join(lines[cursor_line:start]).strip()
            if prelude:
                blocks.append(
                    TextBlock(
                        prelude,
                        "Python module imports",
                        {"offset_unit": "unicode_codepoint", "parser": "python_ast"},
                        starts[cursor_line],
                        starts[start],
                        "code",
                    )
                )
        label = getattr(node, "name", "Python statement")
        code = "".join(lines[start:end]).strip()
        if code:
            blocks.append(
                TextBlock(
                    code,
                    f"Python {type(node).__name__}: {label}",
                    {
                        "offset_unit": "unicode_codepoint",
                        "parser": "python_ast",
                        "line_start": start + 1,
                        "line_end": end,
                    },
                    starts[start],
                    starts[end],
                    "code",
                )
            )
        cursor_line = end
    tail = "".join(lines[cursor_line:]).strip()
    if tail:
        blocks.append(
            TextBlock(
                tail,
                "Python module",
                {"offset_unit": "unicode_codepoint", "parser": "python_ast"},
                starts[cursor_line],
                starts[len(lines)],
                "code",
            )
        )
    return blocks


class _HTMLBlocks(HTMLParser):
    _block_tags = {
        "p",
        "li",
        "td",
        "th",
        "pre",
        "blockquote",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.current: list[str] = []
        self.blocks: list[TextBlock] = []
        self.heading: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_HTML:
            self.hidden += 1
        if tag in self._block_tags:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_HTML and self.hidden:
            self.hidden -= 1
        if tag in self._block_tags:
            text = " ".join("".join(self.current).split())
            if text:
                if tag.startswith("h") and len(tag) == 2:
                    self.heading = text
                self.blocks.append(
                    TextBlock(
                        text,
                        self.heading,
                        {"element": tag},
                        kind="heading" if tag.startswith("h") else "text",
                    )
                )
            self.current = []

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.current.append(data)

    def _flush(self) -> None:
        if self.current:
            text = " ".join("".join(self.current).split())
            if text:
                self.blocks.append(TextBlock(text, self.heading, {"element": "text"}))
        self.current = []


def _check_docx_archive(content: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > MAX_DOCX_ENTRIES:
                raise IngestionError(
                    "archive_too_large", "DOCX contains too many entries"
                )
            total = sum(item.file_size for item in members)
            if total > MAX_DOCX_EXPANDED_BYTES:
                raise IngestionError(
                    "archive_too_large", "DOCX expanded content is too large"
                )
            names = {item.filename for item in members}
            if "word/document.xml" not in names or "[Content_Types].xml" not in names:
                raise IngestionError("invalid_docx", "Invalid DOCX package")
            if any(
                item.filename.lower().endswith("vbaproject.bin")
                or "activex/" in item.filename.lower()
                for item in members
            ):
                raise IngestionError(
                    "active_content_rejected", "Macro content is not supported"
                )
    except zipfile.BadZipFile as error:
        raise IngestionError("invalid_docx", "Invalid DOCX package") from error


def _docx_blocks(content: bytes) -> list[TextBlock]:
    _check_docx_archive(content)
    document = Document(io.BytesIO(content))
    blocks: list[TextBlock] = []
    heading: str | None = None
    ordinal = 0
    table_index = 0
    for item in document.iter_inner_content():
        if hasattr(item, "rows"):
            rows = [
                " | ".join(cell.text.strip() for cell in row.cells) for row in item.rows
            ]
            value = "\n".join(row for row in rows if row.strip(" |"))
            if value:
                blocks.append(
                    TextBlock(value, heading, {"table": table_index}, kind="table")
                )
            table_index += 1
            continue
        paragraph = item
        value = paragraph.text.strip()
        if not value:
            continue
        style = paragraph.style.name if paragraph.style is not None else ""
        if style.startswith("Heading") or style == "Title":
            heading = value
            kind = "heading"
        else:
            kind = "text"
        blocks.append(TextBlock(value, heading, {"paragraph": ordinal}, kind=kind))
        ordinal += 1
    return blocks


def _pdf_blocks(content: bytes, languages: str) -> tuple[list[TextBlock], int]:
    reader = PdfReader(io.BytesIO(content), strict=False)
    if len(reader.pages) > MAX_DOCUMENT_PAGES:
        raise IngestionError("page_limit_exceeded", "PDF exceeds the page limit")
    blocks: list[TextBlock] = []
    for page_number, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        if text:
            blocks.extend(
                replace_location(block, {"page": page_number})
                for block in _markdown_blocks(text)
            )
            continue
        image_bytes = _render_pdf_page(content, page_number - 1)
        ocr = ocr_image(image_bytes, languages)
        if ocr.text.strip():
            blocks.append(
                TextBlock(
                    ocr.text,
                    None,
                    {"page": page_number, "ocr_words": ocr.words},
                    kind="ocr",
                )
            )
    return blocks, len(reader.pages)


def replace_location(block: TextBlock, extra: dict[str, Any]) -> TextBlock:
    return TextBlock(
        block.text,
        block.heading,
        {**block.location, **extra},
        block.source_start,
        block.source_end,
        block.kind,
    )


def _render_pdf_page(content: bytes, page_number: int) -> bytes:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(content)
    page = bitmap = image = None
    try:
        page = document[page_number]
        width, height = page.get_size()
        scale = min(
            2.0, 6000 / max(width, height), (MAX_IMAGE_PIXELS / (width * height)) ** 0.5
        )
        if scale < 0.1:
            raise IngestionError(
                "pdf_page_too_large", "PDF page dimensions exceed limits"
            )
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil()
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
    finally:
        if image is not None:
            image.close()
        if bitmap is not None:
            bitmap.close()
        if page is not None:
            page.close()
        document.close()


def _open_image(content: bytes) -> Image.Image:
    try:
        with Image.open(io.BytesIO(content)) as opened:
            if opened.width * opened.height > MAX_IMAGE_PIXELS:
                raise IngestionError("image_too_large", "Image exceeds the pixel limit")
            opened.load()
            return ImageOps.exif_transpose(opened).convert("RGB")
    except IngestionError:
        raise
    except Exception as error:
        raise IngestionError("invalid_image", "Image could not be decoded") from error


def ocr_image(content: bytes, languages: str = "eng") -> OcrResult:
    image = _open_image(content)
    output = io.BytesIO()
    image.save(output, format="PNG")
    image.close()
    try:
        result = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", languages, "--psm", "6", "tsv"],
            input=output.getvalue(),
            capture_output=True,
            timeout=30,
            check=True,
        )
    except FileNotFoundError as error:
        raise IngestionError("ocr_unavailable", "Tesseract is not installed") from error
    except subprocess.TimeoutExpired as error:
        raise IngestionError(
            "ocr_timeout", "Tesseract exceeded its time limit"
        ) from error
    except subprocess.CalledProcessError as error:
        raise IngestionError(
            "ocr_failed", "Tesseract could not process the image"
        ) from error
    words: list[dict[str, Any]] = []
    lines: dict[tuple[int, int, int, int], list[str]] = {}
    confidence: dict[tuple[int, int, int, int], list[float]] = {}
    boxes: dict[tuple[int, int, int, int], list[int]] = {}
    rows = csv.DictReader(
        result.stdout.decode("utf-8", "replace").splitlines(), delimiter="\t"
    )
    for row in rows:
        token = (row.get("text") or "").strip()
        try:
            conf = float(row.get("conf", "-1"))
            x, y = int(row["left"]), int(row["top"])
            width, height = int(row["width"]), int(row["height"])
            key = tuple(
                int(row[name])
                for name in ("page_num", "block_num", "par_num", "line_num")
            )
        except (TypeError, ValueError, KeyError):
            continue
        if not token or conf < 0:
            continue
        lines.setdefault(key, []).append(token)
        confidence.setdefault(key, []).append(conf)
        box = boxes.setdefault(key, [x, y, x + width, y + height])
        box[:] = [
            min(box[0], x),
            min(box[1], y),
            max(box[2], x + width),
            max(box[3], y + height),
        ]
    for key, tokens in lines.items():
        words.append(
            {
                "text": " ".join(tokens),
                "confidence": round(sum(confidence[key]) / len(confidence[key]), 2),
                "bbox": boxes[key],
                "line": key[3],
            }
        )
    return OcrResult("\n".join(item["text"] for item in words), words, languages)


def extract_document(
    filename: str,
    content_type: str,
    content: bytes,
    languages: str = "eng",
) -> tuple[list[TextBlock], Image.Image | None, int | None]:
    if not content or len(content) > MAX_DOCUMENT_BYTES:
        code = "document_too_large" if content else "empty_document"
        raise IngestionError(code, "Document is empty or exceeds the extraction limit")
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix in SUPPORTED_IMAGE_SUFFIXES or content_type.startswith("image/"):
        image = _open_image(content)
        ocr = ocr_image(content, languages)
        blocks = (
            [
                TextBlock(
                    ocr.text,
                    None,
                    {
                        "width": image.width,
                        "height": image.height,
                        "ocr_words": ocr.words,
                    },
                    kind="ocr",
                )
            ]
            if ocr.text.strip()
            else []
        )
        return blocks, image, None
    if suffix in {".txt", ".md", ".py"}:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise IngestionError(
                "invalid_text", "Text document must be UTF-8"
            ) from error
        if "\x00" in text:
            raise IngestionError(
                "invalid_text", "Text document contains a NUL character"
            )
        return (
            _python_blocks(text) if suffix == ".py" else _markdown_blocks(text),
            None,
            None,
        )
    if suffix in {".html", ".htm"}:
        try:
            parser = _HTMLBlocks()
            parser.feed(content.decode("utf-8-sig"))
            parser.close()
        except (UnicodeDecodeError, ValueError) as error:
            raise IngestionError(
                "invalid_html", "HTML document could not be decoded"
            ) from error
        parser._flush()
        return parser.blocks, None, None
    if suffix == ".pdf" or content_type == "application/pdf":
        try:
            blocks, page_count = _pdf_blocks(content, languages)
        except IngestionError:
            raise
        except Exception as error:
            raise IngestionError("invalid_pdf", "PDF could not be parsed") from error
        if not blocks:
            raise IngestionError("empty_extraction", "PDF contains no extractable text")
        return blocks, None, page_count
    if (
        suffix == ".docx"
        or content_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        try:
            blocks = _docx_blocks(content)
        except IngestionError:
            raise
        except Exception as error:
            raise IngestionError("invalid_docx", "DOCX could not be parsed") from error
        if not blocks:
            raise IngestionError(
                "empty_extraction", "DOCX contains no extractable text"
            )
        return blocks, None, None
    raise IngestionError(
        "unsupported_content_type", f"Unsupported input format: {content_type}"
    )


def _formatted_count(
    model: LocalEmbeddingModel, title: str | None, heading: str | None, body: str
) -> int:
    prefix = "\n".join(part for part in (heading, body) if part)
    return model.count_text_tokens(f"title: {title or 'none'} | text: {prefix}")


def _table_chunks(
    block: TextBlock,
    title: str | None,
    model: LocalEmbeddingModel,
    max_tokens: int,
) -> list[TextChunk] | None:
    lines = block.text.splitlines(keepends=True)
    if len(lines) < 2:
        return None
    header_count = 2 if re.fullmatch(r"\s*\|?[\s|:-]+\|?\s*\n?", lines[1]) else 1
    headers = lines[:header_count]
    data = lines[header_count:]
    groups: list[tuple[int, list[str]]] = []
    current_start = header_count
    current: list[str] = []
    for row_index, row in enumerate(data, header_count):
        candidate = "".join(headers + current + [row]).rstrip()
        try:
            fits = (
                _formatted_count(model, title, block.heading, candidate) <= max_tokens
            )
        except ContextLimitError:
            fits = False
        if fits:
            if not current:
                current_start = row_index
            current.append(row)
            continue
        if not current:
            return None
        groups.append((current_start, current))
        current_start = row_index
        current = [row]
        candidate = "".join(headers + current).rstrip()
        try:
            if _formatted_count(model, title, block.heading, candidate) > max_tokens:
                return None
        except ContextLimitError:
            return None
    if current:
        groups.append((current_start, current))
    if len(groups) <= 1:
        return None

    line_offsets = [0]
    for line in lines:
        line_offsets.append(line_offsets[-1] + len(line))
    result: list[TextChunk] = []
    for chunk_index, (start_row, rows) in enumerate(groups):
        repeated = headers
        value = "".join(repeated + rows).strip()
        if chunk_index:
            source_start = (
                block.source_start + line_offsets[start_row]
                if block.source_start is not None
                else None
            )
        else:
            source_start = block.source_start
        end_row = start_row + len(rows)
        source_end = (
            block.source_start + line_offsets[end_row]
            if block.source_start is not None
            else block.source_end
        )
        result.append(
            TextChunk(
                value,
                title,
                block.heading,
                {
                    **block.location,
                    "table_continuation": chunk_index > 0,
                    "repeated_header": chunk_index > 0,
                },
                source_start,
                source_end,
                _formatted_count(model, title, block.heading, value),
                block.kind,
                block.time_start,
                block.time_end,
            )
        )
    return result


def chunk_blocks(
    blocks: list[TextBlock],
    title: str | None,
    model: LocalEmbeddingModel,
    target_tokens: int,
    overlap_tokens: int,
) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    max_tokens = min(target_tokens, model.context_tokens)
    for block in blocks:
        if not block.text.strip():
            continue
        try:
            count = _formatted_count(model, title, block.heading, block.text)
        except ContextLimitError:
            count = model.context_tokens + 1
        if count <= max_tokens:
            chunks.append(
                TextChunk(
                    block.text,
                    title,
                    block.heading,
                    block.location,
                    block.source_start,
                    block.source_end,
                    count,
                    block.kind,
                    block.time_start,
                    block.time_end,
                )
            )
            continue
        if block.kind == "table":
            table = _table_chunks(block, title, model, max_tokens)
            if table is not None:
                chunks.extend(table)
                continue
        offsets = model.text_token_offsets(block.text)
        if not offsets:
            raise IngestionError("empty_tokens", "A non-empty block produced no tokens")
        start = 0
        while start < len(offsets):
            low, high = start + 1, len(offsets)
            best = start
            while low <= high:
                end = (low + high) // 2
                char_start = offsets[start][0]
                char_end = offsets[end - 1][1]
                candidate = block.text[char_start:char_end]
                try:
                    candidate_count = _formatted_count(
                        model, title, block.heading, candidate
                    )
                    fits = candidate_count <= max_tokens
                except ContextLimitError:
                    fits = False
                if fits:
                    best = end
                    low = end + 1
                else:
                    high = end - 1
            if best == start:
                raise ContextLimitError(
                    "heading and required special tokens exceed the chunk limit"
                )
            boundary_end = best
            if block.kind == "text":
                floor = start + max(1, int((best - start) * 0.7))
                for candidate_end in range(best, floor, -1):
                    end_offset = offsets[candidate_end - 1][1]
                    if end_offset and block.text[end_offset - 1] in ".!?;\n":
                        boundary_end = candidate_end
                        break
            elif block.kind in {"code", "table"}:
                floor = start + max(1, int((best - start) * 0.5))
                for candidate_end in range(best, floor, -1):
                    end_offset = offsets[candidate_end - 1][1]
                    if end_offset and block.text[end_offset - 1] == "\n":
                        boundary_end = candidate_end
                        break
            char_start, char_end = offsets[start][0], offsets[boundary_end - 1][1]
            raw_value = block.text[char_start:char_end]
            leading = len(raw_value) - len(raw_value.lstrip())
            trailing = len(raw_value) - len(raw_value.rstrip())
            char_start += leading
            char_end -= trailing
            value = block.text[char_start:char_end]
            if value:
                source_start = (
                    block.source_start + char_start
                    if block.source_start is not None
                    else None
                )
                source_end = (
                    block.source_start + char_end
                    if block.source_start is not None
                    else None
                )
                chunks.append(
                    TextChunk(
                        value,
                        title,
                        block.heading,
                        {**block.location, "continuation": start > 0},
                        source_start,
                        source_end if source_end is not None else block.source_end,
                        _formatted_count(model, title, block.heading, value),
                        block.kind,
                        (
                            block.time_start
                            + char_start
                            / max(1, len(block.text))
                            * (block.time_end - block.time_start)
                            if block.time_start is not None
                            and block.time_end is not None
                            else block.time_start
                        ),
                        (
                            block.time_start
                            + char_end
                            / max(1, len(block.text))
                            * (block.time_end - block.time_start)
                            if block.time_start is not None
                            and block.time_end is not None
                            else block.time_end
                        ),
                    )
                )
            if boundary_end >= len(offsets):
                break
            start = max(start + 1, boundary_end - overlap_tokens)
    return chunks
