from rdclient.app import format_timestamp


def test_real_debrid_timestamp_is_human_readable():
    value = format_timestamp("2026-10-10T05:41:01.000Z")
    assert "10 Oct 2026" in value
    assert "T05:41:01.000Z" not in value
    assert "·" in value


def test_unknown_timestamp_is_left_alone():
    assert format_timestamp("not-a-date") == "not-a-date"


def test_parse_magnet_lines_deduplicates_and_reports_invalid():
    from rdclient.app import parse_magnet_lines

    a = "magnet:?xt=urn:btih:AAAA"
    b = "magnet:?xt=urn:btih:BBBB"
    magnets, invalid = parse_magnet_lines(f"  {a}  \n\n{b}\n{a}\nhttps://example.invalid/not-a-magnet\n")
    assert magnets == [a, b]
    assert invalid == ["https://example.invalid/not-a-magnet"]
