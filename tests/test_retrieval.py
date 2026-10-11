from uuid import uuid4

import pytest

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
    assert sum(fused[0].channels.values()) == pytest.approx(1.01 / 61)
    assert set(fused[0].channels) == {"transcript", "audio"}
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


def test_alignment_does_not_chain_overlapping_windows_across_moments() -> None:
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
    assert len(groups[0]["matches"]) == 3
    intervals = {
        (match["time_start"], match["time_end"]) for match in groups[0]["matches"]
    }
    assert intervals == {(4, 5), (9, 15), (40, 50)}


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


def test_strong_photo_beats_multiple_weaker_video_channels() -> None:
    photo = candidate(
        uuid4(), uuid4(), kind="image", start=None, end=None, similarity=0.709
    )
    video_asset, generation = uuid4(), uuid4()
    channels = {"image": [photo]}
    for kind, similarity in [("transcript", 0.701), ("audio", 0.622), ("video", 0.582)]:
        item = candidate(video_asset, uuid4(), kind=kind, similarity=similarity)
        item.generation_id = generation
        channels[kind] = [item]
    fused = reciprocal_rank_fusion(channels)
    assert fused[0].asset_id == photo.asset_id
    video = fused[1]
    assert video.score <= (0.701**2 / 61) * 1.01
    assert sum(video.channels.values()) == pytest.approx(video.score)


def test_support_bonus_does_not_grow_with_channel_count() -> None:
    asset, generation = uuid4(), uuid4()
    channels = {}
    for kind in ("image", "audio", "video", "transcript"):
        item = candidate(asset, uuid4(), kind=kind)
        item.generation_id = generation
        channels[kind] = [item]
    two = reciprocal_rank_fusion({key: channels[key] for key in ("image", "audio")})
    four = reciprocal_rank_fusion(channels)
    assert two[0].score == pytest.approx(four[0].score)


@pytest.mark.parametrize(
    "text,confidence",
    [
        (", od", 15.91),
        ("= = =", 95),
        ("a", 90),
        ("long hallucinated text", 20),
        ("A1", float("nan")),
    ],
)
def test_noisy_ocr_cannot_add_dense_or_lexical_evidence(text, confidence) -> None:
    ocr = candidate(uuid4(), uuid4(), kind="ocr")
    ocr.text = text
    ocr.location["ocr_words"] = [{"text": text, "confidence": confidence}]
    assert (
        reciprocal_rank_fusion({"ocr": [ocr], "lexical": [ocr], "identifier": [ocr]})
        == []
    )
    # A filename match is independent of the representative's OCR quality.
    assert reciprocal_rank_fusion({"filename": [ocr]})


@pytest.mark.parametrize("text", ["A1", "42", "NASA", "lunar surface", "月面"])
def test_meaningful_ocr_including_short_identifiers_is_preserved(text) -> None:
    ocr = candidate(uuid4(), uuid4(), kind="ocr")
    ocr.text = text
    ocr.location["ocr_words"] = [{"text": text, "confidence": 90}]
    assert reciprocal_rank_fusion({"ocr": [ocr]})


def test_legacy_ocr_without_confidence_metadata_is_preserved() -> None:
    ocr = candidate(uuid4(), uuid4(), kind="ocr")
    ocr.text = "Apollo 11"
    assert reciprocal_rank_fusion({"ocr": [ocr]})


def test_adjacent_video_windows_do_not_align_at_a_boundary() -> None:
    asset, generation = uuid4(), uuid4()
    early = candidate(asset, uuid4(), kind="video", start=0, end=20)
    late = candidate(asset, uuid4(), kind="video", start=20, end=40)
    early.generation_id = late.generation_id = generation
    fused = reciprocal_rank_fusion({"video": [early, late]})
    assert len(fused) == 2


def test_overlapping_video_windows_stay_bounded_and_preserve_all_evidence() -> None:
    asset, generation = uuid4(), uuid4()
    windows = [
        candidate(asset, uuid4(), kind="video", start=start, end=start + 20)
        for start in range(0, 75, 15)
    ]
    for item in windows:
        item.generation_id = generation
    fused = reciprocal_rank_fusion({"video": windows})
    matches = group_assets(fused)[0]["matches"]
    assert len(matches) == 3
    assert all(match["time_end"] - match["time_start"] <= 20 for match in matches)
    assert {
        item["representation_id"]
        for match in matches
        for item in match["representations"]
    } == {str(item.representation_id) for item in windows}


