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
    **kwargs
):
    """
    Формирует красивое сообщение для Telegram уведомления.
    Все параметры опциональны.
    """
    emoji = TYPE_EMOJI.get(notif_type, TYPE_EMOJI["default"])
    lines = [f"{emoji} <b>{notif_type.upper()}</b>\n"]

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

# if __name__ == "__main__":
#     # Тестовые вызовы для проверки всех типов уведомлений

#     # Тест: info
#     send_telegram_notification(
#         notif_type="info",
#         title="Информационное уведомление",
#         message="Это тестовое информационное сообщение.",
#         proxy="123.45.67.89:8080",
#         wallet_address="0x1234567890abcdef1234567890abcdef12345678",
#         status="info",
#         balance="1.234 ETH",
#         extra="Дополнительная информация",
#         tx_hash="0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
#         explorer_url="https://etherscan.io/tx/",
#         test_param="test_value"
#     )

#     # Тест: success
#     send_telegram_notification(
#         notif_type="success",
#         title="Успех!",
#         message="Транзакция прошла успешно.",
#         proxy="proxy.example.com:3128",
#         wallet_address="0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
#         status="success",
#         balance="0.999 ETH",
#         tx_hash="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
#         explorer_url="https://etherscan.io/tx/",
#         extra="Тест успешного уведомления"
#     )

#     # Тест: error
#     send_telegram_notification(
#         notif_type="error",
#         title="Ошибка!",
#         message="Произошла ошибка при обработке транзакции.",
#         proxy="proxy.error.com:8080",
#         wallet_address="0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
#         status="error",
#         balance="0.0 ETH",
#         tx_hash="0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
#         explorer_url="https://etherscan.io/tx/",
#         extra="Ошибка: недостаточно средств"
#     )

#     # Тест: warning
#     send_telegram_notification(
#         notif_type="warning",
#         title="Внимание!",
#         message="Баланс кошелька низкий.",
#         wallet_address="0xfeedfeedfeedfeedfeedfeedfeedfeedfeedfeed",
#         status="warning",
#         balance="0.01 ETH",
#         extra="Проверьте баланс перед отправкой"
#     )

#     # Тест: critical + файл
#     test_file_path = "result/result.csv"
#     send_telegram_notification(
#         notif_type="critical",
#         title="Критическая ошибка!",
#         message="Сбой системы, требуется вмешательство.",
#         wallet_address="0xfacefacefacefacefacefacefacefacefaceface",
#         status="critical",
#         balance="0.00 ETH",
#         extra="Файл с логами прикреплен",
#         file_path=test_file_path
#     )
