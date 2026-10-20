# RD Desktop 1.3.2

RD Desktop is a desktop client for Real-Debrid with one shared Python/Tk codebase and separate Windows and Linux release builds.

The 1.3.2 source tree keeps the existing modern UI while replacing the older mixed Windows/application backend with a cross-platform core for authentication, API access, downloads, persistence, and operating-system integration.

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
.github/workflows/
  ci.yml
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

The Windows build produces `RD-Desktop-Windows-x64.zip`. The Linux build produces `RD-Desktop-Linux-x86_64.tar.gz`. Both are generated from the same source version.

GitHub Actions tests both operating systems and builds both artifacts from a release tag, a manual workflow run, or a version/release-workflow change pushed to `main`. After both builds pass, the workflow publishes a GitHub Release using the version in `pyproject.toml`.

## Tests

```bash
python -m pytest
```

On a headless Linux machine:

```bash
xvfb-run -a python -m pytest
```

The 1.3.2 source includes regression coverage for OAuth credential polling and incomplete/truncated downloads in addition to the existing UI/application tests.

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
