"""Read-only v3 API catalog adapters for Sonarr and Radarr."""

from __future__ import annotations

import logging
import random
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path, PureWindowsPath

import httpx

from .config import ArrConnection

log = logging.getLogger("crowbarr")


class CatalogCancelled(RuntimeError):
    """Discovery stopped without authorizing a partial catalog replacement."""


@dataclass(frozen=True)
class ManagedFile:
    provider: str
    file_id: int
    item_id: int
    path: str
    remote_path: str
    title: str
    season: int | None = None
    episodes: list[int] = field(default_factory=list)
    episode_title: str = ""
    audio_languages: list[str] = field(default_factory=list)
    poster: bool = False
    year: int | None = None

    def record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CatalogItem:
    """An authoritative item snapshot, never a placeholder for a failed request.

    An unbound client has no full discovery fingerprint. Coordinators must supply
    and compare that fingerprint before using a snapshot to authorize work.
    """

    provider: str
    item_id: int
    discovery_fingerprint: str | None
    files: tuple[ManagedFile, ...]
    outcome: str = "complete"


def map_path(remote: str, connection: ArrConnection) -> Path:
    normalized = remote.replace("\\", "/")
    if ".." in normalized.split("/"):
        raise ValueError("Remote media path contains parent traversal")
    windows = bool(PureWindowsPath(remote).drive)
    comparison = normalized.casefold() if windows else normalized
    for mapping in sorted(connection.mappings, key=lambda m: len(m.remote), reverse=True):
        prefix = mapping.remote.casefold() if windows else mapping.remote
        boundary = prefix.rstrip("/") + "/"
        if comparison.rstrip("/") == prefix.rstrip("/"):
            return Path(mapping.local).resolve()
        if comparison.startswith(boundary):
            relative = normalized[len(boundary) :]
            result = (Path(mapping.local) / relative).resolve()
            if not result.is_relative_to(Path(mapping.local).resolve()):
                raise ValueError("Mapped media escapes its configured directory")
            return result
    if windows:
        raise ValueError("Windows media paths need a path mapping")
    if not Path(remote).is_absolute():
        raise ValueError("API returned a relative media path without a library directory")
    return Path(remote).resolve()


def _remote_path(item: dict, file: dict) -> str:
    if file.get("path"):
        return file["path"]
    if item.get("path") and file.get("relativePath"):
        return item["path"].replace("\\", "/").rstrip("/") + "/" + file["relativePath"].replace("\\", "/")
    raise ValueError("Imported media has no file path in the API response")


def _episode_groups(episodes, monitored_only):
    groups, eligible = {}, set()
    for episode in episodes:
        if not isinstance(episode.get("hasFile"), bool):
            raise ValueError("Episode is missing file-presence metadata")
        if monitored_only and episode["hasFile"] and not isinstance(episode.get("monitored"), bool):
            raise ValueError("Episode is missing monitoring metadata")
        file_id = episode.get("episodeFileId")
        if file_id is not None and (not isinstance(file_id, int) or isinstance(file_id, bool) or file_id < 0):
            raise ValueError("Invalid episode file ID")
        if episode["hasFile"] and not file_id:
            raise ValueError("Imported episode has no file ID")
        if file_id:
            groups.setdefault(file_id, []).append(episode)
            if episode.get("hasFile") and (episode.get("monitored") or not monitored_only):
                eligible.add(file_id)
    return groups, eligible


