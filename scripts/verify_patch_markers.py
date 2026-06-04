#!/usr/bin/env python3
"""Verify a built Camoufox artifact actually contains every expected patch.

Reads patch-manifest.json and asserts:
  - each `libxul_markers` entry is present in libxul.so, and
  - each `omni_markers` entry is present in juggler JS inside omni.ja.

A missing marker means the artifact was compiled from stale or unpatched source,
so the build is fundamentally wrong even if the version string says otherwise.
We fail loudly. This is the gate that would have caught the 2026-05 stale-build:
the synthesizeMouseEvent juggler fix was absent from the shipped omni.ja while
version.json still reported the patched build.

Usage:
    verify_patch_markers.py <camoufox-artifact.zip> <patch-manifest.json>

The artifact is the packaged Camoufox zip (camoufox-*-lin.*.zip). omni.ja is a
zip nested inside it, so we read both with zipfile — no unzip/strings needed.
"""

from __future__ import annotations

import io
import json
import sys
import zipfile


def _read_manifest(path: str) -> tuple[list[str], list[str]]:
    with open(path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    return manifest["libxul_markers"], manifest["omni_markers"]


def verify(artifact_path: str, manifest_path: str) -> int:
    libxul_markers, omni_markers = _read_manifest(manifest_path)
    missing: list[str] = []

    with zipfile.ZipFile(artifact_path) as art:
        names = art.namelist()

        # --- libxul.so: search the raw binary for C++ marker strings ---
        libxul_name = next((n for n in names if n.endswith("libxul.so")), None)
        if libxul_name is None:
            print("FATAL: libxul.so not found in artifact", file=sys.stderr)
            return 1
        libxul = art.read(libxul_name)
        for marker in libxul_markers:
            if marker.encode() in libxul:
                print(f"  ✓ libxul: {marker}")
            else:
                print(f"  ✗ libxul: {marker} — MISSING")
                missing.append(f"libxul:{marker}")

        # --- omni.ja: search juggler JS inside each nested archive ---
        # Packaged Camoufox ships two omni.ja (top-level + browser/). Juggler
        # lives in one of them; we search all of them so we don't depend on which.
        omni_names = [n for n in names if n.endswith("omni.ja")]
        if not omni_names:
            print("FATAL: no omni.ja found in artifact", file=sys.stderr)
            return 1
        omni_hits = {marker: 0 for marker in omni_markers}
        for omni_name in omni_names:
            with zipfile.ZipFile(io.BytesIO(art.read(omni_name))) as omni:
                for entry in omni.namelist():
                    if not entry.endswith(".js"):
                        continue
                    data = omni.read(entry)
                    for marker in omni_markers:
                        if marker.encode() in data:
                            omni_hits[marker] += 1
        for marker in omni_markers:
            if omni_hits[marker] > 0:
                print(f"  ✓ omni: {marker} ({omni_hits[marker]} hit(s))")
            else:
                print(f"  ✗ omni: {marker} — MISSING")
                missing.append(f"omni:{marker}")

    if missing:
        print(
            f"FATAL: {len(missing)} patch marker(s) missing: {missing}\n"
            "The artifact was built from stale or unpatched source.",
            file=sys.stderr,
        )
        return 1
    print("All patch markers verified in artifact.")
    return 0


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    return verify(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    sys.exit(main())
