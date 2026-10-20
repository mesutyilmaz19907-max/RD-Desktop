from rdclient.app import MAX_SAFE_SIMULTANEOUS_DOWNLOADS
from rdclient.config import PublicConfig
from rdclient.i18n import LANGUAGE_OPTIONS, tr


def test_default_simultaneous_downloads_is_three():
    assert PublicConfig().max_simultaneous_downloads == 3


def test_safe_simultaneous_cap_is_eight():
    assert MAX_SAFE_SIMULTANEOUS_DOWNLOADS == 8


def test_v10_navigation_and_settings_strings_exist_for_every_language():
    for code, _label, _flag in LANGUAGE_OPTIONS:
        assert tr(code, "settings") != "settings"
        assert tr(code, "downloads_nav") != "downloads_nav"
        assert tr(code, "simultaneous_downloads") != "simultaneous_downloads"


def test_pause_and_failure_statuses_are_localized():
    for code, _label, _flag in LANGUAGE_OPTIONS:
        assert tr(code, "status_paused") != "status_paused"
        assert tr(code, "status_failed") != "status_failed"


def test_download_limit_input_validation():
    from rdclient.app import normalize_download_limit
    assert normalize_download_limit("1", 3) == (1, True)
    assert normalize_download_limit("8", 3) == (8, True)
    assert normalize_download_limit("0", 3) == (1, False)
    assert normalize_download_limit("9", 3) == (8, False)
    assert normalize_download_limit("", 5) == (5, False)
    assert normalize_download_limit("abc", 4) == (4, False)


def test_download_limit_live_warning_helper():
    from rdclient.app import download_limit_text_needs_warning
    assert download_limit_text_needs_warning("0") is True
    assert download_limit_text_needs_warning("9") is True
    assert download_limit_text_needs_warning("10") is True
    assert download_limit_text_needs_warning("abc") is True
    assert download_limit_text_needs_warning("") is False
    assert download_limit_text_needs_warning("1") is False
    assert download_limit_text_needs_warning("8") is False