class ArrClient:
    def __init__(self, provider: str, connection: ArrConnection, transport=None, *, workers=4,
                 discovery_fingerprint=None, cancel_event=None, progress=None,
                 retry_wait=None, clock=time.time, jitter=random.random):
        if provider not in {"sonarr", "radarr"}:
            raise ValueError("Unknown arr service")
        if not connection.url or not connection.api_key:
            raise ValueError("Both service URL and API key are required for library sync")
        if not isinstance(workers, int) or isinstance(workers, bool) or not 1 <= workers <= 8:
            raise ValueError("Discovery workers must be between 1 and 8")
        self.provider, self.connection = provider, connection.model_copy(deep=True)
        self.discovery_fingerprint = discovery_fingerprint
        self.workers, self.cancel_event, self.progress = workers, cancel_event, progress
        self._retry_wait, self._clock, self._jitter = retry_wait, clock, jitter
        self._abort, self._closed = threading.Event(), threading.Event()
        self._request_slots = threading.BoundedSemaphore(workers)
        self._iteration_lock, self._metrics_lock = threading.Lock(), threading.Lock()
        self._callback_lock = threading.RLock()
        self._pool = None
        self._metrics = dict(requests=0, attempts=0, completed_items=0, submitted_items=0,
                             pending_items=0, peak_pending_items=0, active_requests=0,
                             peak_active_requests=0, in_flight_items=0, peak_in_flight_items=0)
        self.client = httpx.Client(
            timeout=20,
            follow_redirects=False,
            trust_env=False,
            headers={"X-Api-Key": self.connection.api_key},
            limits=httpx.Limits(max_connections=workers, max_keepalive_connections=workers),
            transport=transport,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self._closed.set()
        self._abort.set()
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=True)
        self.client.close()

    @property
    def metrics(self):
        with self._metrics_lock:
            return {"provider": self.provider, **self._metrics}

    def _count(self, **deltas):
        with self._metrics_lock:
            for key, delta in deltas.items():
                self._metrics[key] += delta
            for key in ("active_requests", "pending_items", "in_flight_items"):
                self._metrics["peak_" + key] = max(self._metrics["peak_" + key], self._metrics[key])
        if self.progress:
            # Observers receive only aggregate copies, never configuration or URLs.
            with self._callback_lock:
                if self.progress is None:
                    return
                try:
                    self.progress(self.metrics)
                except Exception:
                    self.progress = None
                    log.warning("Discovery progress observer failed")

    def _check_cancelled(self):
        if self._closed.is_set() or self._abort.is_set() or (self.cancel_event and self.cancel_event.is_set()):
            raise CatalogCancelled("Library discovery cancelled")

    def _get(self, endpoint, **params):
        self._check_cancelled()
        self._count(requests=1)
        for attempt in range(3):
            response = None
            try:
                response = self._attempt(endpoint, params)
            except httpx.TransportError:
                self._check_cancelled()
                if attempt == 2:
                    raise
            else:
                self._check_cancelled()
                if response.status_code not in {429, 502, 503, 504} or attempt == 2:
                    response.raise_for_status()
                    return response
            delay = self._retry_delay(response, attempt)
            if response is not None:
                response.close()
            self._wait_for_retry(delay)

    def _attempt(self, endpoint, params):
        while not self._request_slots.acquire(timeout=0.1):
            self._check_cancelled()
        try:
            self._check_cancelled()
            self._count(attempts=1, active_requests=1)
            try:
                self._check_cancelled()
                response = self.client.get(self.connection.url + "/api/v3/" + endpoint, params=params)
            finally:
                self._count(active_requests=-1)
        finally:
            self._request_slots.release()
        self._check_cancelled()
        return response

    def _retry_delay(self, response, attempt):
        if response is not None:
            value = response.headers.get("Retry-After", "").strip()
            try:
                if value.isdecimal():
                    delay = int(value)
                else:
                    date = parsedate_to_datetime(value)
                    if date.tzinfo is None:
                        date = date.replace(tzinfo=timezone.utc)
                    delay = date.timestamp() - self._clock()
                return max(1, min(60, delay))
            except (ValueError, TypeError, OverflowError):
                pass
        return 2**attempt + max(0, min(1, self._jitter()))

    def _wait_for_retry(self, delay):
        self._check_cancelled()
        if self._retry_wait is not None:
            self._retry_wait(delay)
        else:
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline:
                self._check_cancelled()
                self._abort.wait(min(0.1, max(0, deadline - time.monotonic())))
        self._check_cancelled()

    def get_list(self, endpoint: str, **params) -> list[dict]:
        response = self._get(endpoint, **params)
        data = response.json()
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise ValueError("Unexpected arr API response; expected a list of records")
        return data

    def event_files(self, payload: dict) -> list[ManagedFile]:
        """Fetch only the imported item; never trust webhook paths or monitoring flags."""
        kind = "series" if self.provider == "sonarr" else "movie"
        item_id = int(payload.get(kind, {}).get("id", 0))
        result = self.catalog_item(item_id)
        if self.provider == "radarr":
            return list(result.files)
        file_id = int(payload.get("episodeFile", {}).get("id", 0))
        return [file for file in result.files if file.file_id == file_id]

    def catalog(self) -> list[ManagedFile]:
        files = sorted((file for item in self.iter_catalog_items() for file in item.files),
                       key=lambda file: (file.provider, file.item_id, file.file_id))
        self._check_cancelled()
        return files

    def iter_catalog_items(self):
        if not self._iteration_lock.acquire(blocking=False):
            raise RuntimeError("Only one catalog iterator may run per client")
        pending, pool = set(), None
        try:
            self._check_cancelled()
            endpoint = "series" if self.provider == "sonarr" else "movie"
            inventory = iter(self.get_list(endpoint))
            seen = set()
            pool = self._pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="crowbarr-arr")

            def fill():
                while len(pending) < 2 * self.workers:
                    self._check_cancelled()
                    item = next(inventory, None)
                    if item is None:
                        break
                    item_id = self._positive_id(item.get("id"))
                    if item_id in seen:
                        raise ValueError("Duplicate manager item ID in inventory")
                    seen.add(item_id)
                    pending.add(pool.submit(self._catalog_task, item))
                    self._count(submitted_items=1, pending_items=1)

            fill()
            while pending:
                self._check_cancelled()
                done, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in done:
                    self._check_cancelled()
                    pending.remove(future)
                    self._count(pending_items=-1)
                    result = future.result()
                    self._check_cancelled()
                    yield result
                fill()
            self._check_cancelled()
        finally:
            self._abort.set()
            if pool is not None:
                pool.shutdown(wait=True, cancel_futures=True)
            self._pool = None
            self._count(pending_items=-len(pending))
            if not self._closed.is_set():
                self._abort.clear()
            self._iteration_lock.release()

    @contextmanager
    def _item_work(self):
        self._check_cancelled()
        self._count(in_flight_items=1)
        try:
            yield
            self._check_cancelled()
            self._count(completed_items=1)
            self._check_cancelled()
        finally:
            self._count(in_flight_items=-1)

    def _catalog_task(self, item):
        with self._item_work():
            return self._catalog_record(item)

    @staticmethod
    def _positive_id(value):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError("Manager resource needs a positive integer ID")
        return value

    def catalog_item(self, item_id: int) -> CatalogItem:
        item_id = self._positive_id(item_id)
        kind = "series" if self.provider == "sonarr" else "movie"
        with self._item_work():
            try:
                response = self._get(f"{kind}/{item_id}")
            except httpx.HTTPStatusError as error:
                if error.response.status_code == 404:
                    return CatalogItem(self.provider, item_id, self.discovery_fingerprint, (), "removed")
                raise
            item = response.json()
            if not isinstance(item, dict) or self._positive_id(item.get("id")) != item_id:
                raise ValueError("Unexpected manager item response")
            return self._catalog_record(item)

    def _catalog_record(self, item: dict) -> CatalogItem:
        item_id = self._positive_id(item.get("id"))
        if self.connection.monitored_only:
            if not isinstance(item.get("monitored"), bool):
                raise ValueError("Manager item is missing monitoring metadata")
            if not item["monitored"]:
                return CatalogItem(self.provider, item_id, self.discovery_fingerprint, ())
        if self.provider == "radarr":
            if not isinstance(item.get("hasFile"), bool):
                raise ValueError("Radarr item is missing file-presence metadata")
            if not item["hasFile"]:
                return CatalogItem(self.provider, item_id, self.discovery_fingerprint, ())
            file = item.get("movieFile")
            if not isinstance(file, dict):
                raise ValueError("Radarr reports an imported movie without movieFile metadata")
            self._positive_id(file.get("id"))
            files = (self._file(item, file),)
        else:
            source_files = self.get_list("episodefile", seriesId=item_id)
            episodes = self.get_list("episode", seriesId=item_id) if source_files else []
            groups, eligible_ids = _episode_groups(episodes, self.connection.monitored_only)
            files, seen = [], set()
            for file in source_files:
                file_id = self._positive_id(file.get("id"))
                if file_id in seen or (self.connection.monitored_only and file_id not in eligible_ids):
                    continue
                seen.add(file_id)
                files.append(self._file(item, file, groups.get(file_id, [])))
            files = tuple(files)
        return CatalogItem(self.provider, item_id, self.discovery_fingerprint, files)

    def _file(self, item: dict, file: dict, episodes: list[dict] | None = None) -> ManagedFile:
        from .catalog import language_codes

        remote = _remote_path(item, file)
        matched = sorted(episodes or [], key=lambda e: e.get("episodeNumber", 0))
        info = file.get("mediaInfo") or {}
        return ManagedFile(
            self.provider,
            int(file["id"]),
            int(item["id"]),
            str(map_path(remote, self.connection)),
            remote,
            item.get("title", ""),
            matched[0].get("seasonNumber") if matched else file.get("seasonNumber"),
            [e["episodeNumber"] for e in matched if "episodeNumber" in e],
            " / ".join(e.get("title", "") for e in matched),
            language_codes(info.get("audioLanguages") or info.get("audioLanguage") or []),
            any(i.get("coverType") == "poster" for i in item.get("images", [])),
            item.get("year"),
        )
