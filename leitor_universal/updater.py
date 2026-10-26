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
RELEASES_API = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=30"
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
    published: str = ""


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


def _clean_notes(body: str) -> str:
    """Remove linhas geradas automaticamente pelo GitHub (ex.: "Full Changelog")."""
    lines = [l for l in (body or "").splitlines() if "full changelog" not in l.lower()]
    return "\n".join(lines).strip()


def _to_release(data: dict) -> Release:
    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    installer = next((n for n in assets if n.lower().endswith(INSTALLER_SUFFIX)), None)
    return Release(
        version=data.get("tag_name", "").lstrip("vV"),
        notes=_clean_notes(data.get("body", "")),
        page_url=data.get("html_url", RELEASES_PAGE),
        installer_name=installer,
        installer_url=assets.get(installer) if installer else None,
        checksums_url=assets.get(CHECKSUMS_NAME),
        published=(data.get("published_at") or "")[:10],
    )


def combine_notes(releases: list[Release]) -> str:
    """Novidades de todas as versões pendentes, da mais nova para a mais antiga (Markdown)."""
    parts = []
    for r in releases:
        date = "/".join(reversed(r.published.split("-"))) if r.published else ""
        header = f"### Versão {r.version}" + (f" — {date}" if date else "")
        parts.append(f"{header}\n\n{r.notes or '- Melhorias e correções.'}")
    return "\n\n".join(parts)


def pending_update(releases_json: list[dict], current: str = __version__) -> Release | None:
    """Última versão mais nova que a atual, com as notas acumuladas das versões puladas."""
    releases = [_to_release(d) for d in releases_json if not d.get("draft") and not d.get("prerelease")]
    newer = sorted((r for r in releases if is_newer(r.version, current)),
                   key=lambda r: parse_version(r.version), reverse=True)
    if not newer:
        return None
    latest = newer[0]
    latest.notes = combine_notes(newer)
    return latest


def fetch_update() -> Release | None:
    try:
        with _request(RELEASES_API) as resp:
            data = json.load(resp)
    except Exception as exc:
        raise UpdateError(f"Não foi possível consultar o GitHub: {exc}") from exc
    return pending_update(data)


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
            self.finished_check.emit(fetch_update(), "")
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
