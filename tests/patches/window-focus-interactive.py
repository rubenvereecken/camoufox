"""
Interactive test: move your real cursor in/out of the browser windows.

Launches two headed Camoufox instances running continuous mouse.move() loops.
Prints per-move latency live — you'll see it spike when the real cursor
enters a browser window.

Run from dvsa-bot:
    cd ~/20tech/drivingtest/dvsa-bot
    uv run python ~/20tech/oss/camoufox/tests/patches/window-focus-interactive.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from camoufox.async_api import AsyncCamoufox
from camoufox.fingerprints import generate_context_fingerprint, get_random_preset

DURATION_S = 15
STALL_THRESHOLD_MS = 200


async def launch_instance(label: str):
    for _ in range(10):
        preset = get_random_preset(os="macos")
        fp = generate_context_fingerprint(preset=preset)
        try:
            browser = await AsyncCamoufox(
                fingerprint_preset=fp["preset"],
                headless=False,
                os="macos",
            ).__aenter__()
            context = await browser.new_context(**fp["context_options"])
            await context.add_init_script(fp["init_script"])
            page = await context.new_page()
            await page.goto("about:blank")
            return browser, page
        except ValueError as e:
            if "WebGL" in str(e):
                continue
            raise
    raise RuntimeError(f"{label}: no valid preset")


async def move_loop(page, label: str, stop_event: asyncio.Event, stats: dict):
    i = 0
    stalls = 0
    max_ms = 0.0
    while not stop_event.is_set():
        x = 100 + (i * 7) % 400
        y = 100 + (i * 11) % 300
        t0 = time.monotonic()
        try:
            await asyncio.wait_for(page.mouse.move(x, y), timeout=5.0)
        except asyncio.TimeoutError:
            ms = (time.monotonic() - t0) * 1000
            print(f"  {label}: move #{i} TIMEOUT {ms:.0f}ms")
            stalls += 1
            max_ms = max(max_ms, ms)
            i += 1
            continue
        ms = (time.monotonic() - t0) * 1000
        if ms >= STALL_THRESHOLD_MS:
            print(f"  {label}: move #{i} STALL {ms:.0f}ms")
            stalls += 1
        max_ms = max(max_ms, ms)
        i += 1
    stats[label] = {"moves": i, "stalls": stalls, "max_ms": max_ms}


async def main() -> int:
    print("Launching two headed instances...")
    browser_a, page_a = await launch_instance("A")
    browser_b, page_b = await launch_instance("B")

    print(f"\n>>> Move your real cursor IN and OUT of the browser windows!")
    print(f">>> Running for {DURATION_S}s. Stalls (>{STALL_THRESHOLD_MS}ms) print live.\n")

    stop = asyncio.Event()
    stats: dict = {}

    async def timer():
        for remaining in range(DURATION_S, 0, -1):
            if remaining in (15, 10, 5, 3, 2, 1):
                print(f"  ... {remaining}s remaining")
            await asyncio.sleep(1)
        stop.set()

    await asyncio.gather(
        move_loop(page_a, "A", stop, stats),
        move_loop(page_b, "B", stop, stats),
        timer(),
    )

    print(f"\n--- Results ---")
    total_stalls = 0
    for label in ("A", "B"):
        s = stats[label]
        total_stalls += s["stalls"]
        print(f"  {label}: {s['moves']} moves, {s['stalls']} stalls, max={s['max_ms']:.0f}ms")

    await browser_a.__aexit__(None, None, None)
    await browser_b.__aexit__(None, None, None)

    if total_stalls > 0:
        print(f"\nFAIL: {total_stalls} stalls detected")
        return 1
    else:
        print(f"\nPASS: zero stalls")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
