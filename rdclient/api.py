from __future__ import annotations

import json
import logging
import socket
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import SecretStore
from .constants import DEVICE_GRANT, OAUTH_BASE, OPEN_SOURCE_CLIENT_ID, REST_BASE, USER_AGENT


class RealDebridError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, error_code: int | None = None):
        super().__init__(message)
        self.status = status
        self.error_code = error_code


@dataclass(frozen=True)
class HTTPResult:
    status: int
    headers: Any
    body: bytes


class RealDebridAPI:
    """Small Real-Debrid client with OAuth refresh, pacing and bounded retries."""

    def __init__(self, store: SecretStore, timeout: int = 30) -> None:
        self.store = store
        self.timeout = timeout
        self.user_agent = USER_AGENT
        self._refresh_lock = threading.Lock()
        self._rate_lock = threading.Lock()
        self._last_request = 0.0
        self._min_request_interval = 0.27

    @property
    def authenticated(self) -> bool:
        return self.store.public.auth_mode == "oauth" and bool(self.store.get("access_token") or self.store.get("refresh_token"))

    def _pace(self) -> None:
        with self._rate_lock:
            now = time.monotonic()
            delay = self._min_request_interval - (now - self._last_request)
            if delay > 0:
                time.sleep(delay)
            self._last_request = time.monotonic()

    @staticmethod
    def _normalize_data(data: dict[str, Any] | None) -> dict[str, Any] | None:
        if data is None:
            return None
        return {k: unicodedata.normalize("NFC", v) if isinstance(v, str) else v for k, v in data.items()}

    @staticmethod
    def _decode(body: bytes, headers: Any) -> Any:
        if not body:
            return None
        text = body.decode("utf-8", errors="replace")
        try:
            content_type = str(headers.get("Content-Type", "") or "")
        except Exception:
            content_type = ""
        if "json" in content_type.lower() or text[:1] in "[{":
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
        return text

    def _error(self, result: HTTPResult) -> RealDebridError:
        payload = self._decode(result.body, result.headers)
        if isinstance(payload, dict):
            message = str(payload.get("error") or f"Real-Debrid returned HTTP {result.status}")
            raw_code = payload.get("error_code")
            try:
                code = int(raw_code) if raw_code is not None else None
            except (TypeError, ValueError):
                code = None
        else:
            message, code = str(payload or f"Real-Debrid returned HTTP {result.status}"), None
        return RealDebridError(message, status=result.status, error_code=code)

    def _send(self, method: str, url: str, *, params=None, data=None, content=None, headers=None, retries=None) -> HTTPResult:
        method = method.upper()
        params = self._normalize_data(params)
        data = self._normalize_data(data)
        if params:
            query = urllib.parse.urlencode(params, doseq=True)
            url += ("&" if "?" in url else "?") + query

        request_headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        request_headers.update(headers or {})
        body: bytes | None = content
        if content is None and data is not None:
            body = urllib.parse.urlencode(data, doseq=True).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

        attempts = max(1, retries if retries is not None else (3 if method in {"GET", "HEAD"} else 2))
        last_error: Exception | None = None
        for attempt in range(attempts):
            self._pace()
            request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return HTTPResult(int(response.status), response.headers, response.read())
            except urllib.error.HTTPError as exc:
                result = HTTPResult(int(exc.code), exc.headers, exc.read())
                retryable = exc.code == 429 or (method in {"GET", "HEAD"} and exc.code in {500, 502, 503, 504})
                if retryable and attempt + 1 < attempts:
                    delay = 0.8 * (2**attempt)
                    try:
                        delay = max(delay, float(exc.headers.get("Retry-After", "0") or 0))
                    except Exception:
                        pass
                    time.sleep(min(delay, 10.0))
                    continue
                return result
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as exc:
                last_error = exc
                # Only retry reads automatically. A POST/PUT may have reached the server.
                if method in {"GET", "HEAD"} and attempt + 1 < attempts:
                    time.sleep(0.8 * (2**attempt))
                    continue
                break
        raise RealDebridError("Could not reach Real-Debrid. The HTTPS connection failed or timed out.") from last_error

    def _token(self) -> str:
        if self.store.public.auth_mode != "oauth":
            raise RealDebridError("Not authenticated.")
        token = self.store.get("access_token")
        if not token or time.time() >= self.store.public.access_expires_at:
            self.refresh_access_token()
            token = self.store.get("access_token")
        if not token:
            raise RealDebridError("No access token is available. Sign in again.")
        return token

    def request(self, method: str, path: str, *, params=None, data=None, content=None, headers=None, auth=True, retry_auth=True) -> Any:
        request_headers = dict(headers or {})
        if auth:
            request_headers["Authorization"] = f"Bearer {self._token()}"
        result = self._send(method, f"{REST_BASE}/{path.lstrip('/')}", params=params, data=data, content=content, headers=request_headers)
        if result.status == 401 and auth and retry_auth:
            self.refresh_access_token(force=True)
            return self.request(method, path, params=params, data=data, content=content, headers=headers, auth=auth, retry_auth=False)
        if result.status >= 400:
            raise self._error(result)
        return self._decode(result.body, result.headers)

    # OAuth ---------------------------------------------------------
    def start_open_source_oauth(self) -> dict[str, Any]:
        result = self._send("GET", f"{OAUTH_BASE}/device/code", params={"client_id": OPEN_SOURCE_CLIENT_ID, "new_credentials": "yes"})
        if result.status >= 400:
            raise self._error(result)
        payload = self._decode(result.body, result.headers)
        required = ("device_code", "user_code", "verification_url")
        if not isinstance(payload, dict) or any(not payload.get(key) for key in required):
            raise RealDebridError("Real-Debrid returned an incomplete OAuth device response.")
        logging.info("OAuth device authorization started; expires_in=%s interval=%s", payload.get("expires_in"), payload.get("interval"))
        return payload

    def poll_open_source_credentials(self, device_code: str) -> dict[str, Any] | None:
        result = self._send("GET", f"{OAUTH_BASE}/device/credentials", params={"client_id": OPEN_SOURCE_CLIENT_ID, "code": device_code}, retries=1)
        payload = self._decode(result.body, result.headers)
        if result.status < 400:
            if not isinstance(payload, dict) or not payload.get("client_id") or not payload.get("client_secret"):
                raise RealDebridError("Real-Debrid returned incomplete OAuth credentials.")
            logging.info("OAuth account-bound credentials received")
            return payload

        # RD documents that this endpoint returns an error while authorization is pending.
        # Preserve the body in logs and only treat ordinary 400/403 responses as pending;
        # known terminal/service errors are surfaced immediately instead of looking frozen.
        error = self._error(result)
        logging.info("OAuth credential poll: HTTP %s code=%s error=%s", result.status, error.error_code, error)
        if result.status in {400, 403} and error.error_code is None:
            return None
        raise error

    def exchange_device_code(self, client_id: str, client_secret: str, device_code: str) -> dict[str, Any]:
        result = self._send("POST", f"{OAUTH_BASE}/token", data={"client_id": client_id, "client_secret": client_secret, "code": device_code, "grant_type": DEVICE_GRANT})
        if result.status >= 400:
            raise self._error(result)
        payload = self._decode(result.body, result.headers)
        if not isinstance(payload, dict) or not payload.get("access_token") or not payload.get("refresh_token"):
            raise RealDebridError("Real-Debrid returned an incomplete OAuth token response.")
        return payload

    def refresh_access_token(self, force: bool = False) -> dict[str, Any]:
        with self._refresh_lock:
            if not force:
                existing = self.store.get("access_token")
                if existing and time.time() < self.store.public.access_expires_at:
                    return {"access_token": existing}
            client_id = self.store.get("client_id")
            client_secret = self.store.get("client_secret")
            refresh_token = self.store.get("refresh_token")
            if not client_id or not client_secret or not refresh_token:
                raise RealDebridError("Saved login is incomplete. Sign in again.")
            result = self._send("POST", f"{OAUTH_BASE}/token", data={"client_id": client_id, "client_secret": client_secret, "code": refresh_token, "grant_type": DEVICE_GRANT})
            if result.status >= 400:
                raise self._error(result)
            payload = self._decode(result.body, result.headers)
            if not isinstance(payload, dict) or not payload.get("access_token"):
                raise RealDebridError("Real-Debrid returned an incomplete refresh-token response.")
            self.store.update_oauth_tokens(str(payload["access_token"]), str(payload.get("refresh_token") or refresh_token), int(payload.get("expires_in", 0) or 0))
            return payload

    def test_auth(self) -> dict[str, Any]:
        return self.user()

    # REST ----------------------------------------------------------
    def user(self) -> dict[str, Any]:
        result = self.request("GET", "user")
        return result if isinstance(result, dict) else {}

    def active_count(self) -> dict[str, Any]:
        result = self.request("GET", "torrents/activeCount")
        return result if isinstance(result, dict) else {}

    def torrents(self, limit: int = 5000) -> list[dict[str, Any]]:
        result = self.request("GET", "torrents", params={"limit": limit})
        return result if isinstance(result, list) else []

    def torrent_info(self, torrent_id: str) -> dict[str, Any]:
        result = self.request("GET", f"torrents/info/{torrent_id}")
        return result if isinstance(result, dict) else {}

    def add_torrent(self, path: str) -> dict[str, Any]:
        result = self.request("PUT", "torrents/addTorrent", content=Path(path).read_bytes(), headers={"Content-Type": "application/x-bittorrent"})
        return result if isinstance(result, dict) else {}

    def add_magnet(self, magnet: str) -> dict[str, Any]:
        result = self.request("POST", "torrents/addMagnet", data={"magnet": magnet.strip()})
        return result if isinstance(result, dict) else {}

    def select_files(self, torrent_id: str, file_ids: Iterable[int] | str) -> None:
        files = file_ids if isinstance(file_ids, str) else ",".join(str(x) for x in file_ids)
        self.request("POST", f"torrents/selectFiles/{torrent_id}", data={"files": files})

    def delete_torrent(self, torrent_id: str) -> None:
        self.request("DELETE", f"torrents/delete/{torrent_id}")

    def downloads(self, limit: int = 5000) -> list[dict[str, Any]]:
        result = self.request("GET", "downloads", params={"limit": limit})
        return result if isinstance(result, list) else []

    def delete_download(self, download_id: str) -> None:
        self.request("DELETE", f"downloads/delete/{download_id}")

    def unrestrict_link(self, link: str, password: str = "", remote: bool = False) -> Any:
        data: dict[str, Any] = {"link": link, "remote": 1 if remote else 0}
        if password:
            data["password"] = password
        return self.request("POST", "unrestrict/link", data=data)

    def unrestrict_folder(self, link: str) -> list[str]:
        result = self.request("POST", "unrestrict/folder", data={"link": link})
        return [str(item) for item in result] if isinstance(result, list) else []
