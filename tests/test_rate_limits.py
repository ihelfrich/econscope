"""Rate-limit handling: Retry-After parsing, cooldown, rolling quotas.

These exist because the CourtListener adapter shipped with a documented limit
of 5,000 requests/hour when the real published limit is 5/min, 50/hour and
125/day — and because the shared HTTP layer clamped the server's own
Retry-After to max_backoff (60s), guaranteeing we came back early every time
and stayed throttled.
"""
from __future__ import annotations

import email.utils
import time
import urllib.error

import pytest

from econscope.adapters import base as basemod
from econscope.adapters.base import BaseAdapter, QuotaExhausted
from econscope.intel import http as H


# ── Retry-After parsing ──────────────────────────────────────────────────────

def test_retry_after_delta_seconds():
    assert H._parse_retry_after("120") == pytest.approx(120.0)


def test_retry_after_http_date():
    when = email.utils.formatdate(time.time() + 300, usegmt=True)
    got = H._parse_retry_after(when)
    assert got is not None and 240 < got < 360, got


def test_retry_after_garbage_is_none():
    assert H._parse_retry_after("soon") is None
    assert H._parse_retry_after(None) is None


def test_retry_after_in_the_past_is_zero_not_negative():
    when = email.utils.formatdate(time.time() - 300, usegmt=True)
    assert H._parse_retry_after(when) == 0.0


# ── The actual bug: long Retry-After must not be slept through ──────────────

def _raise_429(retry_after: str):
    def _fake(req, timeout=None, context=None):
        raise urllib.error.HTTPError(
            req.full_url, 429, "Too Many Requests",
            {"Retry-After": retry_after}, None,
        )
    return _fake


def test_long_retry_after_raises_instead_of_sleeping(monkeypatch):
    url = "https://example.test/api"
    H.clear_cooldown(url)
    monkeypatch.setattr(H.urllib.request, "urlopen", _raise_429("4201"))
    slept = []
    monkeypatch.setattr(H.time, "sleep", lambda s: slept.append(s))

    started = time.monotonic()
    with pytest.raises(H.RateLimitedError) as ei:
        H.fetch(url, max_retries=5)

    assert ei.value.retry_after == pytest.approx(4201.0)
    assert not slept, f"should not have slept at all, slept {slept}"
    assert time.monotonic() - started < 1.0


def test_short_retry_after_is_honored_in_full_not_clamped(monkeypatch):
    """A 90s Retry-After must not be clamped to max_backoff=60."""
    url = "https://example.test/api2"
    H.clear_cooldown(url)
    monkeypatch.setattr(H.urllib.request, "urlopen", _raise_429("90"))
    slept = []
    monkeypatch.setattr(H.time, "sleep", lambda s: slept.append(s))

    with pytest.raises((H.RetryableHTTPError, H.RateLimitedError)):
        H.fetch(url, max_retries=2, max_backoff=60.0,
                max_retry_after_sleep=120.0)

    assert slept, "expected at least one sleep"
    assert max(slept) >= 90.0, f"Retry-After was clamped: {slept}"


def test_cooldown_short_circuits_next_call(monkeypatch):
    url = "https://cooling.test/api"
    H.clear_cooldown(url)
    H.note_rate_limited(url, 600)
    called = []
    monkeypatch.setattr(H.urllib.request, "urlopen",
                        lambda *a, **k: called.append(1))
    with pytest.raises(H.RateLimitedError):
        H.fetch(url)
    assert not called, "should not have hit the network while cooling down"
    H.clear_cooldown(url)


# ── Rolling-window quotas ────────────────────────────────────────────────────

class _Dummy(BaseAdapter):
    source_id = "dummy_quota_test"
    source_name = "Dummy"
    requests_per_minute = 0          # spacing off; test the windows alone
    rate_limits = [(3, 60)]
    max_quota_wait = 0.01

    def pull_series(self, *a, **k): ...
    def search(self, *a, **k): ...
    def get_metadata(self, *a, **k): ...


@pytest.fixture(autouse=True)
def _clean_quota(tmp_path, monkeypatch):
    monkeypatch.setattr(basemod, "_QUOTA_DIR", tmp_path / "rl")
    basemod._WINDOWS.pop("dummy_quota_test", None)
    yield
    basemod._WINDOWS.pop("dummy_quota_test", None)


def test_quota_admits_up_to_limit_then_raises():
    d = _Dummy()
    for _ in range(3):
        d._check_quota()
    with pytest.raises(QuotaExhausted) as ei:
        d._check_quota()
    assert ei.value.window == "3/60s"
    assert ei.value.retry_after > 0


def test_quota_persists_across_instances():
    _Dummy()._check_quota()
    _Dummy()._check_quota()
    basemod._WINDOWS.pop("dummy_quota_test", None)   # simulate a restart
    d = _Dummy()
    d._check_quota()
    with pytest.raises(QuotaExhausted):
        d._check_quota()


def test_status_reports_usage():
    d = _Dummy()
    d._check_quota()
    st = d.rate_limit_status()
    assert st["quotas"][0]["used"] == 1
    assert st["quotas"][0]["limit"] == 3


# ── Adaptive spacing ─────────────────────────────────────────────────────────

class _Spaced(_Dummy):
    source_id = "dummy_spacing_test"
    requests_per_minute = 60
    rate_limits = []


def test_interval_widens_on_rate_limit_and_decays_on_success(monkeypatch):
    s = _Spaced()
    basemod._INTERVAL_MULT.pop("dummy_spacing_test", None)
    start = s.current_interval()

    monkeypatch.setattr(basemod, "fetch",
                        lambda *a, **k: (_ for _ in ()).throw(
                            H.RateLimitedError("u", 10)))
    monkeypatch.setattr(basemod.time, "sleep", lambda s: None)
    with pytest.raises(H.RateLimitedError):
        s._fetch("https://x.test")
    widened = s.current_interval()
    assert widened > start, (start, widened)

    monkeypatch.setattr(basemod, "fetch", lambda *a, **k: object())
    for _ in range(5):
        s._fetch("https://x.test")
    assert s.current_interval() < widened
    basemod._INTERVAL_MULT.pop("dummy_spacing_test", None)
