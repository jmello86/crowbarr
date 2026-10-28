"""Read-only discovery completeness, bounded work, and request lifecycle."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from email.utils import formatdate

import httpx
import pytest

from crowbarr.arr import ArrClient, CatalogCancelled
from crowbarr.config import ArrConnection, ConfigStore, Settings
from crowbarr.db import Database
from crowbarr.library import scan_arr


def connection(**values):
    return ArrConnection(url="http://arr", api_key="private", **values)


def test_episode_association_visits_the_list_once(monkeypatch):
    class Episodes(list):
        visited = 0

        def __iter__(self):
            for item in super().__iter__():
                self.visited += 1
                yield item

    episodes = Episodes([
        dict(episodeFileId=i, hasFile=True, monitored=True, seasonNumber=1,
             episodeNumber=3 * i + j, title=f"Episode {3 * i + j}")
        for i in range(1, 1001) for j in (3, 2, 1)
    ])
    routes = {
        "series": [dict(id=1, title="Show", path="/tv/Show", monitored=True)],
        "episodefile": [dict(id=i, path=f"/tv/Show/{i}.mkv") for i in range(1, 1001)],
        "episode": episodes,
    }
    with ArrClient("sonarr", connection(), transport=httpx.MockTransport(lambda _: None)) as adapter:
        monkeypatch.setattr(adapter, "get_list", lambda endpoint, **_: routes[endpoint])
        files = adapter.catalog()
    assert len(files) == 1000
    assert files[0].episodes == [4, 5, 6]
    assert files[0].episode_title == "Episode 4 / Episode 5 / Episode 6"
    assert episodes.visited == 3000


@pytest.mark.parametrize("status,outcome", [(200, "complete"), (404, "removed")])
def test_targeted_item_distinguishes_empty_and_removed(status, outcome):
    def respond(request):
        assert request.url.path == "/api/v3/movie/1"
        return httpx.Response(status, json={"id": 1, "monitored": True, "hasFile": False})

    with ArrClient("radarr", connection(), transport=httpx.MockTransport(respond)) as adapter:
        item = adapter.catalog_item(1)
    assert item.provider == "radarr"
    assert item.item_id == 1
    assert item.outcome == outcome
    assert item.files == ()


def series(item_id):
    return dict(id=item_id, title=f"Show {item_id}", path=f"/tv/Show {item_id}", monitored=True)


def sonarr_payload(request, count=16):
    assert request.method == "GET"
    assert request.headers["X-Api-Key"] == "private"
    endpoint = request.url.path.removeprefix("/api/v3/")
    if endpoint == "series":
        return [series(i) for i in range(count, 0, -1)]
    if endpoint.startswith("series/"):
        return series(int(endpoint.split("/")[1]))
    item_id = int(request.url.params["seriesId"])
    if endpoint == "episodefile":
        return [dict(id=item_id * 10, relativePath="episode.mkv", mediaInfo={"audioLanguages": "English"})]
    if endpoint == "episode":
        return [dict(episodeFileId=item_id * 10, hasFile=True, monitored=True,
                     seasonNumber=1, episodeNumber=1, title="Episode 1")]
    raise AssertionError(endpoint)


class ClosingTransport(httpx.MockTransport):
    closed = False

    def close(self):
        self.closed = True
        super().close()


@pytest.mark.parametrize("workers", [1, 4, 8])
def test_requests_overlap_with_bounded_pool_and_preserve_catalog(workers):
    barrier = threading.Barrier(workers)
    lock = threading.Lock()
    active = peak = 0
    calls = []

    def handler(request):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            calls.append(request.url.path)
        try:
            if request.url.path.endswith("/episodefile"):
                barrier.wait(timeout=5)
            return httpx.Response(200, json=sonarr_payload(request))
        finally:
            with lock:
                active -= 1

    transport = ClosingTransport(handler)
    with ArrClient("sonarr", connection(), transport, workers=workers,
                   discovery_fingerprint="snapshot") as adapter:
        files = adapter.catalog()
        metrics = adapter.metrics
    assert len(files) == 16
    assert [file.item_id for file in files] == list(range(1, 17))
    assert all(file.episodes == [1] and file.audio_languages == ["en"] for file in files)
    assert len(calls) == 33
    assert peak == workers
    assert metrics["peak_active_requests"] == workers
    assert metrics["peak_pending_items"] <= 2 * workers
    assert metrics["peak_in_flight_items"] <= workers
    assert metrics["requests"] == metrics["attempts"] == 33
    assert metrics["completed_items"] == 16
    assert metrics["pending_items"] == metrics["active_requests"] == metrics["in_flight_items"] == 0
    assert transport.closed and adapter.client.is_closed


@pytest.mark.parametrize("workers", [1, 4, 8])
def test_cancellation_stops_bounded_submission_and_closes_requests(workers):
    cancel, release, full = threading.Event(), threading.Event(), threading.Event()

    def observe(snapshot):
        if snapshot["pending_items"] == 2 * workers:
            full.set()

    def handler(request):
        if request.url.path.endswith("/episodefile"):
            assert release.wait(timeout=5)
        return httpx.Response(200, json=sonarr_payload(request, count=100))

    transport = ClosingTransport(handler)
    with ArrClient("sonarr", connection(), transport, workers=workers,
                   cancel_event=cancel, progress=observe) as adapter, ThreadPoolExecutor(1) as owner:
        future = owner.submit(adapter.catalog)
        try:
            assert full.wait(timeout=5)
            assert adapter.metrics["submitted_items"] == 2 * workers
            cancel.set()
        finally:
            release.set()
        with pytest.raises(CatalogCancelled):
            future.result(timeout=5)
        assert adapter.metrics["submitted_items"] == 2 * workers
        assert adapter.metrics["pending_items"] == adapter.metrics["active_requests"] == 0
    assert transport.closed


def test_early_iterator_close_joins_workers_and_allows_client_reuse():
    transport = ClosingTransport(lambda r: httpx.Response(200, json=sonarr_payload(r, count=100)))
    with ArrClient("sonarr", connection(), transport) as adapter:
        iterator = adapter.iter_catalog_items()
        next(iterator)
        iterator.close()
        assert adapter.metrics["submitted_items"] <= 8
        assert adapter.metrics["pending_items"] == adapter.metrics["in_flight_items"] == 0
        assert adapter.catalog_item(1).item_id == 1
    assert transport.closed


def test_context_closes_an_unexhausted_iterator():
    transport = ClosingTransport(lambda r: httpx.Response(200, json=sonarr_payload(r, count=100)))
    with ArrClient("sonarr", connection(), transport) as adapter:
        iterator = adapter.iter_catalog_items()
        next(iterator)
    assert transport.closed
    assert adapter.metrics["active_requests"] == 0
    with pytest.raises(CatalogCancelled):
        next(iterator)
    iterator.close()


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_retryable_status_gets_three_attempts_then_succeeds(status):
    attempts, sleeps = [], []

    def handler(request):
        attempts.append(request.method)
        return httpx.Response(status if len(attempts) < 3 else 200, json=[])

    with ArrClient("sonarr", connection(), httpx.MockTransport(handler),
                   retry_wait=sleeps.append, jitter=lambda: 0) as adapter:
        assert adapter.get_list("series") == []
        assert adapter.metrics["requests"] == 1
        assert adapter.metrics["attempts"] == 3
    assert attempts == ["GET"] * 3
    assert sleeps == [1, 2]


@pytest.mark.parametrize("status", [401, 403, 404, 500, 301])
def test_nonretryable_status_fails_once(status):
    attempts, sleeps = [], []

    def handler(request):
        attempts.append(request.method)
        return httpx.Response(status, json=[])

    with ArrClient("sonarr", connection(), httpx.MockTransport(handler), retry_wait=sleeps.append) as adapter:
        with pytest.raises(httpx.HTTPStatusError):
            adapter.get_list("series")
        assert adapter.metrics["attempts"] == 1
    assert attempts == ["GET"]
    assert sleeps == []


@pytest.mark.parametrize("error", [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError])
def test_transport_failures_stop_at_three_attempts(error):
    sleeps = []

    def handler(request):
        raise error("private remote detail", request=request)

    with ArrClient("sonarr", connection(), httpx.MockTransport(handler),
                   retry_wait=sleeps.append, jitter=lambda: 0) as adapter:
        with pytest.raises(error):
            adapter.get_list("series")
        assert adapter.metrics["attempts"] == 3
    assert sleeps == [1, 2]


@pytest.mark.parametrize("header,expected", [
    ("0", 1), ("4", 4), ("9000", 60), ("invalid", 1), ("-5", 1),
    (formatdate(1700000005, usegmt=True), 5), (formatdate(1700000090, usegmt=True), 60),
    (formatdate(1699999990, usegmt=True), 1),
])
def test_retry_after_is_bounded_and_uses_injected_clock(header, expected):
    calls, sleeps = [], []

    def handler(request):
        calls.append(1)
        return httpx.Response(429 if len(calls) == 1 else 200, json=[], headers={"Retry-After": header})

    with ArrClient("sonarr", connection(), httpx.MockTransport(handler), retry_wait=sleeps.append,
                   clock=lambda: 1700000000, jitter=lambda: 0) as adapter:
        assert adapter.get_list("series") == []
    assert sleeps == [expected]


def test_cancellation_during_backoff_stops_the_next_attempt():
    cancel, attempts = threading.Event(), []

    def handler(request):
        attempts.append(1)
        return httpx.Response(503)

    with ArrClient("sonarr", connection(), httpx.MockTransport(handler), cancel_event=cancel,
                   retry_wait=lambda _: cancel.set()) as adapter:
        with pytest.raises(CatalogCancelled):
            adapter.get_list("series")
    assert attempts == [1]


def test_default_backoff_observes_external_cancellation(monkeypatch):
    cancel = threading.Event()
    with ArrClient("sonarr", connection(), httpx.MockTransport(lambda _: None), cancel_event=cancel) as adapter:
        monkeypatch.setattr(adapter._abort, "wait", lambda _: cancel.set())
        with pytest.raises(CatalogCancelled):
            adapter._wait_for_retry(60)


@pytest.mark.parametrize("data", [{}, [1], "not a list"])
def test_invalid_list_shapes_are_not_retried(data):
    with ArrClient("sonarr", connection(), httpx.MockTransport(lambda _: httpx.Response(200, json=data))) as adapter:
        with pytest.raises(ValueError):
            adapter.get_list("series")
        assert adapter.metrics["attempts"] == 1


def test_invalid_json_is_not_retried():
    with ArrClient("sonarr", connection(), httpx.MockTransport(lambda _: httpx.Response(200, text="broken"))) as adapter:
        with pytest.raises(ValueError):
            adapter.get_list("series")
        assert adapter.metrics["attempts"] == 1


@pytest.mark.parametrize("item", [
    {"id": 2, "monitored": True, "hasFile": False},
    {"id": 1, "hasFile": False},
    {"id": 1, "monitored": True},
    {"id": 1, "monitored": True, "hasFile": True},
    [],
])
def test_invalid_target_metadata_is_not_an_empty_success(item):
    with ArrClient("radarr", connection(), httpx.MockTransport(lambda _: httpx.Response(200, json=item))) as adapter:
        with pytest.raises(ValueError):
            adapter.catalog_item(1)
        assert adapter.metrics["attempts"] == 1
        assert adapter.metrics["completed_items"] == 0


def test_snapshot_and_targeted_request_counts_and_event_filter():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=sonarr_payload(request, count=2))

    original = connection()
    with ArrClient("sonarr", original, httpx.MockTransport(handler), discovery_fingerprint="snapshot") as adapter:
        original.monitored_only = False
        original.url = "http://changed"
        items = list(adapter.iter_catalog_items())
        assert len(calls) == 5
        assert all(item.discovery_fingerprint == "snapshot" and item.outcome == "complete" for item in items)
        assert not any(path.startswith("/api/v3/series/") for path in calls)
        calls.clear()
        assert len(adapter.event_files({"series": {"id": 1}, "episodeFile": {"id": 10, "path": "/forged"}})) == 1
        assert calls == ["/api/v3/series/1", "/api/v3/episodefile", "/api/v3/episode"]
        assert adapter.event_files({"series": {"id": 1}, "episodeFile": {"id": 999}}) == []
        assert adapter.connection.monitored_only is True
        assert adapter.connection.url == "http://arr"


def test_unmonitored_and_empty_items_are_complete_not_removed():
    for item in ({"id": 1, "monitored": False}, {"id": 1, "monitored": True, "hasFile": False}):
        with ArrClient("radarr", connection(), httpx.MockTransport(
                lambda _, payload=item: httpx.Response(200, json=payload))) as adapter:
            result = adapter.catalog_item(1)
            assert result.files == () and result.outcome == "complete"


def test_metrics_callback_is_aggregate_and_cannot_mutate_counters():
    snapshots = []

    def observer(snapshot):
        snapshots.append(dict(snapshot))
        snapshot["attempts"] = -999

    with ArrClient("sonarr", connection(), httpx.MockTransport(
            lambda r: httpx.Response(200, json=sonarr_payload(r, count=2))), progress=observer) as adapter:
        assert len(adapter.catalog()) == 2
        assert adapter.metrics["attempts"] == 5
    assert "private" not in json.dumps(snapshots)
    assert "/tv" not in json.dumps(snapshots)
    assert all(isinstance(value, int) for snapshot in snapshots for key, value in snapshot.items() if key != "provider")


def test_broken_progress_observer_is_disabled_without_leaking_exception(caplog):
    def broken(_):
        raise RuntimeError("private secret in observer")

    with ArrClient("radarr", connection(), httpx.MockTransport(lambda _: httpx.Response(200, json=[])),
                   progress=broken) as adapter:
        assert adapter.catalog() == []
    assert "private secret" not in caplog.text
    assert caplog.text.count("Discovery progress observer failed") == 1


@pytest.mark.parametrize("workers", [0, 9, True, "4", 1.5])
def test_workers_validation(workers):
    with pytest.raises(ValueError):
        Settings(sync_request_workers=workers)
    with pytest.raises(ValueError):
        ArrClient("sonarr", connection(), workers=workers)


def test_worker_setting_defaults_roundtrips_and_leaves_fingerprints_unchanged(tmp_path):
    store = ConfigStore(tmp_path)
    before = store.get()
    assert before.sync_request_workers == 4
    after = Settings.model_validate({**before.model_dump(), "sync_request_workers": 8})
    assert after.fingerprint() == before.fingerprint()
    assert after.discovery_fingerprint() == before.discovery_fingerprint()
    store.save(after)
    assert ConfigStore(tmp_path).get().sync_request_workers == 8


@pytest.mark.parametrize("failure", [401, 404, 429, 503, "timeout", "json", "shape"])
def test_failed_full_discovery_preserves_preexisting_catalog_and_queue(tmp_path, failure):
    db = Database(tmp_path / "queue.db")
    old = tmp_path / "old.mkv"
    old.write_bytes(b"media")
    db.replace_catalog("sonarr", [dict(file_id=9999, item_id=999, path=str(old),
                                      remote_path=str(old), title="Old")])
    job_id = db.enqueue(str(old), "old", None, 0)
    settings = Settings(roots=[str(tmp_path)], sonarr=connection(), sync_request_workers=4)
    clients = []

    def handler(request):
        if request.url.path.endswith("episodefile") and request.url.params["seriesId"] == "2":
            if failure == "timeout":
                raise httpx.ReadTimeout("offline", request=request)
            if failure == "json":
                return httpx.Response(200, text="invalid JSON")
            if failure == "shape":
                return httpx.Response(200, json={"files": []})
            return httpx.Response(failure)
        return httpx.Response(200, json=sonarr_payload(request, count=3))

    def factory(provider, config, **kwargs):
        assert kwargs["workers"] == settings.sync_request_workers
        assert kwargs["discovery_fingerprint"] == settings.discovery_fingerprint()
        adapter = ArrClient(provider, config, httpx.MockTransport(handler),
                            retry_wait=lambda _: None, jitter=lambda: 0, **kwargs)
        clients.append(adapter)
        return adapter

    assert scan_arr(settings, db, factory) == 0
    with db.connect() as c:
        assert [r[0] for r in c.execute("SELECT path FROM managed_media")] == [str(old)]
        assert c.execute("SELECT healthy FROM provider_sync WHERE provider='sonarr'").fetchone()[0] == 0
    assert db.get(job_id)["state"] == "queued"
    assert db.get(job_id)["signature"] == "old"
    assert clients[0].client.is_closed
    assert clients[0].metrics["active_requests"] == clients[0].metrics["in_flight_items"] == 0


def test_worker_setting_api_change_preserves_settled_jobs(tmp_path):
    from fastapi.testclient import TestClient

    from crowbarr.app import create_app

    app = create_app(tmp_path / "config", background=False)
    job_id = app.state.db.enqueue("/tv/settled.mkv", "settled", None, 0)
    app.state.db.update(job_id, state="unchanged")
    with TestClient(app, headers={"X-Api-Key": app.state.store.token}) as client:
        assert client.get("/api/settings").json()["sync_request_workers"] == 4
        response = client.put("/api/settings", json={"sync_request_workers": 8})
        assert response.status_code == 200
        assert response.json()["sync_request_workers"] == 8
        assert client.put("/api/settings", json={"sync_request_workers": 9}).status_code == 422
    assert app.state.db.get(job_id)["state"] == "unchanged"
    assert app.state.db.get(job_id)["signature"] == "settled"


@pytest.mark.parametrize("workers", [1, 4, 8])
def test_generated_100_series_latency_comparison(workers):
    # Timings are reported, never a flaky wall-clock CI gate. The barrier tests
    # above are the deterministic proof of actual request overlap and bounds.
    def handler(request):
        time.sleep(0.005)
        return httpx.Response(200, json=sonarr_payload(request, count=100))

    started = time.monotonic()
    with ArrClient("sonarr", connection(), httpx.MockTransport(handler), workers=workers) as adapter:
        files = adapter.catalog()
        elapsed = time.monotonic() - started
        metrics = adapter.metrics
    assert len(files) == 100
    assert [file.item_id for file in files] == list(range(1, 101))
    assert metrics["requests"] == metrics["attempts"] == 201
    assert metrics["completed_items"] == metrics["submitted_items"] == 100
    assert metrics["peak_pending_items"] <= 2 * workers
    assert metrics["peak_active_requests"] <= workers
    print(f"100-series/5ms fixture: workers={workers}, requests=201, elapsed={elapsed:.3f}s, "
          f"peak_requests={metrics['peak_active_requests']}, peak_pending={metrics['peak_pending_items']}")


def test_catalog_item_monitored_policy_and_episode_metadata_match_serial_catalog():
    def handler(request):
        data = sonarr_payload(request, count=1)
        if request.url.path.endswith("episode"):
            data = [dict(episodeFileId=10, hasFile=True, monitored=False,
                         seasonNumber=1, episodeNumber=1, title="Unmonitored")]
        return httpx.Response(200, json=data)

    with ArrClient("sonarr", connection(), httpx.MockTransport(handler)) as adapter:
        assert adapter.catalog() == []
        assert adapter.catalog_item(1).files == ()
        assert adapter.event_files({"series": {"id": 1}, "episodeFile": {"id": 10}}) == []
    with ArrClient("sonarr", connection(monitored_only=False), httpx.MockTransport(handler)) as adapter:
        assert list(adapter.catalog_item(1).files) == adapter.catalog()
        assert len(adapter.catalog()) == 1


def test_cancelled_before_discovery_does_not_make_a_request():
    cancel = threading.Event()
    cancel.set()
    with ArrClient("sonarr", connection(), httpx.MockTransport(lambda _: pytest.fail("request after cancel")),
                   cancel_event=cancel) as adapter:
        with pytest.raises(CatalogCancelled):
            adapter.catalog()
        assert adapter.metrics["attempts"] == 0


def test_duplicate_inventory_ids_fail_instead_of_replacing_catalog():
    def handler(request):
        if request.url.path.endswith("/series"):
            return httpx.Response(200, json=[series(1), series(1)])
        return httpx.Response(200, json=sonarr_payload(request, count=1))

    transport = ClosingTransport(handler)
    with ArrClient("sonarr", connection(), transport) as adapter, pytest.raises(ValueError, match="Duplicate"):
        adapter.catalog()
    assert transport.closed


def test_observer_cancellation_prevents_request_start():
    cancel = threading.Event()

    def observer(snapshot):
        if snapshot["active_requests"]:
            cancel.set()

    with ArrClient("sonarr", connection(), httpx.MockTransport(lambda _: pytest.fail("request after cancel")),
                   cancel_event=cancel, progress=observer) as adapter, pytest.raises(CatalogCancelled):
        adapter.catalog()


def test_serial_and_concurrent_catalogs_are_identical():
    catalogs = []
    for workers in (1, 4, 8):
        with ArrClient("sonarr", connection(), httpx.MockTransport(
                lambda r: httpx.Response(200, json=sonarr_payload(r, count=16))), workers=workers) as adapter:
            catalogs.append([file.record() for file in adapter.catalog()])
    assert catalogs[0] == catalogs[1] == catalogs[2]


@pytest.mark.parametrize("episode", [{"hasFile": True}, {"episodeFileId": 10, "hasFile": True},
                                     {"episodeFileId": 10, "monitored": True},
                                     {"episodeFileId": "10", "hasFile": True, "monitored": True}])
def test_missing_episode_metadata_is_not_an_empty_catalog(episode):
    def handler(request):
        data = [episode] if request.url.path.endswith("/episode") else sonarr_payload(request, count=1)
        return httpx.Response(200, json=data)

    with ArrClient("sonarr", connection(), httpx.MockTransport(handler)) as adapter, pytest.raises(ValueError):
        adapter.catalog()
