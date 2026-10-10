"""Checks for regression benchmark selection and scoring."""

import runpy
from pathlib import Path

import pytest


@pytest.fixture
def benchmark(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    return runpy.run_path(str(scripts / "benchmark_search.py"))


def test_metrics_count_all_relevant_and_deduplicate(benchmark):
    score = benchmark["metrics"](["wrong", "a", "a", "b"], ["a", "b", "missing"])
    assert score["recall@5"] == pytest.approx(2 / 3)
    assert score["mrr@10"] == 0.5
    assert 0 < score["ndcg@10"] < 1


def test_metrics_penalize_relevant_below_cutoff(benchmark):
    score = benchmark["metrics"]([str(i) for i in range(10)] + ["a"], ["a"])
    assert score["recall@10"] == 0
    assert score["mrr@10"] == 0


def test_candidate_selection_preserves_all_positives(benchmark):
    import random
    from prepare_search_benchmark import select_candidates

    queries = [dict(text="red bicycle", relevant=["positive", "second"])]
    descriptions = dict(
        positive="bike", second="cycle", near="red bicycle", other="cat"
    )
    selected = select_candidates(descriptions, queries, 3, random.Random(7))
    assert set(selected) == {"positive", "second", "near"}
    with pytest.raises(ValueError):
        select_candidates(descriptions, queries, 1, random.Random(7))


def test_download_budget_rejects_overflow(tmp_path, benchmark):
    from prepare_search_benchmark import Budget

    (tmp_path / "existing").write_bytes(b"1234")
    budget = Budget(tmp_path, 10)
    budget.consume(6)
    with pytest.raises(RuntimeError, match="storage cap"):
        budget.consume(1)


def test_query_splits_do_not_share_relevant_assets(tmp_path, benchmark):
    from prepare_search_benchmark import digest, save_json, verify

    (tmp_path / "a.txt").write_text("example")
    save_json(
        tmp_path / "manifest.json",
        dict(
            assets=[
                dict(id="a", path="a.txt", bytes=7, sha256=digest(tmp_path / "a.txt"))
            ],
            queries=[
                dict(id="dev", relevant=["a"], split="dev"),
                dict(id="test", relevant=["a"], split="test"),
            ],
        ),
    )
    with pytest.raises(AssertionError, match="both query splits"):
        verify(tmp_path)


def test_speech_selection_preserves_positives_and_separates_paragraphs(benchmark):
    from prepare_spoken_squad_benchmark import paragraph, select_queries

    rows, qrels = [], []
    for group in range(20):
        for i in range(5):
            identifier = f"q-{group}-{i}"
            rows.append(dict(id=identifier, text=f"Question {identifier}"))
            for sentence in (0, 1):
                qrels.append(
                    {
                        "query-id": identifier,
                        "corpus-id": f"audio_0_{group}_{sentence}",
                        "score": 1,
                    }
                )
    selected = select_queries(rows, qrels)
    assert selected == select_queries(rows, qrels)
    assert len(selected) == 50
    assert all(len(q["relevant"]) == 2 for q in selected)
    origins = {
        split: {
            paragraph(key)
            for q in selected
            if q["split"] == split
            for key in q["relevant"]
        }
        for split in ("dev", "test")
    }
    assert not origins["dev"] & origins["test"]
    assert sum(q["split"] == "dev" for q in selected) == 30


def test_speech_selection_rejects_query_spanning_paragraphs(benchmark):
    from prepare_spoken_squad_benchmark import select_queries

    with pytest.raises(ValueError, match="spans paragraphs"):
        select_queries(
            [dict(id="q", text="Question")],
            [
                {"query-id": "q", "corpus-id": key, "score": 1}
                for key in ("audio_0_0_0", "audio_0_1_0")
            ],
        )


def test_pilot_accepts_standalone_speech_task(benchmark):
    assets = [dict(task="speech", duration_seconds=i, bytes=100) for i in (1, 5, 10)]
    assert benchmark["select_pilot"](assets) == assets[1:]
