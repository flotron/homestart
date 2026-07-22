# HomeStart

[![Checks](https://github.com/flotron/homestart/actions/workflows/checks.yml/badge.svg)](https://github.com/flotron/homestart/actions/workflows/checks.yml)

HomeStart is a small self-hosted dashboard for homelabs, local servers, and
small office machines. It is written with the Python standard library plus
PyYAML, and is designed to run as a `systemd` service on a trusted LAN.

It gives you a browser UI to inspect the host, open local apps, manage Docker
containers, browse files, run supported CLI wrappers such as Ookla Speedtest,
and apply local or GitHub release updates without bundling private runtime data.

## Features

- Professional overview with health state, local alerts, seven days of CPU, memory, and GPU history, physical disks, processes, and Docker resources.
- Apps dashboard: Docker discovery, native/supported app cards, open/stop/restart/uninstall actions.
- Docker support: detects published ports, including stopped containers.
- Native web discovery: detects Apache/Nginx virtual hosts from enabled config files.
- File Browser: Windows-like navigation, full path address bar, physical disk/USB shortcuts, drag and drop, copy/paste, rename, recoverable trash, downloads, folder ZIPs, and new folders.
- Docker logs and curated installation templates with suggested ports and volumes.
- Configurable theme, accent, density, dashboard labels, and alert thresholds.
- Manual downloadable backups for configuration, history, and custom icons.
- Custom app icons stored locally under `data/`.
- Settings: network interface configuration through netplan, GitHub release update checks, and update uploads.
- Supported apps:
  - Ookla Speedtest CLI wrapper with stored local history.
- Safe packaging: installer/update archives exclude local runtime data.

## Security Model

HomeStart is intended for trusted LAN use. Do not expose it directly to the
public internet without adding authentication, TLS, and a reverse proxy.

Actions such as Docker stop/restart, app uninstall, file operations, network
changes, and update installation can affect the host. Use conservative
`config.json` settings for shared or less trusted environments.

Local runtime data is intentionally not part of releases:

- `config.json`
- `data/`
- `dist/`
- `backups/`
- `.env`
- SQLite databases
- logs
- installed `homestart.service`

## Quick Start

Clone the repository:

```sh
git clone https://github.com/flotron/homestart.git
cd homestart
```

Install dependencies:

```sh
sudo apt-get update
sudo apt-get install -y python3 python3-yaml iproute2 procps util-linux
```

Create local configuration:

```sh
cp config.example.json config.json
```

Run manually:

```sh
PORT=8080 python3 app.py
```

Open:

```text
http://SERVER_IP:8080
```

## Install as a Service

The packaged installer is the recommended path for another machine:

```sh
./scripts/build_package.sh
```

Copy `dist/homestart-installer-*.tar.gz` to the target server, then run:

```sh
tar -xzf homestart-installer-*.tar.gz
cd homestart
sudo ./install.sh
```

The installer asks for:

- install directory, default `/opt/homestart`
- dashboard port, default `80`

It creates and starts `homestart.service`.

Useful service commands:

```sh
sudo systemctl status homestart.service
sudo systemctl restart homestart.service
sudo journalctl -u homestart.service -f
```

## Updating an Existing Install

Build packages:

```sh
./scripts/build_package.sh
```

Use only the update archive in the web UI:

```text
homestart-update-VERSION.tar.gz
```

Then in HomeStart:

1. Open `Settings`.
2. Select the update `.tar.gz`.
3. Apply the update.
4. HomeStart restarts automatically.

Updates preserve:

- `config.json`
- `data/`
- local Speedtest history
- custom app icons
- local backups and runtime files

The updater validates package metadata and rejects installer archives.

HomeStart can also check GitHub releases from `Settings > Updates`. The
configured repository is `updates.github_repo` in `config.json` and defaults to
`flotron/homestart`. Online updates expect the latest GitHub release to include
an asset named like:

```text
homestart-update-VERSION.tar.gz
```

## Basic Usage

### Status

Use `Status` to see host health: CPU, RAM, GPU, physical disks, Docker resource
usage, and process/resource tables.

### Apps

Use `Apps` to discover and control services:

- `Open`: opens the app URL.
- `Stop`: stops a running Docker container.
- `Restart`: restarts a Docker container.
- `Uninstall`: removes only the Docker container, or runs an explicit native
  uninstall command when configured.

Docker images and volumes are preserved by uninstall.

If HomeStart cannot find a useful app icon, hover the app card and use the
small icon upload control. Uploaded icons are local runtime data and are not
included in release packages.

### File Browser

Use `File Browser` like a lightweight OS explorer:

- type a full path in the address bar and press Enter
- browse configured roots and mounted drives
- mount unmounted partitions read-only under `/mnt/homestart` when enabled
- drag files into the main pane to upload
- copy an item and paste it into another folder
- create folders
- open/view files inline when the browser supports them
- delete with a simple confirmation prompt

All file operations are constrained by `file_roots`. Unmounted partitions cannot
be browsed directly by Linux; HomeStart mounts them read-only with
`ro,nosuid,nodev,noexec` before opening them.

### Settings

Use `Settings` for network changes and updates. Network changes can disconnect
the host, so the UI asks for explicit confirmation.

### Supported Apps

Supported apps are visual wrappers around local CLI tools.

Ookla Speedtest requires the official `speedtest` CLI. Results are stored in
the local HomeStart database and shown in the Speedtest history table.

## Configuration

Copy and edit:

```sh
cp config.example.json config.json
```

Important options:

- `dashboard.title` and `dashboard.subtitle`: text shown in the UI.
- `dashboard.host`: host used for generated app links. Leave empty to auto-detect.
- `features.docker_actions`: enable Docker stop/restart actions.
- `features.file_browser`: enable File Browser.
- `features.file_operations`: enable create/copy/delete/upload operations.
- `features.file_mounts`: enable read-only mounting of unmounted partitions.
- `features.app_uninstall`: enable uninstall actions.
- `file_roots`: folders the File Browser can access.
- `services`: systemd units shown in status.
- `apps`: manually configured app cards.
- `apps[].app_type`: `docker`, `native`, or `supported`.
- `apps[].requirements`: optional command/path checks.
- `apps[].uninstall_command`: explicit uninstall command for native/supported apps.

Mounted disks and USB drives appear as sidebar shortcuts when their mount points
are inside configured `file_roots`.

## Packaging

Build both installer and update archives:

```sh
./scripts/build_package.sh VERSION
```

Output:

```text
dist/homestart-installer-VERSION.tar.gz
dist/homestart-update-VERSION.tar.gz
```

Each archive includes `CHANGELOG.md` and package metadata. The updater accepts
only archives marked as `package_type: update`.

## Development Notes

Before publishing a release:

1. Update `CHANGELOG.md`.
2. Run the package builder.
3. Confirm archives do not include local data.
4. Test install/update flow on a clean machine or VM when possible.

Automated checks and tagged release packaging are defined under
`.github/workflows/`. See [CONTRIBUTING.md](CONTRIBUTING.md) and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for more detail.


