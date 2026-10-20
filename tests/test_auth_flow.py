from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from rdclient.api import HTTPResult, RealDebridAPI, RealDebridError


class Store:
    public = SimpleNamespace(auth_mode="", access_expires_at=0)
    def get(self, _key):
        return None


class PollAPI(RealDebridAPI):
    def __init__(self, result: HTTPResult):
        super().__init__(Store())
        self.result = result
    def _send(self, *_args, **_kwargs):
        return self.result


def result(status: int, payload: dict) -> HTTPResult:
    return HTTPResult(status, {"Content-Type": "application/json"}, json.dumps(payload).encode())


def test_oauth_pending_response_is_not_silently_logged_as_success():
    api = PollAPI(result(403, {"error": "authorization_pending"}))
    assert api.poll_open_source_credentials("device") is None


def test_oauth_terminal_error_is_raised_instead_of_polling_forever():
    api = PollAPI(result(400, {"error": "bad_parameter", "error_code": 2}))
    with pytest.raises(RealDebridError) as exc:
        api.poll_open_source_credentials("device")
    assert exc.value.error_code == 2


def test_oauth_credentials_require_both_client_values():
    api = PollAPI(result(200, {"client_id": "abc"}))
    with pytest.raises(RealDebridError):
        api.poll_open_source_credentials("device")
