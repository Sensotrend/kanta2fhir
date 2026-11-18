from kanta2fhir import hetu

from .conftest import TEST_HETU


def test_valid_test_hetu() -> None:
    assert hetu.is_valid(TEST_HETU)
    assert hetu.is_test_hetu(TEST_HETU)
    assert hetu.birth_date(TEST_HETU) == "2001-10-05"
    assert hetu.sex(TEST_HETU) == "male"


def test_invalid_check_character() -> None:
    assert not hetu.is_valid("051001A937T")
    assert hetu.birth_date("051001A937T") is None


def test_invalid_date_and_format() -> None:
    assert not hetu.is_valid("310201A937S")  # 31 February
    assert not hetu.is_valid("051001Z937S")  # unknown century sign
    assert not hetu.is_valid("")


def test_century_signs() -> None:
    # The check character does not depend on the century sign.
    for sign, year in [("+", "1801"), ("-", "1901"), ("Y", "1901"), ("A", "2001"), ("F", "2001")]:
        code = f"010101{sign}900R"
        assert hetu.is_valid(code), code
        assert hetu.birth_date(code) == f"{year}-01-01"


def test_leap_day() -> None:
    assert hetu.birth_date("290200A901C") == "2000-02-29"
    assert hetu.sex("290200A901C") == "male"
    assert not hetu.is_valid("290201A901C")  # 2001 is not a leap year


def test_pseudonym_is_stable_and_hides_hetu() -> None:
    p = hetu.pseudonym(TEST_HETU)
    assert p == hetu.pseudonym(TEST_HETU)
    assert TEST_HETU not in p
    assert len(p) == 16


def test_redact() -> None:
    name = f"kanta_terveystiedot_{TEST_HETU}_1791361732438.ndjson"
    assert hetu.redact(name) == "kanta_terveystiedot_<hetu>_1791361732438.ndjson"
    assert hetu.redact("051001A937T") == "051001A937T"  # invalid check character: not a HETU
