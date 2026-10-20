from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .constants import USER_AGENT
from .platform_support import atomic_write_text


class DownloadError(RuntimeError):
    pass


class IncompleteDownloadError(DownloadError):
    pass


@dataclass(frozen=True)
class TransferResult:
    status: str
    downloaded: int
    total: int


class DownloadJobStore:
    """Thread-safe, atomic persistence for the local transfer queue."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def load(self) -> list[dict[str, Any]]:
        with self._lock:
            if not self.path.exists():
                return []
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        rows = payload.get("jobs", []) if isinstance(payload, dict) else []
        return [dict(row) for row in rows if isinstance(row, dict)]

    def save(self, jobs: Mapping[int, Mapping[str, Any]]) -> None:
        clean = []
        for _did, source in sorted(jobs.items()):
            row = {k: v for k, v in dict(source).items() if k not in {"speed", "eta"}}
            clean.append(row)
        payload = json.dumps({"version": 1, "jobs": clean}, indent=2, ensure_ascii=False)
        with self._lock:
            atomic_write_text(self.path, payload)


def reconcile_job(raw: Mapping[str, Any]) -> dict[str, Any]:
    job = dict(raw)
    status = str(job.get("status", "Paused"))
    dest = Path(str(job.get("dest", "") or ""))
    part = Path(str(dest) + ".part") if str(dest) else None
    expected = int(job.get("total", 0) or 0)

    if status in {"Downloading", "Queued"}:
        status = "Paused"
    if status == "Completed":
        if not str(dest) or not dest.exists():
            status = "Missing"
            job["error"] = ""
        elif expected and dest.stat().st_size != expected:
            status = "Failed"
            job["error"] = "Completed file size does not match the expected size."
    elif status == "Missing" and str(dest) and dest.exists():
        actual = dest.stat().st_size
        if not expected or actual == expected:
            status = "Completed"
            job["downloaded"] = actual
            job["total"] = expected or actual
            job["error"] = ""
    elif status == "Paused" and part and part.exists():
        job["downloaded"] = part.stat().st_size

    job["status"] = status
    job["speed"] = 0.0
    job["eta"] = None
    return job


def _parse_total(headers: Any, downloaded_before: int, response_status: int, fallback: int) -> int:
    content_range = ""
    try:
        content_range = str(headers.get("Content-Range", "") or "")
    except Exception:
        pass
    if "/" in content_range:
        tail = content_range.rsplit("/", 1)[1].strip()
        if tail.isdigit():
            return int(tail)
    try:
        length = int(headers.get("Content-Length", "0") or 0)
    except Exception:
        length = 0
    if length:
        return downloaded_before + length if response_status == 206 else length
    return max(0, int(fallback or 0))


def download_file(
    *,
    url: str,
    destination: str,
    expected_total: int = 0,
    stop_action: Callable[[], str | None],
    progress: Callable[[int, int, float, float | None], None],
    timeout: float = 30.0,
) -> TransferResult:
    """Download one file safely, preserving a .part file for resume.

    A final file is only created after the response reaches EOF *and* its byte
    count matches the advertised/known total when such a total is available.
    """
    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = Path(str(dest) + ".part")
    existing = part.stat().st_size if part.exists() else 0

    def open_response(resume_from: int):
        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        if resume_from:
            headers["Range"] = f"bytes={resume_from}-"
        request = urllib.request.Request(url, headers=headers, method="GET")
        return urllib.request.urlopen(request, timeout=timeout)

    try:
        response = open_response(existing)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and existing and expected_total and existing == expected_total:
            os.replace(part, dest)
            return TransferResult("Completed", existing, expected_total)
        if exc.code == 416 and existing:
            part.unlink(missing_ok=True)
            existing = 0
            response = open_response(0)
        else:
            raise DownloadError(f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DownloadError(f"Download connection failed: {exc}") from exc

    with response:
        status = int(getattr(response, "status", 200) or 200)
        append = bool(existing and status == 206)
        mode = "ab" if append else "wb"
        downloaded = existing if append else 0
        total = _parse_total(response.headers, downloaded, status, expected_total)
        if expected_total:
            total = max(total, int(expected_total)) if total else int(expected_total)

        samples: list[tuple[float, int]] = [(time.monotonic(), downloaded)]
        last_progress = 0.0
        with open(part, mode) as fh:
            while True:
                action = stop_action()
                if action:
                    fh.flush()
                    try:
                        os.fsync(fh.fileno())
                    except OSError:
                        pass
                    return TransferResult("Paused" if action == "pause" else "Cancelled", downloaded, total)

                try:
                    chunk = response.read(1024 * 1024)
                except (TimeoutError, OSError) as exc:
                    raise DownloadError(f"Download stream failed: {exc}") from exc
                if not chunk:
                    break
                fh.write(chunk)
                downloaded += len(chunk)
                now = time.monotonic()
                samples.append((now, downloaded))
                samples = [sample for sample in samples if now - sample[0] <= 4.0]
                speed = 0.0
                if len(samples) > 1:
                    speed = (samples[-1][1] - samples[0][1]) / max(0.001, samples[-1][0] - samples[0][0])
                eta = (total - downloaded) / speed if total and speed > 1 and downloaded <= total else None
                if now - last_progress >= 0.30:
                    progress(downloaded, total, speed, eta)
                    last_progress = now
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass

    actual = part.stat().st_size if part.exists() else downloaded
    if total and actual != total:
        raise IncompleteDownloadError(f"Transfer ended early ({actual} of {total} bytes). Partial file kept for resume.")
    if expected_total and actual != expected_total:
        raise IncompleteDownloadError(
            f"Downloaded size does not match Real-Debrid metadata ({actual} of {expected_total} bytes). Partial file kept for resume."
        )

    os.replace(part, dest)
    return TransferResult("Completed", actual, total or actual)
