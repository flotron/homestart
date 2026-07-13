# Changelog

All notable HomeStart changes should be recorded here before building a new
installer or update package. Keep entries focused on user-visible behavior,
packaging, security, and migration notes.

## 20260713-1445

- Redesigned the File Browser into a more visual desktop-style explorer.
- Added a large grid view for folders and files, with a list view toggle for
  dense directory inspection.
- Added a cleaner file sidebar with friendly location labels and full paths.
- Moved upload, new folder, paste, up, roots, and view controls into the File
  Browser workspace header.
- Added a visible Upload button while keeping drag-and-drop uploads.
- Added folder/file counts and current location naming above the file grid.

## 20260710-1735

- Prepared HomeStart for public GitHub distribution.
- Expanded `README.md` with project description, installation guide, basic
  usage tutorial, configuration notes, update flow, packaging, and security
  model.
- Added `.gitignore` to keep local config, runtime databases, packages,
  backups, logs, and local Codex/plugin artifacts out of source control.

## 20260710-1720

- Installer and update archives now include `package.json` metadata with
  `package_type`.
- The HomeStart updater now requires package metadata and accepts only packages
  marked as `update`.
- Uploading an installer archive to Settings > Updates is now rejected with a
  clear error instead of being applied as an update.

## 20260710-1715

- Ookla Speedtest results are now stored locally in `data/homestart.db`.
- Added `/api/speedtest/history` for previous Speedtest runs.
- Speedtest UI now loads the latest stored result and shows a clickable history
  table.
- History is local runtime data, so it is preserved by updates and excluded
  from installer/update packages.

## 20260710-1710

- File Browser path display is now an address bar.
- Users can type or paste a full path and press Enter or `Go` to navigate
  directly, with the backend still enforcing configured `file_roots`.

## 20260710-1705

- File Browser now supports drag-and-drop uploads into the currently open
  folder.
- Added a File Browser clipboard: `Copy` stores the selected file or folder,
  and `Paste` copies it into the current folder.
- Mounted physical disks and USB drives now appear as File Browser sidebar
  shortcuts when their mount points are inside configured `file_roots`.
- Added visible File Browser drop/operation status so the interface behaves
  more like a desktop file explorer.
- Upload, copy, delete, and folder creation remain gated by
  `features.file_operations` and constrained to configured `file_roots`.

## 20260710-1653

- Expanded File Browser into a more OS-like explorer while keeping operations
  constrained to configured `file_roots`.
- Added `features.file_operations` to control create, copy, and delete
  capabilities.
- Added `New folder` support.
- Added per-file actions for open/view, copy, and delete.
- Delete now requires strong confirmation by typing `DELETE <name>`.
- Copy prompts for a destination folder or destination path.
- File open responses now prefer inline display so the browser tries to open
  supported files instead of downloading them immediately.
- Updated the example configuration so installers can expose broader or
  narrower file roots without hardcoded personal paths.

## 20260710-1636

- Reworked Codex CLI supported-app detection to avoid hardcoded user home
  paths from development machines.
- Codex now looks for authenticated config in a portable order:
  `supported_apps.codex.codex_home`, `CODEX_HOME`, `$HOME/.codex`, standard
  `/home/*/.codex` locations, and `/root/.codex`.
- If multiple authenticated Codex homes are found, HomeStart now asks the user
  to configure `supported_apps.codex.codex_home` instead of guessing.
- When HomeStart runs as root, Codex commands run as the owner of the selected
  auth directory to avoid creating root-owned files in a user profile.
- Removed personal path assumptions from Speedtest/Codex supported-app
  wrappers.

## 20260710-1623

- Fixed Apps action buttons overflowing after `Uninstall` was added.
- Increased app card minimum width from 220px to 260px.
- Changed action layout to wrap buttons when a card is too narrow.
- Added stable button minimum widths so actions no longer spill into adjacent
  cards.

## 20260710-1608

- Clarified Supported apps as visual wrappers/adaptations around CLI tools.
- Added a real Ookla Speedtest supported-app wrapper at `/speedtest`.
- Speedtest can now run the installed `speedtest` CLI from HomeStart and show
  download, upload, ping, ISP, and selected server details.
- Fixed Codex CLI Chat configuration that previously relied on development
  machine paths.
- Updated Codex CLI Chat toward portable runtime paths; unauthenticated Codex
  installations now report that authentication is required instead of failing
  on missing local development paths.

## 20260710-1520

- Status now renders a separate usage bar for each detected GPU.
- GPU rows show per-device usage percentage plus frequency and memory details
  when those counters are available.

## 20260710-1510

- Apps now expose Docker running state in `/api/apps`.
- Docker apps marked as stopped or exited now disable the `Open` button.
- After a successful Docker `Stop`, the Apps view immediately greys out `Open`
  before refreshing from the backend.
- `Stop` is disabled for Docker containers that are already stopped; `Restart`
  remains available.

## 20260710-1508

- Added this changelog to the installable and update packages so future Codex
  chats can quickly recover project history from the distributed artifact.
- Updated the package builder to copy `CHANGELOG.md` into every generated
  installer and update archive.

## 20260710-1506

- Fixed Apps cards so `Open`, `Stop`, `Restart`, and `Uninstall` stay inside
  each card after adding the uninstall action.
- Changed app action layout to a stable two-column grid for narrower screens.
- Hardened package validation to reject temporary backup files such as
  `*.bak`, `*.bak-*`, and `*.backup`.
- Rebuilt clean installer and update packages after confirming they do not
  include local/private paths.

## 20260710-1457

- Added the Apps `Uninstall` action.
- Docker uninstall removes only the container with `docker rm -f`; images and
  volumes are preserved.
- Native Linux and supported apps require an explicit `uninstall_command` in
  `config.json` before HomeStart enables uninstall.
- Added strong uninstall confirmation requiring the exact text
  `UNINSTALL <app name>`.
- Hardened package generation and update validation so releases refuse local
  or private files such as `config.json`, `data/`, `dist/`, `backups/`, Git
  metadata, SQLite databases, logs, environment files, and installed service
  units.
- Updated `README.md` and `config.example.json` for uninstall and packaging
  behavior.