def test_noisy_ocr_cannot_bridge_distant_moments() -> None:
    asset, generation = uuid4(), uuid4()
    early = candidate(asset, uuid4(), start=0, end=5)
    late = candidate(asset, uuid4(), start=20, end=25)
    noise = candidate(asset, uuid4(), kind="ocr", start=0, end=25)
    noise.text = "= = ="
    for item in (early, late, noise):
        item.generation_id = generation
    assert (
        len(reciprocal_rank_fusion({"transcript": [early, late], "ocr": [noise]})) == 2
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
@pytest.mark.parametrize(
    "query,photo_similarity,other_similarity,ocr_similarity",
    [
        ("small rock embedded in dusty ground", 0.709, 0.684, 0.633),
        ("American flag on the lunar surface", 0.814, 0.670, 0.696),
    ],
)
async def test_image_search_keeps_strong_visual_match_above_ocr_supported_photo(
    mode, query, photo_similarity, other_similarity, ocr_similarity
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from search_anything.models import Asset, ProcessingGeneration, Representation
    from search_anything.retrieval import search_workspace

    workspace = uuid4()
    correct = Asset(id=uuid4(), filename="correct.jpg", content_type="image/jpeg")
    other = Asset(id=uuid4(), filename="other.jpg", content_type="image/jpeg")
    correct_generation = ProcessingGeneration(id=uuid4())
    other_generation = ProcessingGeneration(id=uuid4())

    def row(asset, generation, kind, similarity, text=None):
        return (
            asset,
            generation,
            Representation(
                id=uuid4(),
                kind=kind,
                text_content=text,
                metadata_json={
                    "width": 100,
                    "height": 100,
                    "ocr_words": [{"text": text, "confidence": 90}],
                },
            ),
            None,
            1 - similarity,
        )

    noisy = row(other, other_generation, "ocr", 0.99, ", od")
    noisy[2].metadata_json["ocr_words"][0]["confidence"] = 15.91
    ocr = row(other, other_generation, "ocr", ocr_similarity, "lunar surface")
    images = [
        row(correct, correct_generation, "image", photo_similarity),
        row(other, other_generation, "image", other_similarity),
    ]
    responses = [[], [], [noisy, ocr], images, [], []]
    if mode == "hybrid":
        responses.extend([[], [], []])
    session = AsyncMock()
    results = []
    for rows in responses:
        result = MagicMock()
        result.all.return_value = rows
        results.append(result)
    session.execute.side_effect = results
    output = await search_workspace(
        session,
        workspace,
        query=query,
        vector=[0.0] * 768,
        mode=mode,
        limit=12,
        candidate_limit=60,
        content_types=["image/jpeg"],
    )
    assert output[0]["filename"] == "correct.jpg"
    assert all(
        representation["text"] != ", od"
        for asset in output
        for match in asset["matches"]
        for representation in match["representations"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "enabled", ["audio", "lexical", "identifier", "filename", None]
)
async def test_disabled_channels_do_not_execute_database_queries(enabled):
    from unittest.mock import AsyncMock, MagicMock
    from search_anything.retrieval import DEFAULT_WEIGHTS, search_workspace

    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = []
    session.execute.return_value = result
    weights = {channel: float(channel == enabled) for channel in DEFAULT_WEIGHTS}
    await search_workspace(
        session,
        uuid4(),
        query="moon",
        vector=[0.0] * 768,
        mode="hybrid",
        limit=10,
        candidate_limit=60,
        weights=weights,
    )
    assert session.execute.await_count == (1 if enabled else 0)
    if enabled == "audio":
        statement = session.execute.call_args.args[0]
        assert "audio" in statement.compile().params.values()
    elif enabled:
        sql = str(session.execute.call_args.args[0])
        assert {
            "lexical": "websearch_to_tsquery",
            "filename": "lower(assets.filename)",
            "identifier": "lower(representations.text_content)",
        }[enabled] in sql


@pytest.mark.asyncio
async def test_dense_ties_have_stable_asset_segment_and_representation_order():
    from unittest.mock import AsyncMock, MagicMock
    from sqlalchemy.dialects import postgresql
    from search_anything.retrieval import search_workspace

    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = []
    session.execute.return_value = result
    await search_workspace(
        session,
        uuid4(),
        query="moon",
        vector=[0.0] * 768,
        mode="semantic",
        limit=10,
        candidate_limit=60,
    )
    # Each dense channel needs the same deterministic order before truncation.
    for call in session.execute.call_args_list:
        sql = str(call.args[0].compile(dialect=postgresql.dialect()))
        order = sql.split("ORDER BY ")[1].split("LIMIT")[0]
        assert "assets.id, segments.ordinal, representations.id" in order
        assert order.index("<=>") < order.index("assets.id")
