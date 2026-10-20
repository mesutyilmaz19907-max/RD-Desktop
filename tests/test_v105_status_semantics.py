import json
import threading
from types import SimpleNamespace

import rdclient.app as appmod
from rdclient.app import RDModernApp
from rdclient.i18n import LANGUAGE_OPTIONS, tr


def _bare_app():
    app = RDModernApp.__new__(RDModernApp)
    app.download_jobs = {}
    app.local_status_state = {}
    app.download_counter = 0
    return app


def test_real_debrid_downloaded_status_is_user_facing_ready():
    expected = {
        "en": "Ready",
        "fr": "Prêt",
        "tr": "Hazır",
        "de": "Bereit",
        "it": "Pronto",
    }
    for code, label in expected.items():
        assert tr(code, "torrent_status_downloaded") == label


def test_missing_local_status_is_localized():
    for code, _label, _flag in LANGUAGE_OPTIONS:
        assert tr(code, "status_missing") != "status_missing"
        assert tr(code, "redownload") != "redownload"
        assert tr(code, "locate_file") != "locate_file"


def test_completed_job_with_deleted_file_loads_as_missing(tmp_path, monkeypatch):
    queue_file = tmp_path / "local-downloads.json"
    gone = tmp_path / "gone.bin"
    queue_file.write_text(json.dumps({"jobs": [{
        "id": 4,
        "url": "https://example.test/gone.bin",
        "dest": str(gone),
        "name": "gone.bin",
        "status": "Completed",
        "downloaded": 123,
        "total": 123,
        "error": "",
    }]}), encoding="utf-8")
    monkeypatch.setattr(appmod, "DOWNLOADS_FILE", queue_file)
    app = _bare_app()
    app._load_download_jobs()
    assert app.download_jobs[4]["status"] == "Missing"
    assert app.download_jobs[4]["error"] == ""


def test_missing_job_self_heals_when_file_is_back(tmp_path, monkeypatch):
    queue_file = tmp_path / "local-downloads.json"
    restored = tmp_path / "restored.bin"
    restored.write_bytes(b"abc")
    queue_file.write_text(json.dumps({"jobs": [{
        "id": 5,
        "url": "https://example.test/restored.bin",
        "dest": str(restored),
        "name": "restored.bin",
        "status": "Missing",
        "downloaded": 3,
        "total": 3,
        "error": "",
    }]}), encoding="utf-8")
    monkeypatch.setattr(appmod, "DOWNLOADS_FILE", queue_file)
    app = _bare_app()
    app._load_download_jobs()
    assert app.download_jobs[5]["status"] == "Completed"


def test_missing_redownload_restarts_from_zero():
    app = _bare_app()
    app.download_jobs[1] = {'status': 'Missing', 'downloaded': 123, 'error': 'old error', 'speed': 0, 'eta': None}
    app.download_lock = threading.RLock()
    app._selected_local_ids = lambda: [1]
    app._render_download_job = lambda _did: None
    saved, wakeups = [], []
    app._save_download_jobs = lambda: saved.append(dict(app.download_jobs[1]))
    app.download_wakeup = SimpleNamespace(set=lambda: wakeups.append(True))
    app.retry_local_download()
    assert app.download_jobs[1]['status'] == 'Queued'
    assert app.download_jobs[1]['downloaded'] == 0
    assert app.download_jobs[1]['error'] == ''
    assert app.local_status_state[1] == 'Queued'
    assert len(saved) == 1 and wakeups == [True]
