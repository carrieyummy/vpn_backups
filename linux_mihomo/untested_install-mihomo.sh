#!/usr/bin/env bash
set -euo pipefail

REPO="${REPO:-https://github.com/MetaCubeX/mihomo}"
VERSION="${VERSION:-}"
INSTALL_PATH="${INSTALL_PATH:-/usr/bin/mihomo}"
INSTALL_DEPS="${INSTALL_DEPS:-1}"

usage() {
  cat <<EOF
Usage: ./install-mihomo.sh [options]

Download and install Mihomo from GitHub Releases.

Options:
  --version VERSION      Install a specific version, for example: v1.19.27 or 1.19.27
  --install-path PATH    Install target, default: /usr/bin/mihomo
  --no-install-deps      Do not install Debian / Ubuntu dependencies
  -h, --help             Show this help

Environment:
  REPO=url               Source repository, default: https://github.com/MetaCubeX/mihomo
  VERSION=version        Version to install; empty means latest
  INSTALL_PATH=path      Install target, default: /usr/bin/mihomo
  INSTALL_DEPS=0|1       Install dependencies with apt-get, default: 1
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --version)
      VERSION="${2:-}"
      if [ -z "$VERSION" ]; then
        echo "Missing value for --version" >&2
        exit 2
      fi
      shift
      ;;
    --install-path)
      INSTALL_PATH="${2:-}"
      if [ -z "$INSTALL_PATH" ]; then
        echo "Missing value for --install-path" >&2
        exit 2
      fi
      shift
      ;;
    --no-install-deps)
      INSTALL_DEPS=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

run_as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    need_cmd sudo
    sudo "$@"
  fi
}

install_deps() {
  if [ "$INSTALL_DEPS" != "1" ]; then
    return
  fi

  if command -v apt-get >/dev/null 2>&1; then
    run_as_root apt-get update
    run_as_root apt-get install -y curl gzip ca-certificates libcap2-bin
  else
    echo "apt-get not found; please install curl, gzip, ca-certificates and libcap manually." >&2
  fi
}

normalize_version() {
  version="$1"
  version="${version#v}"
  if [ -z "$version" ]; then
    echo "Unable to determine Mihomo version" >&2
    exit 1
  fi
  printf '%s\n' "$version"
}

detect_asset() {
  case "$(uname -m)" in
    x86_64|amd64)
      printf 'mihomo-linux-amd64-compatible-v%s.gz\n' "$1"
      ;;
    aarch64|arm64)
      printf 'mihomo-linux-arm64-v%s.gz\n' "$1"
      ;;
    armv7l|armv7*)
      printf 'mihomo-linux-armv7-v%s.gz\n' "$1"
      ;;
    *)
      echo "Unsupported CPU architecture: $(uname -m)" >&2
      exit 1
      ;;
  esac
}

install_deps
need_cmd curl
need_cmd gzip
need_cmd mktemp
need_cmd install

if [ -z "$VERSION" ]; then
  LATEST_URL="$(curl -fsSLI -o /dev/null -w '%{url_effective}' "${REPO}/releases/latest")"
  VERSION="${LATEST_URL##*/v}"
fi

VERSION="$(normalize_version "$VERSION")"
ASSET="$(detect_asset "$VERSION")"
DOWNLOAD_URL="${REPO}/releases/download/v${VERSION}/${ASSET}"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

echo "Downloading Mihomo ${VERSION} from ${DOWNLOAD_URL}"
curl -fL --retry 3 --connect-timeout 20 -o "${TMP_DIR}/${ASSET}" "$DOWNLOAD_URL"

gzip -dc "${TMP_DIR}/${ASSET}" > "${TMP_DIR}/mihomo"
chmod 0755 "${TMP_DIR}/mihomo"
run_as_root install -m 0755 "${TMP_DIR}/mihomo" "$INSTALL_PATH"

echo "Mihomo installed to ${INSTALL_PATH}"
"$INSTALL_PATH" -v
