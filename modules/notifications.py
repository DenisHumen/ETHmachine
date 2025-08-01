import sys
import os

# Исправленный импорт config для корректного поиска модуля
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(project_root)

from config.config import ENABLE_NOTIFICATIONS, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

import requests

# Эмодзи для разных типов уведомлений
TYPE_EMOJI = {
    "info": "ℹ️",
    "success": "✅",
    "error": "❌",
    "warning": "⚠️",
    "critical": "🚨",
    "proxy": "🟨",
    "wallet": "👛",
    "tx": "🔗",
    "balance": "💰",
    "default": "🔔"
}

def format_notification_message(
    notif_type="info",
    title=None,
    message=None,
    proxy=None,
    wallet_address=None,
    status=None,
    tx_hash=None,
    explorer_url=None,
    balance=None,
    extra=None,
    main_title="NONE",  # Новый параметр для главного заголовка
    **kwargs
):
    """
    Формирует красивое сообщение для Telegram уведомления.
    Все параметры опциональны.
    """
    emoji = TYPE_EMOJI.get(notif_type, TYPE_EMOJI["default"])
    # Главный заголовок с эмодзи в начале и конце
    lines = [f"✨ <b>{main_title}</b> ✨", f"{emoji} <b>{notif_type.upper()}</b>\n"]

    if title:
        lines.append(f"<b>{title}</b>")
    if message:
        lines.append(f"{message}")
    if proxy:
        lines.append(f"🟨 <b>Proxy:</b> <code>{proxy}</code>")
    if wallet_address:
        lines.append(f"👛 <b>Wallet:</b> <code>{wallet_address}</code>")
    # Добавляем статус только если он не совпадает с типом уведомления
    if status and status.lower() != notif_type.lower():
        lines.append(f"📋 <b>Status:</b> <b>{status}</b>")
    if balance is not None:
        lines.append(f"💰 <b>Balance:</b> <code>{balance}</code>")
    if tx_hash:
        lines.append(f"🔗 <b>Tx Hash:</b> <code>{tx_hash}</code>")
    if explorer_url and tx_hash:
        lines.append(f"🌐 <a href='{explorer_url}{tx_hash}'>Explorer Link</a>")
    elif explorer_url:
        lines.append(f"🌐 <a href='{explorer_url}'>Explorer</a>")
    if extra:
        lines.append(f"📝 <b>Extra:</b> {extra}")

    # Добавляем любые дополнительные параметры
    for key, value in kwargs.items():
        lines.append(f"🔹 <b>{key}:</b> <code>{value}</code>")

    return "\n".join(lines)

def send_telegram_notification(
    notif_type="info",
    title=None,
    message=None,
    proxy=None,
    wallet_address=None,
    status=None,
    tx_hash=None,
    explorer_url=None,
    balance=None,
    extra=None,
    file_path=None,  # Новый параметр для файла
    main_title="NONE",  # Новый параметр для главного заголовка
    **kwargs
):
    """
    Отправляет уведомление в Telegram.
    Все параметры опциональны, можно передавать любые дополнительные через kwargs.
    Можно прикрепить файл (например, CSV) через file_path.
    """
    if not ENABLE_NOTIFICATIONS or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    text = format_notification_message(
        notif_type=notif_type,
        title=title,
        message=message,
        proxy=proxy,
        wallet_address=wallet_address,
        status=status,
        tx_hash=tx_hash,
        explorer_url=explorer_url,
        balance=balance,
        extra=extra,
        main_title=main_title,  # Передаём главный заголовок
        **kwargs
    )

    success = True

    for chat_id in TELEGRAM_CHAT_ID:
        if file_path:
            # Отправляем только файл с caption, не отправляем отдельное текстовое сообщение
            url_doc = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
            try:
                with open(file_path, "rb") as f:
                    files = {"document": f}
                    data = {
                        "chat_id": chat_id,
                        "caption": text,
                        "parse_mode": "HTML"
                    }
                    resp_doc = requests.post(url_doc, data=data, files=files, timeout=20)
                    if resp_doc.status_code != 200:
                        success = False
            except Exception:
                success = False
        else:
            # Отправляем только текстовое сообщение
            url_msg = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            try:
                resp = requests.post(url_msg, json=payload, timeout=10)
                if resp.status_code != 200:
                    success = False
            except Exception:
                success = False

    return success

def send_telegram_message(message, main_title="ETHmachine"):
    """
    Упрощенная функция для отправки текстового сообщения в Telegram
    """
    return send_telegram_notification(
        notif_type="info",
        message=message,
        main_title=main_title
    )

def send_telegram_file(file_path, caption="", main_title="ETHmachine"):
    """
    Функция для отправки файла в Telegram с подписью
    """
    return send_telegram_notification(
        notif_type="info",
        message=caption,
        file_path=file_path,
        main_title=main_title
    )