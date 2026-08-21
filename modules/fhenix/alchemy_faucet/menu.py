"""Alchemy Faucet (Base Sepolia) — меню модуля."""
from __future__ import annotations

from config.modules.cfg_fhenix import (
    ALCHEMY_FAUCET_ARRIVAL_TIMEOUT_MIN,
    ALCHEMY_FAUCET_COOLDOWN_HOURS,
    ALCHEMY_FAUCET_URL,
)
from modules.fhenix.alchemy_faucet import database as db
from modules.fhenix.alchemy_faucet.worker import process_wallet
from modules.fhenix.faucet_menu import Faucet, run_faucet_menu

ALCHEMY_FAUCET = Faucet(
    key="alchemy",
    title="Alchemy Faucet",
    subtitle="тестовый ETH сети Base Sepolia",
    db=db,
    process_wallet=process_wallet,
    statuses=("pending", "in_progress", "requested", "cooldown",
              "arrived", "ineligible", "failed"),
    info={
        "Как это работает": [
            f"Кран: {ALCHEMY_FAUCET_URL}",
            "Кошельки берутся из data/data.csv — нужны поля private_key и "
            "proxy; все запросы кошелька идут через его прокси.",
            "Для каждого кошелька решается Cloudflare Turnstile, затем "
            "отправляется заявка на кран.",
            f"После заявки модуль ждёт роста баланса в Base Sepolia — "
            f"до {ALCHEMY_FAUCET_ARRIVAL_TIMEOUT_MIN} минут.",
            f"Кран отдаёт токены раз в {ALCHEMY_FAUCET_COOLDOWN_HOURS} часа; "
            "кошельки в кулдауне пропускаются без траты капчи.",
            "Alchemy проверяет активность кошелька в основной сети. Если "
            "проверка не пройдена, кошелёк помечается как «не подходит» и "
            "больше не переспрашивается.",
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


def run_alchemy_faucet() -> None:
    run_faucet_menu(ALCHEMY_FAUCET)


__all__ = ["run_alchemy_faucet", "ALCHEMY_FAUCET"]
