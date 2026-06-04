"""Unit tests for the shared addon cache (camoufox.addons).

Regression coverage for the cache-corruption bug: a partially-extracted addon
dir (created before extraction finished, or left by a failed extraction) used to
be trusted forever — `os.path.exists(dir)` was true, so every subsequent launch
skipped re-extraction and then failed `confirm_paths` with "manifest.json is
missing". These tests mock the download so they run offline.
"""

import os
import threading
import time
from typing import List
from unittest import mock

import pytest

import camoufox.addons as addons
from camoufox.addons import DefaultAddons, maybe_download_addons
from camoufox.exceptions import InvalidAddonPath


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Point the shared addon cache at a throwaway dir."""
    monkeypatch.setattr(addons, "ADDONS_DIR", tmp_path / "addons")
    return tmp_path / "addons"


def _fake_extract_ok(url: str, extract_path: str, name: str) -> None:
    """Stand-in for download_and_extract that writes a valid manifest.json."""
    os.makedirs(extract_path, exist_ok=True)
    with open(os.path.join(extract_path, "manifest.json"), "w") as fh:
        fh.write('{"name": "%s"}' % name)


def _fake_extract_empty(url: str, extract_path: str, name: str) -> None:
    """Stand-in that 'succeeds' but produces no manifest.json (corrupt zip)."""
    os.makedirs(extract_path, exist_ok=True)


def test_fresh_extraction_populates_cache(cache_dir):
    collected: List[str] = []
    with mock.patch.object(addons, "download_and_extract", _fake_extract_ok):
        maybe_download_addons([DefaultAddons.UBO], collected)

    ubo = str(cache_dir / "UBO")
    assert collected == [ubo]
    assert os.path.isfile(os.path.join(ubo, "manifest.json"))


def test_complete_cache_is_reused_without_redownload(cache_dir):
    _fake_extract_ok("", str(cache_dir / "UBO"), "UBO")

    with mock.patch.object(addons, "download_and_extract") as dl:
        collected: List[str] = []
        maybe_download_addons([DefaultAddons.UBO], collected)

    dl.assert_not_called()  # already complete → no download
    assert collected == [str(cache_dir / "UBO")]


def test_partial_dir_is_repaired_not_trusted(cache_dir):
    """The core regression: an empty (manifest-less) cache dir must be re-extracted."""
    ubo = cache_dir / "UBO"
    ubo.mkdir(parents=True)  # the poisoned partial dir — exists but no manifest

    with mock.patch.object(addons, "download_and_extract", side_effect=_fake_extract_ok) as dl:
        collected: List[str] = []
        maybe_download_addons([DefaultAddons.UBO], collected)

    assert dl.called  # did NOT trust the partial dir
    assert os.path.isfile(os.path.join(str(ubo), "manifest.json"))


def test_failed_extraction_raises_and_leaves_no_live_dir(cache_dir):
    """A download that yields no manifest must surface loudly, not be swallowed,
    and must not leave a poisoned live dir for the next launch."""
    with mock.patch.object(addons, "download_and_extract", _fake_extract_empty):
        with pytest.raises(InvalidAddonPath):
            maybe_download_addons([DefaultAddons.UBO], [])

    # No half-populated live dir left behind.
    assert not (cache_dir / "UBO").exists()


def test_concurrent_extraction_is_safe(cache_dir):
    """Many threads extracting at once converge on one complete dir; the old
    decorative per-call lock let them race a half-extracted dir."""
    barrier = threading.Barrier(8)
    errors: List[BaseException] = []

    def slow_extract(url: str, extract_path: str, name: str) -> None:
        time.sleep(0.02)  # widen the race window
        _fake_extract_ok(url, extract_path, name)

    def worker() -> None:
        try:
            barrier.wait()
            maybe_download_addons([DefaultAddons.UBO], [])
        except BaseException as e:  # noqa: BLE001 — test asserts none escaped
            errors.append(e)

    with mock.patch.object(addons, "download_and_extract", slow_extract):
        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert errors == []
    assert os.path.isfile(os.path.join(str(cache_dir / "UBO"), "manifest.json"))
