#!/usr/bin/env bash
# Install a custom Camoufox build into the local channel.
#
# Usage:
#   ./install-local-build.sh [artifact.zip] [version-build]
#   ./install-local-build.sh --from-build    # install from build tree (default when no zip and build exists)
#
# If no artifact is given, prefers the live build tree (obj-*/dist/) over dist/*.zip.
# This avoids the stale-zip trap where `make build` compiles fresh code but the
# dist/ zip is from a previous `multibuild.py` run.
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

# --- Read version/release from upstream.sh ---

source "$REPO_ROOT/upstream.sh"
VERSION_BUILD="${version}-${release}"
VERSION="$version"
BUILD="$release"

# --- Parse flags ---

PRE_WARM=false
FROM_BUILD=false
POSITIONAL_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --pre-warm)   PRE_WARM=true ;;
        --from-build) FROM_BUILD=true ;;
        *)            POSITIONAL_ARGS+=("$arg") ;;
    esac
done

# --- Detect platform ---

case "$(uname -s)-$(uname -m)" in
    Darwin-arm64)  PLAT="mac.arm64";  OBJ_ARCH="aarch64-apple-darwin" ;;
    Darwin-x86_64) PLAT="mac.x86_64"; OBJ_ARCH="x86_64-apple-darwin" ;;
    Linux-x86_64)  PLAT="lin.x86_64"; OBJ_ARCH="x86_64-pc-linux-gnu" ;;
    Linux-aarch64) PLAT="lin.aarch64"; OBJ_ARCH="aarch64-unknown-linux-gnu" ;;
    MINGW*|MSYS*|CYGWIN*)  PLAT="win.x86_64"; OBJ_ARCH="x86_64-pc-windows-msvc" ;;
    *)             echo "Unknown platform: $(uname -s)-$(uname -m)"; exit 1 ;;
esac

# --- Resolve source: build tree or artifact zip ---

CF_SOURCE_DIR="${REPO_ROOT}/camoufox-${VERSION_BUILD}"
BUILD_DIST="${CF_SOURCE_DIR}/obj-${OBJ_ARCH}/dist"
INSTALL_FROM_BUILD=false

ARTIFACT="${POSITIONAL_ARGS[0]:-}"

if [[ -n "$ARTIFACT" ]]; then
    # Explicit artifact — use it
    if [[ ! -f "$ARTIFACT" ]]; then
        echo "Artifact not found: $ARTIFACT"
        exit 1
    fi
    echo "Using artifact: $ARTIFACT"
elif [[ "$FROM_BUILD" == true ]]; then
    # Explicit --from-build
    if [[ ! -d "$BUILD_DIST" ]]; then
        echo "Build tree not found: $BUILD_DIST"
        echo "Run 'make build' first."
        exit 1
    fi
    INSTALL_FROM_BUILD=true
elif [[ -d "$BUILD_DIST/Camoufox.app" ]] || [[ -d "$BUILD_DIST/bin" ]]; then
    # Build tree exists — prefer it over dist/ zip (avoids stale-zip trap)
    INSTALL_FROM_BUILD=true
    echo "Using build tree: $BUILD_DIST"

    # Warn if source files are newer than the built binary
    BUILD_BINARY=""
    if [[ -f "$BUILD_DIST/Camoufox.app/Contents/MacOS/XUL" ]]; then
        BUILD_BINARY="$BUILD_DIST/Camoufox.app/Contents/MacOS/XUL"
    elif [[ -f "$BUILD_DIST/bin/libxul.so" ]]; then
        BUILD_BINARY="$BUILD_DIST/bin/libxul.so"
    fi
    if [[ -n "$BUILD_BINARY" ]]; then
        NEWER_SOURCE="$(find "$CF_SOURCE_DIR" -name '*.cpp' -newer "$BUILD_BINARY" -not -path '*/obj-*' 2>/dev/null | head -1)"
        if [[ -n "$NEWER_SOURCE" ]]; then
            echo ""
            echo "WARNING: Source files are newer than the built binary."
            echo "         Run 'make build' first if you want to include recent edits."
            echo "         (e.g. $(basename "$NEWER_SOURCE") is newer than XUL)"
            echo ""
        fi
    fi
else
    # Fall back to dist/ zip
    ARTIFACT="$(ls -t "$REPO_ROOT"/dist/camoufox-*-"${PLAT}".zip 2>/dev/null | head -1)"
    if [[ -z "$ARTIFACT" ]]; then
        echo "No build tree or artifact found."
        echo "Run 'make build' or 'python3 multibuild.py' first."
        exit 1
    fi
    echo "Using artifact: $ARTIFACT"
fi

echo "Version: $VERSION_BUILD"

INSTALL_DIR="${BROWSERS_DIR}/local/${VERSION_BUILD}"
echo "Installing to: $INSTALL_DIR"

# --- Sync properties.json from settings/ to build tree ---

if [[ -f "$REPO_ROOT/settings/properties.json" ]] && [[ -d "$CF_SOURCE_DIR/lw" ]]; then
    cp "$REPO_ROOT/settings/properties.json" "$CF_SOURCE_DIR/lw/properties.json"
fi

# --- Ensure compat flag exists (prevents pip camoufox from wiping the cache) ---

mkdir -p "${CACHE_DIR}"
touch "${CACHE_DIR}/.0.5_FLAG"

# --- Install ---

if [[ -d "$INSTALL_DIR" ]]; then
    echo "Removing existing installation..."
    rm -rf "$INSTALL_DIR"
fi

mkdir -p "$INSTALL_DIR"

if [[ "$INSTALL_FROM_BUILD" == true ]]; then
    # Copy directly from the build tree — always fresh
    if [[ -d "$BUILD_DIST/Camoufox.app" ]]; then
        cp -a "$BUILD_DIST/Camoufox.app" "$INSTALL_DIR/Camoufox.app"
    else
        cp -a "$BUILD_DIST/bin"/. "$INSTALL_DIR/"
    fi
    # Sync properties.json into the installed resources
    if [[ -f "$REPO_ROOT/settings/properties.json" ]]; then
        for dest in \
            "$INSTALL_DIR/Camoufox.app/Contents/Resources/properties.json" \
            "$INSTALL_DIR/properties.json"; do
            if [[ -d "$(dirname "$dest")" ]]; then
                cp "$REPO_ROOT/settings/properties.json" "$dest"
            fi
        done
    fi
else
    # Unzip artifact
    TMP_DIR="$(mktemp -d)"
    trap 'rm -rf "$TMP_DIR"' EXIT

    unzip -q "$ARTIFACT" -d "$TMP_DIR"

    if [[ -d "$TMP_DIR/Camoufox.app" ]]; then
        cp -a "$TMP_DIR/Camoufox.app" "$INSTALL_DIR/Camoufox.app"
    elif [[ -d "$TMP_DIR/Camoufox/Camoufox.app" ]]; then
        cp -a "$TMP_DIR/Camoufox/Camoufox.app" "$INSTALL_DIR/Camoufox.app"
    else
        cp -a "$TMP_DIR"/. "$INSTALL_DIR/"
    fi
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
    # Find a Python that has camoufox installed
    PYTHON="python3"
    for candidate in \
        "$REPO_ROOT/pythonlib/../.venv/bin/python" \
        "$HOME/20tech/drivingtest/dvsa-scraper/.venv/bin/python" \
        "$(command -v python3 2>/dev/null)"; do
        if [[ -x "$candidate" ]] && "$candidate" -c "import camoufox" 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    done
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
