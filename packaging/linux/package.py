"""Package a tested PyInstaller directory as a native DEB or RPM."""
from __future__ import annotations

import argparse
from importlib.metadata import version as installed_version
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
HOMEPAGE = 'https://github.com/mesutyilmaz19907-max/RD-Desktop'


def stage_files(destination: Path, bundle: Path) -> None:
    shutil.copytree(bundle, destination / 'opt/rd-desktop', symlinks=True)
    files = {
        ROOT / 'packaging/linux/rd-desktop.desktop': 'usr/share/applications/rd-desktop.desktop',
        ROOT / 'assets/realdebrid-logo.png': 'usr/share/pixmaps/rd-desktop.png',
        ROOT / 'README.md': 'usr/share/doc/rd-desktop/README.md',
        ROOT / 'assets/icons/LICENSE.txt': 'usr/share/doc/rd-desktop/icons-LICENSE.txt',
    }
    for source, relative in files.items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, path)
    executable = destination / 'usr/bin/rd-desktop'
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.symlink_to('/opt/rd-desktop/RD-Desktop')


def build_deb(stage: Path, version: str, target: str, glibc: str, output: Path) -> Path:
    control = stage / 'DEBIAN/control'
    control.parent.mkdir()
    installed_kib = (sum(p.stat().st_size for p in stage.rglob('*')
                         if p.is_file() and not p.is_symlink()) + 1023) // 1024
    control.write_text(
        'Package: rd-desktop\n'
        f'Version: {version}-1\n'
        'Section: net\nPriority: optional\nArchitecture: amd64\n'
        'Maintainer: RD Desktop contributors <343665499+mesutyilmaz19907-max@users.noreply.github.com>\n'
        f'Installed-Size: {installed_kib}\n'
        f'Depends: libc6 (>= {glibc}), libx11-6, libxext6, libxrender1, libxft2, libfontconfig1, xdg-utils\n'
        'Recommends: gnome-keyring\n'
        f'Homepage: {HOMEPAGE}\n'
        'Description: Desktop client for Real-Debrid\n'
        ' Shared desktop client with protected credentials and resumable downloads.\n',
        encoding='utf-8',
    )
    archive = output / f'RD-Desktop-{version}-{target}-amd64.deb'
    subprocess.run(['dpkg-deb', '--build', '--root-owner-group', str(stage), str(archive)], check=True)
    subprocess.run(['dpkg-deb', '--info', str(archive)], check=True)
    return archive


def build_rpm(stage: Path, version: str, target: str, glibc: str, output: Path, work: Path) -> Path:
    top = work / 'rpmbuild'
    for name in ('BUILD', 'BUILDROOT', 'RPMS', 'SOURCES', 'SPECS', 'SRPMS'):
        (top / name).mkdir(parents=True, exist_ok=True)
    spec = top / 'SPECS/rd-desktop.spec'
    spec.write_text(
        '%global debug_package %{nil}\n'
        '%global __os_install_post %{nil}\n'
        '%global _build_id_links none\n'
        'Name: rd-desktop\n'
        f'Version: {version}\n'
        'Release: 1%{?dist}\n'
        'Summary: Desktop client for Real-Debrid\n'
        'License: LicenseRef-Unspecified\n'
        f'URL: {HOMEPAGE}\n'
        'BuildArch: x86_64\n'
        'AutoReqProv: no\n'
        f'Requires: glibc >= {glibc}\n'
        'Requires: libX11, libXext, libXrender, libXft, fontconfig, xdg-utils\n'
        'Suggests: gnome-keyring\n'
        '\n%description\n'
        'Desktop client with protected credentials and resumable downloads.\n'
        'The application code has no project-level license specified.\n'
        '\n%prep\n\n%build\n\n%install\n'
        'mkdir -p "%{buildroot}"\n'
        f'cp -a {shlex.quote(str(stage))}/. "%{{buildroot}}/"\n'
        '\n%files\n%defattr(-,root,root,-)\n'
        '/opt/rd-desktop\n/usr/bin/rd-desktop\n'
        '/usr/share/applications/rd-desktop.desktop\n'
        '/usr/share/pixmaps/rd-desktop.png\n'
        '/usr/share/doc/rd-desktop\n',
        encoding='utf-8',
    )
    subprocess.run(['rpmbuild', '-bb', '--define', f'_topdir {top}', str(spec)], check=True)
    built = list((top / 'RPMS').rglob('*.rpm'))
    if len(built) != 1:
        raise RuntimeError(f'Expected one RPM, found {len(built)}')
    archive = output / f'RD-Desktop-{version}-{target}-x86_64.rpm'
    shutil.copy2(built[0], archive)
    subprocess.run(['rpm', '--query', '--package', '--info', str(archive)], check=True)
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--format', required=True, choices=('deb', 'rpm'))
    parser.add_argument('--target', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]*', args.target):
        parser.error('--target must be a distro identifier such as ubuntu-24.04')
    if platform.system() != 'Linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
        parser.error('native packages must be built on Linux x86_64')
    libc, glibc = platform.libc_ver()
    if libc != 'glibc' or not re.fullmatch(r'\d+(\.\d+)+', glibc):
        parser.error('could not determine the glibc runtime requirement')
    version = installed_version('rd-desktop')
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        parser.error('native release packages require a major.minor.patch project version')
    output = ROOT / 'dist'
    bundle = output / 'RD-Desktop'
    if not (bundle / 'RD-Desktop').is_file():
        parser.error('run packaging/linux/build.sh before creating a native package')
    build = ROOT / 'build'
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='native-package-', dir=build) as directory:
        work = Path(directory)
        stage = work / 'stage'
        stage_files(stage, bundle)
        if args.format == 'deb':
            archive = build_deb(stage, version, args.target, glibc, output)
        else:
            archive = build_rpm(stage, version, args.target, glibc, output, work)
    print(archive)


if __name__ == '__main__':
    main()
