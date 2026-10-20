from rdclient.i18n import LANGUAGE_OPTIONS, TRANSLATIONS, normalize_language, tr
from rdclient.app import format_timestamp


def test_language_set_is_complete():
    assert [code for code, _label, _flag in LANGUAGE_OPTIONS] == ["en", "fr", "tr", "de", "it"]
    english_keys = set(TRANSLATIONS["en"])
    for code in ("fr", "tr", "de", "it"):
        assert set(TRANSLATIONS[code]) == english_keys


def test_translation_fallback_and_normalization():
    assert normalize_language("TR") == "tr"
    assert normalize_language("xx") == "en"
    assert tr("fr", "ready") == "Prêt"
    assert tr("xx", "ready") == "Ready"


def test_timestamp_month_is_localized():
    # The day may shift with the machine timezone, but October remains October
    # for normal timezone offsets around this test timestamp.
    value = "2026-10-10T05:41:01.000Z"
    assert "oct." in format_timestamp(value, "fr")
    assert "Eki" in format_timestamp(value, "tr")
    assert "Okt" in format_timestamp(value, "de")
    assert "ott" in format_timestamp(value, "it")


def test_batch_queue_strings_exist_in_all_languages():
    for code in ("en", "fr", "tr", "de", "it"):
        assert tr(code, "upload_torrents") != "upload_torrents"
        assert tr(code, "upload_queue_title") != "upload_queue_title"
        assert tr(code, "queue_magnets") != "queue_magnets"
