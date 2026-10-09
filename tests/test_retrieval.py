from uuid import uuid4

from search_anything.retrieval import Candidate, group_assets, reciprocal_rank_fusion


def candidate(
    asset_id,
    representation_id,
    *,
    kind="transcript",
    start=0.0,
    end=10.0,
    score=0.0,
    page=None,
    source_start=None,
    source_end=None,
    heading=None,
    similarity=None,
):
    location = {}
    if page is not None:
        location["page"] = page
    if heading is not None:
        location["heading"] = heading
    return Candidate(
        asset_id=asset_id,
        filename="lecture.mp4",
        content_type="video/mp4",
        representation_id=representation_id,
        generation_id=uuid4(),
        kind=kind,
        text="matching passage",
        location=location,
        source_start=source_start,
        source_end=source_end,
        time_start=start,
        time_end=end,
        score=score,
        similarity=similarity,
    )


def test_fusion_combines_aligned_audio_and_transcript_evidence() -> None:
    asset, generation = uuid4(), uuid4()
    transcript = candidate(asset, uuid4(), kind="transcript", start=8, end=14)
    audio = candidate(asset, uuid4(), kind="audio", start=10, end=20)
    # The same canonical generation is required for alignment.
    transcript.generation_id = generation
    audio.generation_id = generation
    fused = reciprocal_rank_fusion(
        {"transcript": [transcript], "audio": [audio]},
    )
    assert len(fused) == 1
    assert fused[0].channels == {"transcript": 1 / 61, "audio": 1 / 61}
    grouped = group_assets(fused)
    assert len(grouped) == 1
    assert len(grouped[0]["matches"]) == 1
    assert {item["kind"] for item in grouped[0]["matches"][0]["representations"]} == {
        "transcript",
        "audio",
    }


def test_fusion_deduplicates_a_channel_and_weights_remain_live() -> None:
    asset, generation = uuid4(), uuid4()
    first = candidate(asset, uuid4(), start=0, end=5)
    second = candidate(asset, uuid4(), start=30, end=35)
    first.generation_id = second.generation_id = generation
    fused = reciprocal_rank_fusion(
        {"transcript": [first, first, second]}, {"transcript": 3.0}
    )
    by_span = {hit.time_start: hit for hit in fused}
    assert by_span[0].score == 3 / 61
    assert by_span[30].score == 3 / 62


def test_channel_weights_change_rank_without_changing_candidates() -> None:
    asset, generation = uuid4(), uuid4()
    transcript = candidate(asset, uuid4(), kind="transcript", start=0, end=2)
    video = candidate(asset, uuid4(), kind="video", start=20, end=22)
    transcript.generation_id = video.generation_id = generation
    candidates = {"transcript": [transcript], "video": [video]}
    transcript_first = reciprocal_rank_fusion(candidates, {"transcript": 2, "video": 1})
    video_first = reciprocal_rank_fusion(candidates, {"transcript": 1, "video": 2})
    assert transcript_first[0].kind == "transcript"
    assert video_first[0].kind == "video"


def test_transitive_alignment_keeps_distant_moments_under_one_asset() -> None:
    asset, generation = uuid4(), uuid4()
    early = candidate(asset, uuid4(), kind="transcript", start=0, end=5)
    bridge = candidate(asset, uuid4(), kind="audio", start=4, end=10)
    late = candidate(asset, uuid4(), kind="video", start=9, end=15)
    distant = candidate(asset, uuid4(), kind="video", start=40, end=50)
    for item in (early, bridge, late, distant):
        item.generation_id = generation
    fused = reciprocal_rank_fusion(
        {
            "transcript": [early],
            "audio": [bridge],
            "video": [late, distant],
        }
    )
    groups = group_assets(fused)
    assert len(groups) == 1
    assert len(groups[0]["matches"]) == 2
    intervals = {
        (match["time_start"], match["time_end"]) for match in groups[0]["matches"]
    }
    assert intervals == {(0, 15), (40, 50)}


def test_disabled_channel_cannot_bridge_otherwise_separate_spans() -> None:
    asset, generation = uuid4(), uuid4()
    transcript = candidate(asset, uuid4(), kind="transcript", start=0, end=5)
    audio = candidate(asset, uuid4(), kind="audio", start=4, end=10)
    video = candidate(asset, uuid4(), kind="video", start=9, end=15)
    for item in (transcript, audio, video):
        item.generation_id = generation
    fused = reciprocal_rank_fusion(
        {"transcript": [transcript], "audio": [audio], "video": [video]},
        {"audio": 0},
    )
    assert len(fused) == 2
    assert all("audio" not in hit.channels for hit in fused)


def test_source_alignment_is_scoped_by_generation_page_and_heading() -> None:
    asset, generation = uuid4(), uuid4()
    page_one = candidate(
        asset, uuid4(), start=None, end=None, source_start=0, source_end=20, page=1
    )
    page_two = candidate(
        asset, uuid4(), start=None, end=None, source_start=0, source_end=20, page=2
    )
    page_one.generation_id = page_two.generation_id = generation
    fused = reciprocal_rank_fusion({"text": [page_one, page_two]})
    assert len(fused) == 2
    assert len(group_assets(fused)[0]["matches"]) == 2

    section_a = candidate(
        asset,
        uuid4(),
        start=None,
        end=None,
        source_start=0,
        source_end=20,
        page=1,
        heading="Alpha",
    )
    section_b = candidate(
        asset,
        uuid4(),
        start=None,
        end=None,
        source_start=0,
        source_end=20,
        page=1,
        heading="Beta",
    )
    section_a.generation_id = section_b.generation_id = generation
    assert len(reciprocal_rank_fusion({"text": [section_a, section_b]})) == 2
