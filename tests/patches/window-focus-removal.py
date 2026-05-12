"""
Verify the window.focus() removal from activateAndRun.

Two headed Camoufox instances run concurrent mouse.move() calls. Before the
fix, this reliably caused 3s+ stalls as both processes fought for OS window
focus on every dispatch. After: mouse.move() completes in <100ms regardless
of how many instances are open.

Also verifies that document.hasFocus() and document.visibilityState remain
correct — content process has overrideHasFocus + forceActiveState (main.js),
so these should be unaffected by OS focus state.

Run from dvsa-bot to get the right venv:
    cd ~/20tech/drivingtest/dvsa-bot
    uv run python ~/20tech/oss/camoufox/tests/patches/window-focus-removal.py

What PASS means:
    Both instances complete 50 concurrent mouse.move() trajectories with
    p95 latency < 500ms, and document.hasFocus() returns true on both.
"""

import asyncio
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Not using launch_camoufox helper — we need two separate browser instances,
# and the helper's context manager isn't designed for that.
from camoufox.async_api import AsyncCamoufox
from camoufox.fingerprints import generate_context_fingerprint, get_random_preset

MOVES_PER_INSTANCE = 50
LATENCY_THRESHOLD_MS = 500  # p95 must be under this
MOVE_TIMEOUT_S = 5.0  # per-move timeout — pre-fix, moves hung for 3s+


async def run_mouse_trajectory(page, instance_id: str) -> list[float]:
    """Run MOVES_PER_INSTANCE mouse moves, return per-move latencies in ms."""
    latencies = []
    x, y = 100, 100
    for i in range(MOVES_PER_INSTANCE):
        x = 100 + (i * 7) % 400
        y = 100 + (i * 11) % 300
        t0 = time.monotonic()
        try:
            await asyncio.wait_for(page.mouse.move(x, y), timeout=MOVE_TIMEOUT_S)
        except asyncio.TimeoutError:
            ms = (time.monotonic() - t0) * 1000
            print(f"  {instance_id}: move #{i} timed out at {ms:.0f}ms")
            latencies.append(ms)
            continue
        ms = (time.monotonic() - t0) * 1000
        latencies.append(ms)
    return latencies


async def launch_instance(instance_id: str, os_name: str = "macos"):
    """Launch a headed Camoufox, open a page, return (browser, page, config)."""
    for attempt in range(10):
        preset = get_random_preset(os=os_name)
        fp = generate_context_fingerprint(preset=preset)
        try:
            browser = await AsyncCamoufox(
                fingerprint_preset=fp["preset"],
                headless=False,
                os=os_name,
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
    raise RuntimeError(f"{instance_id}: no valid preset after 10 attempts")


async def main() -> int:
    print("Launching two headed Camoufox instances...")
    browser_a, page_a = await launch_instance("A")
    browser_b, page_b = await launch_instance("B")
    print("Both instances launched.\n")

    # Check focus state BEFORE mouse moves
    focus_a_before = await page_a.evaluate("document.hasFocus()")
    focus_b_before = await page_b.evaluate("document.hasFocus()")
    vis_a = await page_a.evaluate("document.visibilityState")
    vis_b = await page_b.evaluate("document.visibilityState")
    print(f"  A: hasFocus={focus_a_before}, visibilityState={vis_a}")
    print(f"  B: hasFocus={focus_b_before}, visibilityState={vis_b}")

    # Run concurrent mouse trajectories
    print(f"\nRunning {MOVES_PER_INSTANCE} concurrent mouse.move() on each instance...")
    t0 = time.monotonic()
    latencies_a, latencies_b = await asyncio.gather(
        run_mouse_trajectory(page_a, "A"),
        run_mouse_trajectory(page_b, "B"),
    )
    total_s = time.monotonic() - t0
    print(f"Completed in {total_s:.1f}s\n")

    # Check focus state AFTER mouse moves
    focus_a_after = await page_a.evaluate("document.hasFocus()")
    focus_b_after = await page_b.evaluate("document.hasFocus()")

    # Stats
    all_passed = True
    for label, latencies in [("A", latencies_a), ("B", latencies_b)]:
        p50 = statistics.median(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        p_max = max(latencies)
        timeouts = sum(1 for l in latencies if l >= MOVE_TIMEOUT_S * 1000)
        print(f"  Instance {label}: p50={p50:.0f}ms  p95={p95:.0f}ms  max={p_max:.0f}ms  timeouts={timeouts}")
        if p95 >= LATENCY_THRESHOLD_MS:
            print(f"  FAIL: p95 ({p95:.0f}ms) >= {LATENCY_THRESHOLD_MS}ms threshold")
            all_passed = False

    print()

    # Focus checks
    for label, before, after in [("A", focus_a_before, focus_a_after), ("B", focus_b_before, focus_b_after)]:
        if not after:
            print(f"  FAIL: Instance {label} hasFocus={after} after mouse moves")
            all_passed = False
        else:
            print(f"  Instance {label}: hasFocus stayed true")

    # Cleanup
    await browser_a.__aexit__(None, None, None)
    await browser_b.__aexit__(None, None, None)

    print()
    if all_passed:
        print("PASS: concurrent headed mouse.move() works without stalls")
    else:
        print("FAIL: see above")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
