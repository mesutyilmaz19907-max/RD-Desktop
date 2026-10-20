import inspect

from rdclient.app import RDModernApp
from rdclient.i18n import tr


def test_rd_history_label_is_localized():
    assert tr('en', 'tab_rd_downloads') == 'RD History'
    assert tr('fr', 'tab_rd_downloads') == 'Historique RD'
    assert tr('tr', 'tab_rd_downloads') == 'RD Geçmişi'
    assert tr('de', 'tab_rd_downloads') == 'RD-Verlauf'
    assert tr('it', 'tab_rd_downloads') == 'Cronologia RD'


def test_language_selector_lives_in_settings_not_sidebar_footer():
    ui = inspect.getsource(RDModernApp._build_ui)
    settings = inspect.getsource(RDModernApp._build_settings_tab)
    assert '_build_language_selector(bottom)' not in ui
    assert '_build_language_selector(langcontrol)' in settings


def test_account_page_is_hidden_from_nav_and_card_opens_it():
    account = inspect.getsource(RDModernApp._build_account_tab)
    ui = inspect.getsource(RDModernApp._build_ui)
    opener = inspect.getsource(RDModernApp._open_account_page)
    assert 'pack_forget' in account
    assert '_open_account_page()' in ui
    assert 'self.nb.select(index)' in opener
