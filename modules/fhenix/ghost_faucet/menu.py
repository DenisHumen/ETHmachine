"""Ghost Faucet (Sepolia) — меню модуля."""
from __future__ import annotations

from config.modules.cfg_fhenix import (
    GHOST_FAUCET_ARRIVAL_TIMEOUT_MIN,
    GHOST_FAUCET_COOLDOWN_HOURS,
    GHOST_FAUCET_URL,
)
from modules.fhenix.faucet_menu import Faucet, run_faucet_menu
from modules.fhenix.ghost_faucet import database as db
from modules.fhenix.ghost_faucet.worker import process_wallet

GHOST_FAUCET = Faucet(
    key="ghost",
    title="Ghost Faucet",
    subtitle="тестовый ETH сети Sepolia",
    db=db,
    process_wallet=process_wallet,
    statuses=("pending", "in_progress", "requested", "cooldown",
              "arrived", "failed"),
    info={
        "Как это работает": [
            f"Кран: {GHOST_FAUCET_URL}",
            "Кошельки берутся из data/data.csv — нужны поля private_key и "
            "proxy; все запросы кошелька идут через его прокси.",
            "Для каждого кошелька решается Cloudflare Turnstile, затем "
            "отправляется заявка на кран.",
            f"После заявки модуль ждёт роста баланса в Sepolia — "
            f"до {GHOST_FAUCET_ARRIVAL_TIMEOUT_MIN} минут.",
            f"Кран отдаёт токены раз в {GHOST_FAUCET_COOLDOWN_HOURS} часа; "
            "кошельки в кулдауне пропускаются без траты капчи.",
            "Прерывание (Ctrl+C) безопасно — прогресс лежит в базе, "
            "следующий запуск продолжит с того же места.",
        ],
        "Где что лежит": [
            f"База: db/{db.DB_PATH.name}",
            "Задачи: таблица wallet_tasks",
            "История заявок: таблица request_history — она переживает "
            "очистку базы, иначе кулдаун будет посчитан заново.",
        ],
        "Что нужно настроить": [
            "Ключ сервиса разгадывания капчи (Turnstile) в "
            "config/modules/general_config.py.",
            "Параметры крана — в config/modules/cfg_fhenix.py.",
        ],
    },
)


def run_ghost_faucet() -> None:
    run_faucet_menu(GHOST_FAUCET)


__all__ = ["run_ghost_faucet", "GHOST_FAUCET"]
