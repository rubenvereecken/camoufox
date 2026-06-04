import os
import shutil
import tempfile
from enum import Enum
from threading import Lock
from typing import List, Optional

from .exceptions import InvalidAddonPath
from .pkgman import INSTALL_DIR, unzip, webdl

# Addons are stored in a shared folder, not per-browser version
ADDONS_DIR = INSTALL_DIR / "addons"

# Serialises extraction across concurrent launches in one process. The old code
# did `with Lock():` where Lock was a freshly-constructed multiprocessing.Lock
# per call — a new instance guards nothing, so it serialised nothing. A
# module-level threading.Lock actually guards the check-then-extract sequence
# (maybe_download_addons runs in a thread-pool executor, so threads are the unit
# of concurrency here). It's an optimisation, not a correctness crutch: the
# atomic temp-dir swap below makes concurrent extraction safe even without it.
_extract_lock = Lock()


class DefaultAddons(Enum):
    """
    Default addons to be downloaded
    """

    UBO = "https://addons.mozilla.org/firefox/downloads/latest/ublock-origin/latest.xpi"


def confirm_paths(paths: List[str]) -> None:
    """
    Confirms that the addon paths are valid
    """
    for path in paths:
        if not os.path.isdir(path):
            raise InvalidAddonPath(path)
        if not os.path.exists(os.path.join(path, 'manifest.json')):
            raise InvalidAddonPath(
                'manifest.json is missing. Addon path must be a path to an extracted addon.'
            )


def add_default_addons(
    addons_list: List[str], exclude_list: Optional[List[DefaultAddons]] = None
) -> None:
    """
    Adds default addons, minus any specified in exclude_list, to addons_list
    """
    # Build a dictionary from DefaultAddons, excluding keys found in exclude_list
    if exclude_list is None:
        exclude_list = []

    addons = [addon for addon in DefaultAddons if addon not in exclude_list]
    maybe_download_addons(addons, addons_list)


def ensure_default_addons(exclude_list: Optional[List[DefaultAddons]] = None) -> None:
    """
    Pre-populate the shared addon cache without collecting the paths.

    Call once at process startup, before launching browsers concurrently, so the
    one-time download/extraction happens off the critical path and every launch
    finds a complete cache instead of racing the extraction.
    """
    add_default_addons([], exclude_list)


def download_and_extract(url: str, extract_path: str, name: str) -> None:
    """
    Downloads and extracts an addon from a given URL to a specified path
    """
    # Create a temporary file to store the downloaded zip
    buffer = webdl(url, desc=f"Downloading addon ({name})", bar=False)
    unzip(buffer, extract_path, f"Extracting addon ({name})", bar=False)


def _is_extracted(addon_path: str) -> bool:
    """An addon counts as extracted only if it actually holds a manifest.json.

    A bare directory (an interrupted/failed extraction) is treated as absent so
    it gets re-extracted, rather than trusted forever. The old code checked only
    `os.path.exists(addon_path)` on the directory — so a half-extracted dir, once
    created, made every subsequent launch fail `confirm_paths` with
    "manifest.json is missing" until someone manually cleared it.
    """
    return os.path.isfile(os.path.join(addon_path, 'manifest.json'))


def _download_and_extract_atomic(url: str, extract_path: str, name: str) -> None:
    """Extract into a sibling temp dir, then atomically swap it into place.

    A failed or interrupted extraction leaves only the temp dir (cleaned here),
    never a half-populated live dir. The swap is the last step, so `extract_path`
    only ever exists in its complete form.
    """
    parent = os.path.dirname(extract_path)
    os.makedirs(parent, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix=f".{name}.tmp-", dir=parent)
    try:
        download_and_extract(url, tmp_dir, name)
        if not _is_extracted(tmp_dir):
            raise InvalidAddonPath(
                f"Addon {name!r} extracted from {url} but produced no manifest.json"
            )
        # os.replace can't overwrite a non-empty dir; clear any stale partial
        # first, then swap. Within _extract_lock + single process this is safe.
        if os.path.exists(extract_path):
            shutil.rmtree(extract_path, ignore_errors=True)
        os.replace(tmp_dir, extract_path)
    finally:
        # No-op after a successful swap (tmp_dir was renamed away).
        shutil.rmtree(tmp_dir, ignore_errors=True)


def get_addon_path(addon_name: str) -> str:
    """
    Returns a path to the addon in the shared addons folder.
    """
    return str(ADDONS_DIR / addon_name)


def maybe_download_addons(
    addons: List[DefaultAddons], addons_list: Optional[List[str]] = None
) -> None:
    """
    Downloads and extracts addons to the shared cache, skipping any already
    present. Re-extracts a partially-extracted (manifest-less) cache dir rather
    than trusting it, and never leaves a half-populated dir behind on failure.

    Raises InvalidAddonPath if an addon can't be made usable — a failure here
    means every subsequent launch would fail `confirm_paths`, so it must surface
    loudly, not be swallowed.
    """
    for addon in addons:
        addon_path = get_addon_path(addon.name)

        # Fast path: a complete cache dir is reused as-is, no lock needed.
        if _is_extracted(addon_path):
            if addons_list is not None:
                addons_list.append(addon_path)
            continue

        # Serialise the extraction so concurrent launches don't each re-download;
        # re-check inside the lock in case another thread just populated it.
        with _extract_lock:
            if not _is_extracted(addon_path):
                _download_and_extract_atomic(addon.value, addon_path, addon.name)

        if not _is_extracted(addon_path):
            raise InvalidAddonPath(
                f"Addon {addon.name!r} could not be extracted to {addon_path}"
            )
        if addons_list is not None:
            addons_list.append(addon_path)
