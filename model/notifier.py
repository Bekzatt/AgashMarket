"""Уведомления подписчикам в Telegram из кассы — в фоновом потоке, окно не подвисает."""
import json
import logging
import threading
import urllib.parse
import urllib.request

import config
from model import services

log = logging.getLogger(__name__)


def _send(text: str) -> None:
    try:
        chat_ids = services.subscriber_chat_ids()
    except Exception:
        log.exception("Не удалось получить подписчиков")
        return
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
    for chat_id in chat_ids:
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text[:4000]}).encode()
        try:
            with urllib.request.urlopen(url, data=data, timeout=10) as resp:
                json.load(resp)
        except Exception as ex:
            log.warning("Telegram: не отправлено в %s: %s", chat_id, ex)


def notify(text: str):
    """Отправить сообщение всем подписчикам. Возвращает поток (можно дождаться через join)."""
    if not config.BOT_TOKEN:
        return None
    thread = threading.Thread(target=_send, args=(text,), daemon=True)
    thread.start()
    return thread
