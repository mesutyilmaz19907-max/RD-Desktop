# Changelog

## Unreleased

- Compile and verify distro-specific Ubuntu 22.04/24.04, Debian 12/13, and Fedora 44 packages in CI.
- Build native DEB/RPM installers, Windows archives, Python wheels/source distributions, and SHA-256 manifests.
- Test Python 3.10, 3.12, and 3.14 on Linux and Windows; verify native package installation and wheel assets.
- Share package build jobs with releases and skip publishing an already-released version from a different commit.

## 1.3.0

Backend rewrite with the existing modern UI retained.

- Replaced the duplicated legacy/modern application inheritance with a lean shared controller and one modern UI application.
- Rebuilt the Real-Debrid OAuth/REST client with request pacing, bounded retries, token refresh locking, response validation, and authorization diagnostics.
- Removed legacy password/2FA and private-token authentication paths from the public desktop flow.
- Added Windows DPAPI and Linux system-keyring credential backends; removed Linux plaintext/base64 storage.
- Added XDG config/data locations on Linux and migration away from the old `~/.rd-desktop/config.json` secret file.
- Rebuilt local download transfers around resumable `.part` files with completion-size validation and atomic promotion.
- Added serialized atomic queue persistence and safer restart/shutdown reconciliation.
- Added cross-platform file/folder opening and Linux desktop theme detection.
- Fixed stale folder-unrestrict download state and the Treeview empty-state overlay regression.
- Preserved unsaved form/results state when switching language.
- Kept native `.torrent` drag/drop on Windows while making the Linux UI accurately advertise upload-button behavior.
- Replaced VBS launchers with a Python package/entry point and release build scripts.
- Added Windows/Linux CI and tagged GitHub release workflows.
- Added regression tests for OAuth polling, truncated downloads, destination permissions, and legacy Linux secret migration.

## 1.3.1

- Check torrent/magnet info hashes against the existing Real-Debrid torrent list before adding.
- Skip already-existing torrents before upload, file-list polling, or automatic file selection.
- De-duplicate repeated torrents inside the same batch without extra Real-Debrid add calls.
- Show skipped items separately from failed items in the upload queue.

## 1.3.2

- Fix first Shift-click range selection in the main Treeview lists by maintaining an explicit selection anchor.
- Preserve Ctrl+Shift additive range selection and normal Ctrl-click behavior.
