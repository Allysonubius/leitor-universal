"""Atualização automática a partir das releases do GitHub.

Fluxo: consulta a última release → compara versões → baixa o instalador →
confere o SHA-256 publicado em SHA256SUMS.txt → executa o instalador e encerra o app.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from . import __version__

REPOSITORY = "Allysonubius/leitor-universal"
LATEST_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases"
INSTALLER_SUFFIX = "-setup.exe"
CHECKSUMS_NAME = "SHA256SUMS.txt"
USER_AGENT = f"LeitorUniversal/{__version__}"


class UpdateError(Exception):
    pass


@dataclass
class Release:
    version: str
    notes: str
    page_url: str
    installer_name: str | None
    installer_url: str | None
    checksums_url: str | None


def parse_version(text: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", text.split("-")[0])
    return tuple(int(n) for n in numbers[:3]) or (0,)


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


def is_installed_build() -> bool:
    """Só a versão empacotada (instalador) pode se substituir sozinha."""
    return bool(getattr(sys, "frozen", False))


def _request(url: str, timeout: float = 15):
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "application/vnd.github+json",
    })
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_latest_release() -> Release:
    try:
        with _request(LATEST_API) as resp:
            data = json.load(resp)
    except Exception as exc:
        raise UpdateError(f"Não foi possível consultar o GitHub: {exc}") from exc
    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    installer = next((n for n in assets if n.lower().endswith(INSTALLER_SUFFIX)), None)
    return Release(
        version=data.get("tag_name", "").lstrip("vV"),
        notes=(data.get("body") or "").strip(),
        page_url=data.get("html_url", RELEASES_PAGE),
        installer_name=installer,
        installer_url=assets.get(installer) if installer else None,
        checksums_url=assets.get(CHECKSUMS_NAME),
    )


def expected_checksum(release: Release) -> str:
    if not release.checksums_url:
        raise UpdateError("A release não publica SHA256SUMS.txt; atualização cancelada por segurança.")
    with _request(release.checksums_url) as resp:
        for line in resp.read().decode("utf-8", "replace").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].lstrip("*") == release.installer_name:
                return parts[0].lower()
    raise UpdateError("O instalador não consta em SHA256SUMS.txt.")


def download_installer(release: Release, progress=None) -> Path:
    if not release.installer_url:
        raise UpdateError("A release não possui instalador para Windows.")
    checksum = expected_checksum(release)
    target_dir = Path(tempfile.mkdtemp(prefix="leitor-update-"))
    target = target_dir / release.installer_name
    digest = hashlib.sha256()
    with _request(release.installer_url, timeout=60) as resp, target.open("wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(256 * 1024):
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if digest.hexdigest().lower() != checksum:
        target.unlink(missing_ok=True)
        raise UpdateError("O arquivo baixado não confere com o SHA-256 publicado.")
    return target


def launch_installer(installer: Path) -> None:
    """Instalação silenciosa; o instalador fecha o app e o reabre ao terminar."""
    subprocess.Popen(
        [str(installer), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
        close_fds=True,
    )


class UpdateCheckThread(QThread):
    finished_check = Signal(object, str)  # (Release | None, mensagem de erro)

    def run(self) -> None:
        try:
            self.finished_check.emit(fetch_latest_release(), "")
        except Exception as exc:
            self.finished_check.emit(None, str(exc))


class UpdateDownloadThread(QThread):
    progress = Signal(int, int)
    done = Signal(str, str)  # (caminho do instalador, mensagem de erro)

    def __init__(self, release: Release, parent=None):
        super().__init__(parent)
        self.release = release

    def run(self) -> None:
        try:
            path = download_installer(self.release, lambda d, t: self.progress.emit(d, t))
            self.done.emit(str(path), "")
        except Exception as exc:
            self.done.emit("", str(exc))
