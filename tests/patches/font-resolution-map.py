"""
Test the fonts:resolution_map closed sandbox.

Verifies that:
1. macOS fonts in the map resolve and render with their own metrics
2. Linux fontconfig aliases are blocked (render with fallback metrics)
3. CSS generic pass-throughs remap to the correct macOS fonts
4. Unknown fonts are blocked (render with fallback metrics)

Detection method: measureText width comparison. A font that resolves
produces a different width from the monospace baseline. A font that
doesn't resolve falls back and matches the fallback width.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'pythonlib'))

from helpers import launch_camoufox


async def test_resolution_map():
    async with launch_camoufox(os="macos") as (page, config):
        # Font detection via measureText: if a font resolves, its width
        # differs from the monospace/sans-serif/serif baselines.
        results = await page.evaluate("""() => {
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');
            const testStr = 'mmmmmmmmlli';

            function getWidth(fontFamily) {
                ctx.font = `72px ${fontFamily}`;
                return ctx.measureText(testStr).width;
            }

            // Baselines
            const monoW = getWidth('monospace');
            const sansW = getWidth('sans-serif');
            const serifW = getWidth('serif');

            // A font "exists" if its width differs from ALL three baselines
            function fontExists(name) {
                const w = getWidth(`"${name}", monospace`);
                if (Math.abs(w - monoW) > 0.01) return true;
                const w2 = getWidth(`"${name}", sans-serif`);
                if (Math.abs(w2 - sansW) > 0.01) return true;
                const w3 = getWidth(`"${name}", serif`);
                if (Math.abs(w3 - serifW) > 0.01) return true;
                return false;
            }

            const testFonts = [
                // macOS fonts — should exist
                'Helvetica', 'Arial', 'Times New Roman', 'Menlo', 'Courier New',
                'Georgia', 'Verdana', 'Lucida Grande', 'Monaco', 'Helvetica Neue',
                'Apple Chancery', 'Papyrus', 'Futura', 'Optima', 'Palatino',
                // Linux fontconfig aliases — should NOT exist on macOS
                'Sans', 'mono',
                // Linux/GNOME fonts — should NOT exist
                'Ubuntu', 'Cantarell', 'DejaVu Sans', 'Liberation Sans',
                // Windows-only fonts — should NOT exist on macOS
                'Segoe UI', 'Calibri', 'Consolas',
                // Completely fictional — should NOT exist
                'FakeFont123', 'NotARealFont',
            ];
            const out = {};
            for (const font of testFonts) {
                out[font] = fontExists(font);
            }

            // Also report baseline widths for debugging
            out['_baselines'] = { monospace: monoW, 'sans-serif': sansW, serif: serifW };

            return out;
        }""")

        # CSS generic resolution
        generic_results = await page.evaluate("""() => {
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');
            function w(f) { ctx.font = '16px ' + f; return ctx.measureText('Hello World').width; }
            return {
                'sans-serif': w('sans-serif'), 'Helvetica': w('Helvetica'),
                'serif': w('serif'), 'Times': w('Times'),
                'monospace': w('monospace'), 'Menlo': w('Menlo'),
            };
        }""")

        print("\n=== Font Resolution Map Test ===\n")

        baselines = results.pop('_baselines')
        print(f"Baselines: mono={baselines['monospace']:.3f}  "
              f"sans={baselines['sans-serif']:.3f}  "
              f"serif={baselines['serif']:.3f}\n")

        all_pass = True

        # macOS fonts
        macos_fonts = ['Helvetica', 'Arial', 'Times New Roman', 'Menlo',
                       'Courier New', 'Georgia', 'Verdana', 'Lucida Grande',
                       'Monaco', 'Helvetica Neue', 'Apple Chancery', 'Papyrus',
                       'Futura', 'Optima', 'Palatino']
        print("macOS fonts (should EXIST):")
        for font in macos_fonts:
            ok = results[font]
            if not ok:
                all_pass = False
            print(f"  {'PASS' if ok else 'FAIL'}  {font}")

        # Linux names
        linux_names = ['Sans', 'mono', 'Ubuntu', 'Cantarell',
                       'DejaVu Sans', 'Liberation Sans']
        print("\nLinux names (should NOT exist):")
        for font in linux_names:
            ok = not results[font]
            if not ok:
                all_pass = False
            print(f"  {'PASS' if ok else 'FAIL'}  {font}")

        # Windows names
        win_names = ['Segoe UI', 'Calibri', 'Consolas']
        print("\nWindows names (should NOT exist):")
        for font in win_names:
            ok = not results[font]
            if not ok:
                all_pass = False
            print(f"  {'PASS' if ok else 'FAIL'}  {font}")

        # Fictional
        fake_names = ['FakeFont123', 'NotARealFont']
        print("\nFictional names (should NOT exist):")
        for font in fake_names:
            ok = not results[font]
            if not ok:
                all_pass = False
            print(f"  {'PASS' if ok else 'FAIL'}  {font}")

        # CSS generic resolution
        print("\n=== CSS Generic Resolution ===\n")
        pairs = [
            ('sans-serif', 'Helvetica'),
            ('serif', 'Times'),
            ('monospace', 'Menlo'),
        ]
        for generic, expected in pairs:
            gw = generic_results[generic]
            ew = generic_results[expected]
            match = abs(gw - ew) < 0.01
            if not match:
                all_pass = False
            print(f"  {'PASS' if match else 'FAIL'}  {generic} ({gw:.3f}) ≈ {expected} ({ew:.3f})")

        # Resolution map stats
        res_map = config.get('fonts:resolution_map', {})
        print(f"\nResolution map: {len(res_map)} entries")

        print(f"\n{'=' * 40}")
        print(f"Overall: {'ALL PASS' if all_pass else 'SOME FAILED'}")
        return 0 if all_pass else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(test_resolution_map()))
