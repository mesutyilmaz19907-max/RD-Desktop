# RD Desktop 1.0.0

[![CI](https://github.com/mesutyilmaz19907-max/RD-Desktop/actions/workflows/ci.yml/badge.svg)](https://github.com/mesutyilmaz19907-max/RD-Desktop/actions/workflows/ci.yml)

**First public release: [v1.0.0](https://github.com/mesutyilmaz19907-max/RD-Desktop/releases/tag/v1.0.0).**

RD Desktop is a modern desktop client for Real-Debrid, built with a single shared Python/Tk codebase and packaged separately for Windows and Linux.

It brings common Real-Debrid tasks into a clean desktop interface, including torrent management, magnet and `.torrent` uploads, file selection, link unrestricting, download management, history, account information, and secure device-based authentication.

The project is designed to stay lightweight, responsive, and easy to use while keeping platform-specific behavior properly separated between Windows and Linux.

**Important:** RD Desktop is only a client for the Real-Debrid service. It does not provide downloads, hosting, cached content, or premium access by itself. A valid **Real-Debrid Premium account is required** for the application to be useful. Without an active Real-Debrid Premium subscription, most of the app's functionality will not work.

RD Desktop is an independent project and is not affiliated with or endorsed by Real-Debrid.

## Supported platforms

- Windows 10/11, x64
- Linux desktop environments with Python 3.10+, Tk 8.6+, `xdg-open`, and a working Secret Service/keyring backend

The source is shared. Platform-specific behavior is isolated behind small OS helpers rather than maintaining separate Windows and Linux forks.

## Authentication

RD Desktop uses Real-Debrid's open-source OAuth device authorization flow. On first sign-in it obtains account-bound OAuth credentials, then stores secrets through the operating system rather than in plaintext configuration.

- Windows: DPAPI protects OAuth secrets for the current Windows user.
- Linux: Python `keyring` stores OAuth secrets through the desktop credential service. There is deliberately no plaintext/base64 fallback.

If Linux has no usable keyring backend, RD Desktop can start but persistent authorization will fail with an explanatory error instead of writing secrets insecurely.

## Project layout

```text
rdclient/
  api.py               Real-Debrid OAuth and REST client
  app.py               preserved modern Tk UI and controller integration
  config.py            public settings + protected secret storage
  constants.py         application/API constants and version
  downloads.py         resumable transfer engine and queue persistence
  launcher.py          logging, startup checks, application entry point
  platform_support.py  Windows/Linux paths, open-file/folder, theme helpers
  ui_assets.py         packaged UI icon loader
  ui_theme.py          theme detection and Tk styling
  i18n.py              translations
packaging/
  windows/build.ps1
  linux/build.sh
  linux/package.py
  checksums.py
.github/workflows/
  ci.yml
  build.yml
  release.yml
tests/
```

## Data locations

Windows stores application data beneath `%LOCALAPPDATA%\RD Desktop`.

Linux follows XDG paths:

- configuration: `${XDG_CONFIG_HOME:-~/.config}/rd-desktop`
- application data/log/download queue: `${XDG_DATA_HOME:-~/.local/share}/rd-desktop`

Private Linux directories/files created by RD Desktop are restricted to the current user where applicable.

## Run from source

Create a virtual environment, then install the project:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m rdclient
```

Linux:

```bash
source .venv/bin/activate
python -m pip install -e .
python -m rdclient
```

On Linux, install your distribution's Tk package if Python was built without Tk support (commonly `python3-tk`). A desktop credential service such as GNOME Keyring or another `keyring`-compatible backend must also be available for persistent login.

The compatibility launcher also remains available:

```bash
python "RD Desktop.py"
```

## Build release artifacts

Build each operating-system artifact on that operating system. Do not cross-build the Windows executable from Linux or vice versa.

Windows PowerShell:

```powershell
.\packaging\windows\build.ps1
```

Linux:

```bash
./packaging/linux/build.sh
```

The Windows build produces `RD-Desktop-Windows-x64.zip`. A local Linux build produces `RD-Desktop-Linux-x86_64.tar.gz`. CI includes the target distro in Linux archive names so builds from different system libraries stay distinguishable.

After a Linux build, create a native package on the matching distribution:

```bash
# Debian/Ubuntu; requires dpkg-deb
python packaging/linux/package.py --format deb --target ubuntu-24.04

# Fedora; requires rpmbuild
python packaging/linux/package.py --format rpm --target fedora-44
```

Native packages install the application in `/opt/rd-desktop`, provide the `rd-desktop` command, and add an application-menu entry. They declare a minimum glibc version matching their build environment. Use the package for your distro; a frozen executable built with newer system libraries may not work on an older distro. A working desktop keyring is still needed for persistent login.

## Continuous integration and downloads

Every push and pull request runs syntax/undefined-name checks, tests on Windows and Ubuntu with Python 3.10, 3.12, and 3.14, and the following native package builds:

| Target | Architecture | Build artifacts |
| --- | --- | --- |
| Ubuntu 22.04 | x86_64 | `.deb`, `.tar.gz` |
| Ubuntu 24.04 | x86_64 | `.deb`, `.tar.gz` |
| Debian 12 | x86_64 | `.deb`, `.tar.gz` |
| Debian 13 | x86_64 | `.deb`, `.tar.gz` |
| Fedora 44 | x86_64 | `.rpm`, `.tar.gz` |
| Windows | x64 | `.zip` |
| Python package | platform independent source/wheel | `.whl`, source `.tar.gz` |

Each Linux build uses its distro's own Python and libraries in a container, runs the full test suite under Xvfb, installs the resulting native package, and checks the installed executable. The Windows build checks the packaged executable. The Python package job installs the wheel into a clean virtual environment outside the source tree and checks the bundled icon data.

Download build artifacts and their SHA-256 manifests from the **Artifacts** section of a successful [CI run](https://github.com/mesutyilmaz19907-max/RD-Desktop/actions/workflows/ci.yml). CI artifacts are retained for 14 days. The **Run workflow** button can also start CI manually.

Release tags, manual release runs, and version/release-workflow changes on `main` use the same package-build workflow. After all package builds pass, the release workflow publishes the distro packages, archives, Python packages, and a combined `SHA256SUMS` file. If the current version already belongs to another commit, a normal CI change skips publishing; bump the version before publishing the next release.

## Tests

```bash
python -m pytest
```

On a headless Linux machine:

```bash
xvfb-run -a python -m pytest
```

The test suite covers OAuth credential polling, incomplete/truncated downloads, secure configuration migration, duplicate torrent checks, and native UI interactions.

## Behavioral notes

- Native Explorer `.torrent` drag-and-drop remains Windows-only. Linux uses the Upload torrents action; the UI reflects that capability.
- Download completion is verified before a `.part` file can be promoted to its final filename.
- Download queue persistence uses atomic, serialized writes.
- Interrupted active jobs are persisted as resumable/paused work during shutdown.
- Open File/Open Folder uses the native Windows shell on Windows and `xdg-open` on Linux.
- Real-Debrid OAuth/API failures are logged with useful status/error information instead of treating every authorization error as an endless pending state.

## Logging

Startup and API diagnostics are written to `rd-desktop.log` in the platform application-data directory. OAuth tokens and client secrets are not intentionally written to the log.

## License

No project-level license has been specified for the application code. `assets/icons/LICENSE.txt` covers the bundled icon assets.
