# Changelog

## 1.0.0 — 2026-10-20

First public release of RD Desktop for Windows and Linux.

- Manage Real-Debrid torrents, upload magnets and `.torrent` files, and choose which files to download.
- Skip duplicate torrents and repeated items before uploading them to Real-Debrid.
- Unrestrict links and manage resumable downloads with queue persistence, pause/resume controls, and completion checks.
- View account information and download history in a themed, multilingual desktop interface.
- Sign in through the Real-Debrid OAuth device flow, with credentials protected by Windows DPAPI or the Linux desktop keyring.
- Open files and folders through the operating system; use native `.torrent` drag-and-drop on Windows and the upload action on Linux.
- Install Windows x64 builds, Ubuntu 22.04/24.04 and Debian 12/13 DEB packages, or Fedora 44 RPM packages. Linux portable archives and Python wheel/source packages are also included.
- Verify downloads with the included `SHA256SUMS` file. CI tests supported Python versions, compiles each platform's packages, and checks native installation and startup.

A Real-Debrid Premium account is required. RD Desktop is an independent client and is not affiliated with or endorsed by Real-Debrid.
