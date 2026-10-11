"""Checks that experimental ranking preserves baseline behavior and isolation."""

import importlib
from uuid import uuid4

import pytest

from search_anything import retrieval


@pytest.fixture
def experiment(monkeypatch):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("experiment_retrieval")


def candidate(kind="audio", similarity=0.7, text=None, asset_id=None):
    return retrieval.Candidate(
        asset_id=asset_id or uuid4(),
        filename="opaque.wav",
        content_type="audio/wav",
        representation_id=uuid4(),
        generation_id=uuid4(),
        kind=kind,
        text=text,
        location={},
        source_start=None,
        source_end=None,
        time_start=0,
        time_end=10,
        similarity=similarity,
    )


def test_baseline_replay_and_patch_cleanup(experiment):
    a = candidate()
    b = candidate(similarity=0.5)
    channels = {"audio": [a, b]}
    serialized = {k: [experiment.plain(c) for c in v] for k, v in channels.items()}
    snapshot = {"reverse": {str(a.asset_id): "a", str(b.asset_id): "b"}}
    query = {"channels": serialized, "extended_channels": serialized}
    score = retrieval._channel_score
    assert experiment.rank(snapshot, query, "baseline", {}) == ["a", "b"]
    experiment.rank(snapshot, query, "rank_only", {})
    assert retrieval._channel_score is score
    assert a.score == 0


def test_confidence_gate_handles_missing_and_bad_segments(experiment):
    c = candidate("transcript", text="The lecture describes the orbit of the moon.")
    assert experiment.confidence_quality(c, []) == 1
    segment = dict(
        start=0, end=10, no_speech_prob=0.9, avg_logprob=-0.1, compression_ratio=1
    )
    assert experiment.confidence_quality(c, [segment]) == 0.1
    assert experiment.confidence_quality(c, [dict(segment, start=20, end=25)]) == 1
    assert experiment.text_quality("hello world again " * 5) == 0.1


def test_bm25_retrieves_partial_query_terms_without_gold(experiment):
    a = candidate("transcript", text="The spaceship launched in 1969.")
    b = candidate("transcript", text="A lecture about ancient pottery.")
    reps = [
        dict(key=key, candidate=experiment.plain(c)) for key, c in [("a", a), ("b", b)]
    ]
    hits = experiment.lexical({}, reps, "When was the spaceship launched?", {"a", "b"})
    assert hits[0].asset_id == a.asset_id
    assert experiment.lexical({}, reps, "spaceship", {"b"}) == []


def test_crops_have_fixed_bounded_geometry(experiment):
    crops = experiment.boxes(100, 80)
    assert len(crops) == 4
    for x0, y0, x1, y1 in crops:
        assert 0 <= x0 < x1 <= 100
        assert 0 <= y0 < y1 <= 80
        assert x1 - x0 == 70
        assert y1 - y0 == 56


def test_sentence_parts_retain_neighboring_context_and_bound_length(experiment):
    parts = experiment.sentence_parts(
        "First statement. Second statement. Third statement."
    )
    assert "First statement. Second statement." in parts
    long = experiment.sentence_parts(" ".join(f"word{i}" for i in range(200)))
    assert all(len(p.split()) <= 80 for p in long)
    assert "word199" in long[-1]


def test_bootstrap_is_paired_and_reproducible(experiment):
    assert experiment.paired_interval([0, 0, 0]) == [0, 0]
    assert experiment.paired_interval([0.2] * 30) == pytest.approx([0.2, 0.2])
    assert experiment.paired_interval([0.1, -0.2, 0.3]) == experiment.paired_interval(
        [0.1, -0.2, 0.3]
    )


def test_ocr_quality_uses_confidence_and_keeps_missing_neutral(experiment):
    c = candidate("ocr", text="Sale 42")
    assert experiment.ocr_quality(c) == 1
    c.location = {
        "ocr_words": [
            {"text": "Sale", "confidence": 70},
            {"text": "42", "confidence": 70},
        ]
    }
    assert experiment.ocr_quality(c) == pytest.approx(0.49)
    c.location = {"ocr_words": [{"text": "Sale", "confidence": "invalid"}]}
    assert experiment.ocr_quality(c) == 1


def test_confidence_does_not_mix_audio_window_contexts(experiment):
    c = candidate("transcript", text="A clear sentence about the moon.")
    c.location = {"window_start": 0}
    segment = dict(
        start=0,
        end=10,
        window_start=5,
        no_speech_prob=0.9,
        avg_logprob=-2,
        compression_ratio=3,
    )
    assert experiment.confidence_quality(c, [segment]) == 1
    segment["window_start"] = 0
    assert experiment.confidence_quality(c, [segment]) == 0.1


def test_cluster_bootstrap_keeps_contrast_pairs_together(experiment):
    # Each pair's positive and negative changes cancel. Query resampling would
    # invent uncertainty by separating these dependent observations.
    changes = [0.5, -0.5, 0.2, -0.2]
    assert experiment.paired_interval(changes, groups=["a", "a", "b", "b"]) == [0, 0]
    assert experiment.paired_interval(changes)[0] < 0


@pytest.mark.asyncio
async def test_capture_refuses_to_overwrite_frozen_snapshot(experiment, tmp_path):
    snapshot = tmp_path / "collection-snapshot.json"
    snapshot.write_text("frozen")
    with pytest.raises(RuntimeError, match="fresh --output"):
        await experiment.capture(tmp_path)
    assert snapshot.read_text() == "frozen"


def test_sentence_passages_keep_only_overlapping_asr_segment_bounds(experiment):
    members = []
    for i, text in enumerate(
        ["First statement.", "Second statement.", "Third statement."]
    ):
        c = candidate("transcript", text=text)
        c.time_start, c.time_end = i * 2, (i + 1) * 2
        members.append({"candidate": experiment.plain(c)})
    passages = experiment.sentence_passages(members)
    assert passages[0] == ("First statement.", 0, 2)
    assert passages[1] == ("First statement. Second statement.", 0, 4)
    assert passages[2] == ("Second statement. Third statement.", 2, 6)
