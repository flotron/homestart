#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo bash "$0" "$@"
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR_DEFAULT="/opt/homestart"
PORT_DEFAULT="80"

echo "HomeStart installer"
echo
echo "Occupied TCP ports:"
if command -v ss >/dev/null 2>&1; then
  ss -ltnH | awk '{print $4}' | sed -E 's/.*:([0-9]+)$/\1/' | sort -n | uniq | sed 's/^/  /'
else
  echo "  ss not available"
fi
echo

read -r -p "Install directory [${INSTALL_DIR_DEFAULT}]: " INSTALL_DIR
INSTALL_DIR="${INSTALL_DIR:-$INSTALL_DIR_DEFAULT}"
if [[ "$INSTALL_DIR" != /* ]]; then
  echo "Install directory must be an absolute path, for example: /opt/homestart" >&2
  echo "If you wanted to use port ${INSTALL_DIR}, press Enter for the install directory and type ${INSTALL_DIR} at the port prompt." >&2
  exit 1
fi

read -r -p "Dashboard port [${PORT_DEFAULT}]: " PORT
PORT="${PORT:-$PORT_DEFAULT}"

if ! [[ "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1 || PORT > 65535 )); then
  echo "Invalid port: $PORT" >&2
  exit 1
fi
if command -v ss >/dev/null 2>&1 && ss -ltnH | awk '{print $4}' | sed -E 's/.*:([0-9]+)$/\1/' | grep -qx "$PORT"; then
  read -r -p "Port ${PORT} appears to be occupied. Continue anyway? [y/N]: " CONFIRM_PORT
  if [[ ! "$CONFIRM_PORT" =~ ^[Yy]$ ]]; then
    echo "Installation cancelled. Run installer again and choose a free port." >&2
    exit 1
  fi
fi

if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  apt-get install -y python3 python3-yaml iproute2 procps util-linux
fi

mkdir -p "$INSTALL_DIR/static" "$INSTALL_DIR/scripts" "$INSTALL_DIR/data"
install -m 0755 "$SRC_DIR/app.py" "$INSTALL_DIR/app.py"
install -m 0644 "$SRC_DIR/config.example.json" "$INSTALL_DIR/config.example.json"
install -m 0644 "$SRC_DIR/README.md" "$INSTALL_DIR/README.md"
install -m 0644 "$SRC_DIR/homestart.service.example" "$INSTALL_DIR/homestart.service.example"
install -m 0755 "$SRC_DIR/install.sh" "$INSTALL_DIR/install.sh"
if [[ -f "$SRC_DIR/package.json" ]]; then
  install -m 0644 "$SRC_DIR/package.json" "$INSTALL_DIR/package.json"
fi

if [[ -d "$SRC_DIR/scripts" ]]; then
  cp -a "$SRC_DIR/scripts/." "$INSTALL_DIR/scripts/"
fi
cp -a "$SRC_DIR/static/." "$INSTALL_DIR/static/"

if [[ ! -f "$INSTALL_DIR/config.json" ]]; then
  cp "$INSTALL_DIR/config.example.json" "$INSTALL_DIR/config.json"
fi

cat >/etc/systemd/system/homestart.service <<SERVICE
[Unit]
Description=HomeStart app launcher
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/app.py
Environment=PORT=${PORT}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable --now homestart.service

echo
echo "HomeStart installed."
echo "Open: http://$(hostname -I | awk '{print $1}'):${PORT}"
echo "Config: ${INSTALL_DIR}/config.json"
