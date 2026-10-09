from search_anything.api import _source_response_type


def test_active_document_sources_are_downloads() -> None:
    for content_type in (
        "text/html",
        "text/html; charset=utf-8",
        "image/svg+xml",
        "application/xhtml+xml",
        "application/xml",
        "text/javascript",
    ):
        assert _source_response_type(content_type) == ("application/octet-stream", True)


def test_passive_media_keeps_its_inline_type() -> None:
    for content_type in ("text/plain", "application/pdf", "image/png", "video/mp4"):
        assert _source_response_type(content_type) == (content_type, False)
