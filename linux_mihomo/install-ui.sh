#!/usr/bin/env bash
set -euo pipefail

BRANCH="${BRANCH:-gh-pages}"
REPO="${REPO:-https://github.com/metacubex/metacubexd}"
BACKUP="${BACKUP:-1}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
MIHOMO_DIR="${MIHOMO_DIR:-${SCRIPT_DIR}/mihomo}"
UI_DIR="${UI_DIR:-ui-metacubexd}"

usage() {
  cat <<EOF
Usage: ./install-ui.sh [options]

Download MetaCubeXD static dashboard into the mihomo config directory.

Options:
  --no-backup    Replace existing ${UI_DIR} without keeping a timestamped backup
  -h, --help     Show this help

Environment:
  MIHOMO_DIR=path  Mihomo config directory, default: ./mihomo next to this script
  UI_DIR=path      Target UI directory name or absolute path, default: ui-metacubexd
  BRANCH=name    Source branch, default: gh-pages
  REPO=url       Source repository, default: https://github.com/metacubex/metacubexd
  BACKUP=0|1     Keep backup when target exists, default: 1
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --no-backup)
      BACKUP=0
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

download() {
  url="$1"
  output="$2"

  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 --connect-timeout 20 -o "$output" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "$output" "$url"
  else
    echo "Missing required command: curl or wget" >&2
    exit 1
  fi
}

need_cmd tar
need_cmd mktemp

case "$UI_DIR" in
  ""|"/"|".")
    echo "Refusing unsafe UI_DIR: ${UI_DIR:-<empty>}" >&2
    exit 1
    ;;
esac

case "$MIHOMO_DIR" in
  ""|"/"|".")
    echo "Refusing unsafe MIHOMO_DIR: ${MIHOMO_DIR:-<empty>}" >&2
    exit 1
    ;;
esac

mkdir -p "$MIHOMO_DIR"

case "$UI_DIR" in
  /*)
    TARGET_DIR="$UI_DIR"
    ;;
  *)
    TARGET_DIR="${MIHOMO_DIR}/${UI_DIR}"
    ;;
esac

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

ARCHIVE="$TMP_DIR/metacubexd-${BRANCH}.tar.gz"
EXTRACT_DIR="$TMP_DIR/extract"
DOWNLOAD_URL="${REPO}/archive/refs/heads/${BRANCH}.tar.gz"

echo "Downloading MetaCubeXD from ${DOWNLOAD_URL}"
download "$DOWNLOAD_URL" "$ARCHIVE"

mkdir -p "$EXTRACT_DIR"
tar -xzf "$ARCHIVE" -C "$EXTRACT_DIR" --strip-components=1

if [ -e "$TARGET_DIR" ]; then
  if [ "$BACKUP" = "1" ]; then
    BACKUP_DIR="${TARGET_DIR}.bak.$(date +%Y%m%d-%H%M%S)"
    echo "Backing up existing ${TARGET_DIR} to ${BACKUP_DIR}"
    mv "$TARGET_DIR" "$BACKUP_DIR"
  else
    echo "Removing existing ${TARGET_DIR}"
    rm -rf "$TARGET_DIR"
  fi
fi

mv "$EXTRACT_DIR" "$TARGET_DIR"

echo "MetaCubeXD installed to ${TARGET_DIR}"
