"""
Verify an uncaught page error does NOT crash the Playwright driver (port of #625).

The bug (camoufox #617): our Juggler's `pageUncaughtError` event never sent a
`location` field. Playwright >=1.60 reads `pageError.location.url` unconditionally
when marshalling the event (playwright#39767), so on the old Juggler EVERY uncaught
page error left `pageError.location` undefined -> a TypeError inside a Node
EventEmitter callback -> the whole Playwright Node driver process crashed -> every
in-flight op reported "Connection closed while reading from the driver". Imperva /
reese84 pages throw uncaught errors routinely, so this was a prod storm (~100 driver
crashes/hr on dev.4 + PW 1.62). The fix makes Juggler emit `location` on the event.

This test triggers an uncaught page error and asserts the driver SURVIVES it (and
the error is delivered). On a pre-#625 build + PW >=1.60 it crashes at step 1.
Needs a BUILT browser carrying the fix (>= ruben.dev.5) — run it against a local
build or the deployed dev container after the base rebuild lands.

Run:
    cd ~/20tech/drivingtest/dvsa-bot
    uv run python ~/20tech/oss/camoufox/tests/patches/2026-09-19-pageerror-no-driver-crash.py
"""

import asyncio
import sys

from helpers import launch_camoufox


async def test():
    failures = []
    async with launch_camoufox() as (page, _config):
        errors = []
        page.on("pageerror", lambda e: errors.append(e))

        # Trigger an uncaught JS error on the page (evaluate() would catch it).
        await page.set_content(
            "<script>throw new Error('boom-uncaught-no-handler')</script>"
        )
        # Let the pageerror round-trip Juggler -> driver.
        await page.wait_for_timeout(500)

        # 1) The driver must still be alive. On the pre-#625 build + PW >=1.60 the
        #    driver has already crashed and this raises "Connection closed ...".
        try:
            alive = await page.evaluate("1 + 1")
            if alive == 2:
                print("  driver survived an uncaught page error: PASS")
            else:
                failures.append(f"driver.evaluate returned {alive!r}, expected 2")
        except Exception as e:  # noqa: BLE001 -- test: a raise here IS the #625 bug
            failures.append(f"driver died after a page error (the #625 crash): {e}")
            print(f"  driver died: FAIL ({e})")

        # 2) The page error should still have been delivered to the handler.
        if errors:
            print(f"  pageerror delivered ({errors[0]}): PASS")
        else:
            failures.append("no pageerror delivered — event lost")

    print("\n" + "=" * 50)
    if failures:
        print(f"FAILED ({len(failures)} issues):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
