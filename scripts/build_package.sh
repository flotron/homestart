#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
VERSION="${1:-$(tr -d '[:space:]' < "$ROOT_DIR/VERSION")}"
WORK_DIR="$(mktemp -d)"
PACKAGE_DIR="$WORK_DIR/homestart"
INSTALLER_DIR="$WORK_DIR/installer/homestart"
UPDATE_DIR="$WORK_DIR/update/homestart"
INSTALLER="$DIST_DIR/homestart-installer-${VERSION}.tar.gz"
UPDATE="$DIST_DIR/homestart-update-${VERSION}.tar.gz"

cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

mkdir -p "$PACKAGE_DIR/static" "$PACKAGE_DIR/scripts" "$PACKAGE_DIR/docs" "$DIST_DIR"

install -m 0755 "$ROOT_DIR/app.py" "$PACKAGE_DIR/app.py"
install -m 0644 "$ROOT_DIR/config.example.json" "$PACKAGE_DIR/config.example.json"
install -m 0644 "$ROOT_DIR/README.md" "$PACKAGE_DIR/README.md"
install -m 0644 "$ROOT_DIR/CHANGELOG.md" "$PACKAGE_DIR/CHANGELOG.md"
install -m 0644 "$ROOT_DIR/CONTRIBUTING.md" "$PACKAGE_DIR/CONTRIBUTING.md"
install -m 0644 "$ROOT_DIR/VERSION" "$PACKAGE_DIR/VERSION"
install -m 0644 "$ROOT_DIR/docs/ARCHITECTURE.md" "$PACKAGE_DIR/docs/ARCHITECTURE.md"
install -m 0644 "$ROOT_DIR/homestart.service.example" "$PACKAGE_DIR/homestart.service.example"
install -m 0755 "$ROOT_DIR/install.sh" "$PACKAGE_DIR/install.sh"
cp -a "$ROOT_DIR/static/." "$PACKAGE_DIR/static/"
cp -a "$ROOT_DIR/scripts/." "$PACKAGE_DIR/scripts/"

make_manifest() {
  local package_type="$1"
  local target="$2"
  cat > "$target/package.json" <<EOF
{
  "name": "homestart",
  "version": "$VERSION",
  "package_type": "$package_type",
  "format": 1
}
EOF
}

validate_package_tree() {
  local path="$1"
  local bad
  bad="$(
    find "$path" \( \
      -name 'config.json' -o \
      -name '*.db' -o \
      -name '*.sqlite' -o \
      -name '*.sqlite-*' -o \
      -name '*.log' -o \
      -name '*.bak' -o \
      -name '*.bak-*' -o \
      -name '*.backup' -o \
      -name '.env' -o \
      -name 'homestart.service' -o \
      -name '__pycache__' -o \
      -name '.git' -o \
      -path '*/data/*' -o \
      -path '*/dist/*' -o \
      -path '*/backups/*' \
    \) -print
  )"
  if [[ -n "$bad" ]]; then
    echo "Refusing to build package with local/private files:" >&2
    echo "$bad" >&2
    exit 1
  fi
}

validate_archive() {
  local archive="$1"
  local bad
  bad="$(
    tar -tzf "$archive" | grep -E '(^|/)(config\.json|data|dist|backups|homestart\.service|\.git|__pycache__|\.env)(/|$)|\.(db|sqlite|log|bak|backup)$|\.sqlite-|\.bak-' || true
  )"
  if [[ -n "$bad" ]]; then
    echo "Refusing package archive with local/private entries:" >&2
    echo "$bad" >&2
    exit 1
  fi
}

validate_package_tree "$PACKAGE_DIR"

mkdir -p "$(dirname "$INSTALLER_DIR")" "$(dirname "$UPDATE_DIR")"
cp -a "$PACKAGE_DIR" "$INSTALLER_DIR"
cp -a "$PACKAGE_DIR" "$UPDATE_DIR"
make_manifest "installer" "$INSTALLER_DIR"
make_manifest "update" "$UPDATE_DIR"

tar -C "$(dirname "$INSTALLER_DIR")" -czf "$INSTALLER" homestart
tar -C "$(dirname "$UPDATE_DIR")" -czf "$UPDATE" homestart

validate_archive "$INSTALLER"
validate_archive "$UPDATE"

echo "$INSTALLER"
echo "$UPDATE"
