import pytest

from search_anything.ranges import ByteRange, UnsatisfiableRange, parse_range


def test_range_parsing_supports_closed_open_and_suffix_ranges() -> None:
    assert parse_range(None, 10) is None
    assert parse_range("bytes=2-5", 10) == ByteRange(2, 5)
    assert parse_range("bytes=7-", 10) == ByteRange(7, 9)
    assert parse_range("bytes=-3", 10) == ByteRange(7, 9)


@pytest.mark.parametrize(
    "header,size",
    [("bytes=10-", 10), ("bytes=4-2", 10), ("bytes=-0", 10), ("bytes=0-1,4-5", 10)],
)
def test_unsatisfiable_ranges_are_rejected(header: str, size: int) -> None:
    with pytest.raises(UnsatisfiableRange):
        parse_range(header, size)
