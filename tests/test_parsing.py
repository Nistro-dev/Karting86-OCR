from apex_ocr.ocr.parsing import (
    LenientReading,
    StrictReading,
    extract_laps,
    extract_time,
    parse_lenient,
    parse_strict,
    repair_colons,
    seconds_from_time,
    time_from_seconds,
)


def test_parse_strict_time_only():
    r = parse_strict("07:32")
    assert r == StrictReading(time_text="07:32", laps_done=None, laps_total=None)


def test_parse_strict_time_with_hours():
    r = parse_strict("1:23:45")
    assert r.time_text == "1:23:45"


def test_parse_strict_with_laps():
    r = parse_strict("5/20 07:32")
    assert r == StrictReading(time_text="07:32", laps_done=5, laps_total=20)


def test_parse_strict_with_laps_hundreds():
    r = parse_strict("125/300 01:23:45")
    assert r == StrictReading(time_text="01:23:45", laps_done=125, laps_total=300)


def test_parse_strict_extra_spacing_around_slash():
    r = parse_strict("5 / 20  07:32")
    assert r == StrictReading(time_text="07:32", laps_done=5, laps_total=20)


def test_parse_strict_missing_colon_is_repaired():
    r = parse_strict("0732")
    assert r.time_text == "07:32"


def test_parse_strict_missing_colon_with_laps():
    r = parse_strict("5/20 0732")
    assert r == StrictReading(time_text="07:32", laps_done=5, laps_total=20)


def test_parse_strict_rejects_garbage():
    assert parse_strict("garbage") is None
    assert parse_strict("") is None


def test_parse_strict_rejects_out_of_range_minutes_or_seconds():
    # "09:49" mal lu par l'OCR (0 -> 6) donnerait "69:49" : doit être rejeté,
    # pas accepté comme un temps de 69 minutes.
    assert parse_strict("69:49") is None
    assert parse_strict("09:69") is None
    assert parse_strict("01:23:69") is None
    assert parse_strict("01:69:33") is None


def test_parse_strict_rejects_leftover_noise():
    # un token numérique en trop après le temps -> lecture rejetée (armement strict)
    assert parse_strict("5/20 07:32 99") is None


def test_parse_lenient_full_reading():
    r = parse_lenient("5/20 07:32")
    assert r == LenientReading(time_text="07:32", laps_done=5, laps_total=20)


def test_parse_lenient_time_unreadable_keeps_laps():
    r = parse_lenient("5/20")
    assert r.laps_done == 5 and r.laps_total == 20
    assert r.time_text is None


def test_parse_lenient_laps_unreadable_keeps_time():
    r = parse_lenient("07:32")
    assert r.time_text == "07:32"
    assert r.laps_done is None


def test_parse_lenient_detects_laps_even_if_not_seen_before():
    # les tours doivent être détectés dès qu'ils apparaissent, pas seulement
    # si on s'y attendait déjà (sinon impossible de détecter leur apparition
    # en cours de session)
    r = parse_lenient("5/20 07:32")
    assert r.laps_done == 5 and r.laps_total == 20
    assert r.time_text == "07:32"


def test_repair_colons():
    assert repair_colons("732") == "7:32"
    assert repair_colons("0732") == "07:32"
    assert repair_colons("12345") == "1:23:45"
    assert repair_colons("012345") == "01:23:45"


def test_extract_time_and_laps_helpers():
    assert extract_time("blah 07:32 blah") == "07:32"
    assert extract_laps("5/20 07:32") == (5, 20)
    assert extract_laps("07:32") is None


def test_seconds_and_time_roundtrip():
    assert seconds_from_time("07:32") == 452
    assert seconds_from_time("01:23:45") == 5025
    assert time_from_seconds(452, with_hours=False) == "07:32"
    assert time_from_seconds(5025, with_hours=True) == "01:23:45"
    assert time_from_seconds(0, with_hours=False) == "00:00"
    assert time_from_seconds(-5, with_hours=False) == "00:00"
