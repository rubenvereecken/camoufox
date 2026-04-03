#!/usr/bin/env bash
# Install a custom Camoufox build into the local channel.
#
# Usage:
#   ./install-local-build.sh [artifact.zip] [version-build]
#
# If no artifact is given, uses the latest zip in dist/.
# If no version-build is given, extracts it from the zip filename.
#
# Installs to ~/.cache/camoufox/browsers/local/<version-build>/
# and sets active_version in config.json.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

CACHE_DIR="${HOME}/Library/Caches/camoufox"
# Fall back to XDG if not on macOS
if [[ ! -d "${HOME}/Library/Caches" ]]; then
    CACHE_DIR="${XDG_CACHE_HOME:-${HOME}/.cache}/camoufox"
fi

BROWSERS_DIR="${CACHE_DIR}/browsers"
CONFIG_FILE="${CACHE_DIR}/config.json"

# --- Parse flags ---

PRE_WARM=false
POSITIONAL_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --pre-warm) PRE_WARM=true ;;
        *)          POSITIONAL_ARGS+=("$arg") ;;
    esac
done

# --- Resolve artifact zip ---

ARTIFACT="${POSITIONAL_ARGS[0]:-}"
if [[ -z "$ARTIFACT" ]]; then
    # Auto-detect platform
    case "$(uname -s)-$(uname -m)" in
        Darwin-arm64)  PLAT="mac.arm64" ;;
        Darwin-x86_64) PLAT="mac.x86_64" ;;
        Linux-x86_64)  PLAT="lin.x86_64" ;;
        Linux-aarch64) PLAT="lin.aarch64" ;;
        MINGW*|MSYS*|CYGWIN*)  PLAT="win.x86_64" ;;
        *)             echo "Unknown platform: $(uname -s)-$(uname -m)"; exit 1 ;;
    esac
    ARTIFACT="$(ls -t "$REPO_ROOT"/dist/camoufox-*-"${PLAT}".zip 2>/dev/null | head -1)"
    if [[ -z "$ARTIFACT" ]]; then
        echo "No artifact found in dist/ for ${PLAT}. Pass the zip path as an argument."
        exit 1
    fi
    echo "Using latest artifact: $ARTIFACT"
fi

if [[ ! -f "$ARTIFACT" ]]; then
    echo "Artifact not found: $ARTIFACT"
    exit 1
fi

# --- Resolve version-build string ---

VERSION_BUILD="${POSITIONAL_ARGS[1]:-}"
if [[ -z "$VERSION_BUILD" ]]; then
    # Extract from filename: camoufox-<version>-<build>-mac.arm64.zip
    BASENAME="$(basename "$ARTIFACT")"
    # Strip prefix "camoufox-" and suffix "-mac.arm64.zip" (or similar)
    VERSION_BUILD="${BASENAME#camoufox-}"
    VERSION_BUILD="${VERSION_BUILD%-mac.*}"
    VERSION_BUILD="${VERSION_BUILD%-lin.*}"
    VERSION_BUILD="${VERSION_BUILD%-win.*}"
fi

echo "Version: $VERSION_BUILD"

# --- Extract version and build parts ---

# version-build format: "146.0.1-ruben.brotli-fix.1"
# version = everything up to the first hyphen-followed-by-non-digit
# For simplicity, split on first hyphen after the semver
VERSION="$(echo "$VERSION_BUILD" | grep -oE '^[0-9]+\.[0-9]+\.[0-9]+')"
BUILD="${VERSION_BUILD#${VERSION}-}"

INSTALL_DIR="${BROWSERS_DIR}/local/${VERSION_BUILD}"

echo "Installing to: $INSTALL_DIR"

# --- Ensure compat flag exists (prevents pip camoufox from wiping the cache) ---

mkdir -p "${CACHE_DIR}"
touch "${CACHE_DIR}/.0.5_FLAG"

# --- Install ---

if [[ -d "$INSTALL_DIR" ]]; then
    echo "Removing existing installation..."
    rm -rf "$INSTALL_DIR"
fi

mkdir -p "$INSTALL_DIR"

# Unzip to temp dir first to handle nested structure
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

unzip -q "$ARTIFACT" -d "$TMP_DIR"

# Handle macOS structure: the zip may contain Camoufox.app directly or nested
# Use cp -a instead of mv — mv fails with "Directory not empty" on partial reinstalls
if [[ -d "$TMP_DIR/Camoufox.app" ]]; then
    cp -a "$TMP_DIR/Camoufox.app" "$INSTALL_DIR/Camoufox.app"
elif [[ -d "$TMP_DIR/Camoufox/Camoufox.app" ]]; then
    cp -a "$TMP_DIR/Camoufox/Camoufox.app" "$INSTALL_DIR/Camoufox.app"
else
    # Linux/Windows: copy everything
    cp -a "$TMP_DIR"/. "$INSTALL_DIR/"
fi

# Fix permissions (cp/unzip can strip executable bits)
chmod -R 755 "$INSTALL_DIR"

# Write version.json
cat > "$INSTALL_DIR/version.json" <<VEOF
{
  "version": "$VERSION",
  "build": "$BUILD",
  "prerelease": false,
  "local_build": true
}
VEOF

# --- Set active version ---

RELATIVE_PATH="browsers/local/${VERSION_BUILD}"

# Write config.json (preserve channel if set)
if [[ -f "$CONFIG_FILE" ]]; then
    # Use python for safe JSON manipulation
    python3 -c "
import json, sys
with open('$CONFIG_FILE') as f:
    cfg = json.load(f)
cfg['active_version'] = '$RELATIVE_PATH'
with open('$CONFIG_FILE', 'w') as f:
    json.dump(cfg, f, indent=2)
"
else
    mkdir -p "$(dirname "$CONFIG_FILE")"
    echo "{\"channel\": \"official/stable\", \"active_version\": \"$RELATIVE_PATH\"}" > "$CONFIG_FILE"
fi

echo ""
echo "Installed: $INSTALL_DIR"
echo "Active:    $RELATIVE_PATH"

# Verify
PLIST="$INSTALL_DIR/Camoufox.app/Contents/Info.plist"
if [[ -f "$PLIST" ]]; then
    BUNDLE_VERSION="$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$PLIST" 2>/dev/null || echo "unknown")"
    echo "Bundle:    $BUNDLE_VERSION"
fi

# --- Remove official build (prevents fallback overwrite of config.json) ---

if [[ -d "${BROWSERS_DIR}/official" ]]; then
    rm -rf "${BROWSERS_DIR}/official"
    echo "Removed official build (prevents fallback overwrite)"
fi

# --- Pre-warm: download addons and GeoIP databases ---

if [[ "$PRE_WARM" == true ]]; then
    echo ""
    echo "Pre-warming caches..."
    # Find a Python that has camoufox installed (venv, uv, or system)
    PYTHON="python3"
    if [[ -f "$REPO_ROOT/../drivingtest/dvsa-scraper/.venv/bin/python" ]]; then
        PYTHON="$REPO_ROOT/../drivingtest/dvsa-scraper/.venv/bin/python"
    fi
    "$PYTHON" -c "
from camoufox.addons import maybe_download_addons, DefaultAddons
maybe_download_addons([DefaultAddons.UBO])
print('UBO addon cached')

try:
    from camoufox.geolocation import download_mmdb
    download_mmdb()
    print('GeoIP databases cached')
except Exception as e:
    print(f'GeoIP download skipped: {e}')
" || echo "Pre-warm failed (camoufox not importable). Run manually after uv sync."
fi

echo ""
echo "Done. Run 'camoufox list' to see installed versions."
