"""Onmi.fun — meme-coin launchpad на LITVM (https://app.onmi.fun/?chain=LITVM).

Сайт позволяет создать собственный ERC-20 (meme-coin) на bonding-curve через
TokenLaunch-фабрику. У создателя есть выбор:
  • Только создание (`createToken`) — токены минтятся на bonding-curve, на
    кошельке остаётся только tx создания.
  • Создание + Initial Buy (`createTokenAndBuy`, payable native zkLTC) —
    создатель сразу выкупает часть supply за нативный zkLTC через bonding-кривую.

Дополнительная функциональность сайта (после создания):
  • Buy/Sell на bondingCurveManager (свопы до graduation).
  • После graduation токен переезжает на собственный AMM (uniswap-like
    router/factory на LITVM).

Текущий модуль автоматизирует ТОЛЬКО шаг создания (с опциональным Initial Buy),
повторяя точную последовательность шагов сайта:
  1. (опц.) AI Magic — генерация name/symbol/description (на сегодня сервис
     отключён сервером, AI_MAGIC_ENABLED=false → fallback на локальный генератор).
  2. Скачивание картинки с Pinterest, ресайз 1:1 ≥ 1000×1000, сжатие ≤ 1 MB.
  3. POST `/api/upload/image?chainId=4441` (multipart, поле `imageUrl=<bytes>`)
     → ссылка `https://onmi.s3…`.
  4. POST `/api/upload/metadata?chainId=4441` (JSON) → metadataURI.
  5. on-chain: `createTokenAndBuy(...)` payable или `createToken(...)`.
  6. Парсим receipt: получаем адрес созданного токена.

Подробности — в `worker.py` / `onmi_client.py`.
"""
from modules.litvm_testnet.onmi.menu import run_litvm_onmi

__all__ = ["run_litvm_onmi"]
