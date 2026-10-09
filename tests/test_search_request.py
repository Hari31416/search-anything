import pytest
from pydantic import ValidationError

from search_anything.api import SearchRequest


def test_search_limits_require_candidate_oversampling() -> None:
    with pytest.raises(ValidationError, match="candidate_limit must be at least limit"):
        SearchRequest(query="identifier", limit=25, candidate_limit=20)


@pytest.mark.parametrize(
    "weights",
    [
        {"unknown": 1},
        {"text": -1},
        {"text": float("inf")},
        {
            channel: 0
            for channel in (
                "text",
                "transcript",
                "ocr",
                "image",
                "audio",
                "video",
                "combined",
                "lexical",
                "identifier",
                "filename",
            )
        },
    ],
)
def test_search_weights_are_known_finite_and_enabled(weights) -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="local", weights=weights)


def test_search_weights_accept_enabled_channels() -> None:
    request = SearchRequest(query="local", weights={"lexical": 2, "video": 0})
    assert request.weights == {"lexical": 2, "video": 0}


def test_partial_zero_weight_leaves_default_channels_enabled() -> None:
    request = SearchRequest(query="local", weights={"audio": 0})
    assert request.weights == {"audio": 0}


def test_similarity_cutoffs_are_limited_to_dense_channels() -> None:
    request = SearchRequest(query="local", similarity_cutoffs={"video": 0.2})
    assert request.similarity_cutoffs == {"video": 0.2}
    with pytest.raises(ValidationError, match="dense representation"):
        SearchRequest(query="local", similarity_cutoffs={"lexical": 0.2})


@pytest.mark.parametrize("mode", ["separate", "combined", "both"])
def test_representation_mode_is_explicit(mode: str) -> None:
    request = SearchRequest(query="local", representation_mode=mode)
    assert request.representation_mode == mode


def test_representation_mode_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="local", representation_mode="all")
