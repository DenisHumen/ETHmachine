import requests
from config.config import ENABLE_NOTIFICATIONS, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

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
    **kwargs
):
    """
    Формирует красивое сообщение для Telegram уведомления.
    Все параметры опциональны.
    """
    emoji = TYPE_EMOJI.get(notif_type, TYPE_EMOJI["default"])
    lines = [f"{emoji} <b>{notif_type.upper()}</b>"]

    if title:
        lines.append(f"<b>{title}</b>")
    if message:
        lines.append(f"{message}")
    if proxy:
        lines.append(f"🟨 <b>Proxy:</b> <code>{proxy}</code>")
    if wallet_address:
        lines.append(f"👛 <b>Wallet:</b> <code>{wallet_address}</code>")
    if status:
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
        **kwargs
    )

    success = True

    for chat_id in TELEGRAM_CHAT_ID:
        # Отправка текстового сообщения
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

        # Если указан файл, отправляем его как документ
        if file_path:
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

    return success
