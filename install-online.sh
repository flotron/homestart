#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="${HOMESTART_REPOSITORY:-flotron/homestart}"
VERSION="${HOMESTART_VERSION:-latest}"
DOWNLOAD_ROOT="https://github.com/${REPOSITORY}/releases"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

if [[ "$VERSION" == "latest" ]]; then
  RELEASE_URL="${DOWNLOAD_ROOT}/latest/download"
else
  VERSION="${VERSION#v}"
  RELEASE_URL="${DOWNLOAD_ROOT}/download/v${VERSION}"
fi

download() {
  local url="$1"
  local destination="$2"
  if command -v curl >/dev/null 2>&1; then
    curl --fail --location --silent --show-error --retry 3 \
      --output "$destination" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget --quiet --tries=3 --output-document="$destination" "$url"
  else
    echo "HomeStart requires curl or wget to download the installer." >&2
    exit 1
  fi
}

echo "Downloading the HomeStart installer..."
download "${RELEASE_URL}/homestart-installer.tar.gz" "$WORK_DIR/homestart-installer.tar.gz"
download "${RELEASE_URL}/SHA256SUMS" "$WORK_DIR/SHA256SUMS"

if ! command -v sha256sum >/dev/null 2>&1; then
  echo "sha256sum is required to verify the HomeStart installer." >&2
  exit 1
fi

CHECKSUM_LINE="$(grep -E '  homestart-installer\.tar\.gz$' "$WORK_DIR/SHA256SUMS" || true)"
if [[ -z "$CHECKSUM_LINE" ]]; then
  echo "The release does not contain a checksum for homestart-installer.tar.gz." >&2
  exit 1
fi
(
  cd "$WORK_DIR"
  printf '%s\n' "$CHECKSUM_LINE" | sha256sum --check -
)

tar -xzf "$WORK_DIR/homestart-installer.tar.gz" -C "$WORK_DIR"
if [[ ! -x "$WORK_DIR/homestart/install.sh" ]]; then
  echo "The downloaded archive is not a valid HomeStart installer." >&2
  exit 1
fi

echo "Installer verified. Installing HomeStart..."
HOMESTART_NONINTERACTIVE="${HOMESTART_NONINTERACTIVE:-1}" \
  bash "$WORK_DIR/homestart/install.sh"
