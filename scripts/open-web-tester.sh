#!/usr/bin/env bash
# Opens the Camoufox web tester and prints the binary path to select.
#
# Usage: ./open-web-tester.sh [binary-path]
#   If no path given, uses the default build output location.

set -euo pipefail

DEFAULT_BINARY="$(find ~/20tech/oss/camoufox/camoufox-*/obj-*/dist/Camoufox.app/Contents/MacOS/camoufox 2>/dev/null | head -1)"
BINARY="${1:-$DEFAULT_BINARY}"

if [[ -z "$BINARY" ]]; then
    echo "No binary found. Pass the path as an argument."
    exit 1
fi

echo "Opening web tester..."
echo ""
echo "Select this binary when prompted:"
echo "  $BINARY"
echo ""
echo "Or the installed copy:"
echo "  $(find ~/Library/Caches/camoufox/browsers/official/*/Camoufox.app/Contents/MacOS/camoufox 2>/dev/null | head -1)"
echo ""

# Copy the build output path to clipboard for easy pasting
echo -n "$BINARY" | pbcopy
echo "(Build binary path copied to clipboard)"
echo ""

open "https://camoufox-tester.vercel.app/"
