"""Проверка обновлений через GitHub Releases.

При запуске exe в фоне спрашиваем GitHub о последнем релизе. Если его версия новее —
предлагаем «Скачать и установить? Да/Нет». При «Да» скачиваем новый exe рядом со старым,
а после закрытия кассы подменяем файл и запускаем новую версию.

Подмена без .bat: работающий exe в Windows нельзя перезаписать, но можно переименовать.
Поэтому старый файл становится AgashMarket.exe.old (удаляется при следующем запуске),
а новый встаёт на его место.
"""
import json
import logging
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QMessageBox, QProgressDialog

import config
import version

log = logging.getLogger("updater")

API = "https://api.github.com/repos/{repo}/releases/latest"
USER_AGENT = "AgashMarket-updater"


@dataclass
class Release:
    version: str
    notes: str
    asset_name: str
    asset_size: int
    download_url: str  # для публичного репозитория — прямая ссылка, для приватного — адрес API


def parse_version(text: str) -> tuple:
    """'v1.2.10' → (1, 2, 10). Нечисловые части игнорируются."""
    return tuple(int(x) for x in re.findall(r"\d+", text or ""))


def update_repo() -> str:
    return os.getenv("UPDATE_REPO", "").strip() or version.UPDATE_REPO.strip()


def current_exe() -> Optional[Path]:
    return Path(sys.executable).resolve() if config.FROZEN else None


def _request(url, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": USER_AGENT})
    if config.GITHUB_TOKEN:
        req.add_header("Authorization", f"Bearer {config.GITHUB_TOKEN}")
    return req


def release_from_json(data: dict) -> Optional[Release]:
    assets = [a for a in data.get("assets", []) if a.get("name", "").lower().endswith(".exe")]
    if not assets:
        return None
    asset = assets[0]
    url = asset["url"] if config.GITHUB_TOKEN else asset["browser_download_url"]
    return Release(version=data.get("tag_name", "").lstrip("vV"), notes=(data.get("body") or "").strip(),
                   asset_name=asset["name"], asset_size=int(asset.get("size") or 0), download_url=url)


def fetch_latest(repo: str) -> Optional[Release]:
    with urllib.request.urlopen(_request(API.format(repo=repo)), timeout=15) as resp:
        return release_from_json(json.load(resp))


def is_newer(release: Release, current: str = version.VERSION) -> bool:
    return parse_version(release.version) > parse_version(current)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _open_download(url: str):
    """Открывает скачивание. Для приватного репозитория GitHub отвечает переадресацией на
    временную ссылку — по ней идём уже без токена (с токеном хранилище отвечает ошибкой)."""
    if not config.GITHUB_TOKEN:
        return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=30)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        return opener.open(_request(url, "application/octet-stream"), timeout=30)
    except urllib.error.HTTPError as ex:
        if ex.code in (301, 302, 303, 307, 308) and ex.headers.get("Location"):
            req = urllib.request.Request(ex.headers["Location"], headers={"User-Agent": USER_AGENT})
            return urllib.request.urlopen(req, timeout=30)
        raise


def download(release: Release, target: Path, progress=None, cancelled=lambda: False) -> bool:
    """Скачивает exe во временный файл и переименовывает в target. False — отменено."""
    part = target.with_name(target.name + ".part")
    done = 0
    with _open_download(release.download_url) as resp, open(part, "wb") as out:
        total = int(resp.headers.get("Content-Length") or release.asset_size or 0)
        while True:
            if cancelled():
                break
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if cancelled():
        part.unlink(missing_ok=True)
        return False
    if (release.asset_size and done != release.asset_size) or done < 1024 * 1024:
        part.unlink(missing_ok=True)
        raise IOError(f"Файл обновления скачался не полностью ({done} из {release.asset_size} байт)")
    os.replace(part, target)
    return True


def install(new_exe: Path, exe: Path) -> None:
    """Ставит new_exe на место работающего exe (старый → .old)."""
    old = exe.with_name(exe.name + ".old")
    old.unlink(missing_ok=True)
    os.replace(exe, old)
    try:
        os.replace(new_exe, exe)
    except OSError:
        os.replace(old, exe)  # не получилось — возвращаем старую версию
        raise


