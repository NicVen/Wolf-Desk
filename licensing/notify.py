"""Client + admin notifications (Telegram). Best-effort — never raises.

`contact` on a license is free-form: a numeric Telegram chat id gets a DM via
LICENSE_BOT_TOKEN; anything else is just logged (wire up email later if wanted).
A copy of every notice goes to LICENSE_ADMIN_CHAT if set.
"""
import json
import sys
import urllib.parse
import urllib.request

from . import config


def _telegram(chat_id, text):
    if not config.LICENSE_BOT_TOKEN or not chat_id:
        return
    url = "https://api.telegram.org/bot%s/sendMessage" % config.LICENSE_BOT_TOKEN
    data = urllib.parse.urlencode({
        "chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15).read()
    except Exception as e:  # noqa: BLE001
        _log("telegram send failed: %s" % e)


def _log(msg):
    sys.stdout.write("[notify] %s\n" % msg)
    sys.stdout.flush()


def client(contact, text):
    if contact and str(contact).lstrip("-").isdigit():
        _telegram(str(contact), text)
    else:
        _log("client notice (contact=%r): %s" % (contact, text))


def admin(text):
    if config.LICENSE_ADMIN_CHAT:
        _telegram(config.LICENSE_ADMIN_CHAT, "[STAALWAG licensing] " + text)
    else:
        _log("admin notice: %s" % text)