def cleanup_old() -> None:
    """Удаляет остатки прошлого обновления (.old, недокачанный .part)."""
    exe = current_exe()
    if exe is None:
        return
    for suffix in (".old", ".new", ".new.part"):
        try:
            exe.with_name(exe.name + suffix).unlink(missing_ok=True)
        except OSError:
            log.warning("Не удалось удалить %s%s", exe.name, suffix)


def relaunch(exe: Path) -> None:
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(exe)], cwd=str(exe.parent), creationflags=flags, close_fds=True)


# ---------------------------------------------------------------- интерфейс

class _CheckThread(QThread):
    found = pyqtSignal(object)

    def __init__(self, repo):
        super().__init__()
        self.repo = repo

    def run(self):
        try:
            release = fetch_latest(self.repo)
            if release and is_newer(release):
                self.found.emit(release)
            else:
                log.info("Обновлений нет (текущая версия %s)", version.VERSION)
        except Exception as ex:  # нет интернета и т.п. — касса работает дальше
            log.warning("Не удалось проверить обновления: %s", ex)


class _DownloadThread(QThread):
    progress = pyqtSignal(int, int)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, release, target):
        super().__init__()
        self.release, self.target, self.stop = release, target, False

    def run(self):
        try:
            if download(self.release, self.target, self.progress.emit, lambda: self.stop):
                self.finished_ok.emit()
        except Exception as ex:
            log.exception("Ошибка скачивания обновления")
            self.failed.emit(str(ex))


class Updater:
    """Создаётся один раз при запуске кассы. После успешного скачивания выставляет
    pending_exe — main() после закрытия окон подменит exe и запустит новую версию."""

    def __init__(self, app):
        self.app = app
        self.pending_exe: Optional[Path] = None
        self._threads = []

    def check(self):
        repo = update_repo()
        if not config.FROZEN or not repo:
            return  # из исходников (python init.py) обновления не проверяем
        cleanup_old()
        thread = _CheckThread(repo)
        thread.found.connect(self._ask)
        self._threads.append(thread)
        thread.start()

    def _parent(self):
        return self.app.activeWindow()

    def _ask(self, release: Release):
        notes = release.notes[:700] + ("…" if len(release.notes) > 700 else "")
        text = (f"Доступна новая версия кассы: {release.version}\n"
                f"Сейчас установлена: {version.VERSION}\n\n"
                + (f"Что нового:\n{notes}\n\n" if notes else "")
                + "Скачать и установить?")
        answer = QMessageBox.question(self._parent(), "Обновление", text,
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer == QMessageBox.Yes:
            self._download(release)

    def _download(self, release: Release):
        exe = current_exe()
        target = exe.with_name(exe.name + ".new")
        dialog = QProgressDialog("Скачивание обновления…", "Отмена", 0, 100, self._parent())
        dialog.setWindowTitle("Обновление")
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        thread = _DownloadThread(release, target)
        self._threads.append(thread)

        def on_progress(done, total):
            mb = done / 1024 / 1024
            if total:
                dialog.setValue(int(done * 100 / total))
                dialog.setLabelText(f"Скачивание обновления… {mb:.1f} из {total / 1024 / 1024:.1f} МБ")
            else:
                dialog.setLabelText(f"Скачивание обновления… {mb:.1f} МБ")

        def on_done():
            dialog.close()
            self.pending_exe = target
            answer = QMessageBox.question(
                self._parent(), "Обновление",
                f"Версия {release.version} скачана.\nПерезапустить кассу сейчас?\n\n"
                "Если нажать «Нет», обновление установится при закрытии кассы.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer == QMessageBox.Yes:
                self.app.closeAllWindows()
                self.app.quit()

        def on_failed(message):
            dialog.close()
            QMessageBox.warning(self._parent(), "Обновление",
                                f"Не удалось скачать обновление:\n{message}\n\nКасса продолжит работу в текущей версии.")

        thread.progress.connect(on_progress)
        thread.finished_ok.connect(on_done)
        thread.failed.connect(on_failed)
        dialog.canceled.connect(lambda: setattr(thread, "stop", True))
        thread.start()

    def apply_if_pending(self) -> None:
        """Вызывается после закрытия кассы (и остановки бота)."""
        exe = current_exe()
        if not self.pending_exe or exe is None or not self.pending_exe.exists():
            return
        try:
            install(self.pending_exe, exe)
            log.info("Обновление установлено, запускаю новую версию")
            relaunch(exe)
        except Exception:
            log.exception("Не удалось установить обновление")
