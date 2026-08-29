"""LiteForge testnet — навигация по пресетам проекта.

Своих задач у этого меню нет: оно только показывает список пресетов и
передаёт управление выбранному. Поэтому здесь ``ui.show_items``, а не
``ModuleMenu`` — статистики, справки и очистки базы у навигации не бывает.

Новый пресет добавляется в двух местах: пункт в ``LITVM_TESTNET_SUBMENU``
и строка в ``_HANDLERS`` с тем же ``key``.
"""
from __future__ import annotations

from importlib import import_module

from modules.ui import ui
from modules.ui.menu_model import BACK_KEY, MenuItem, SubMenu

LITVM_TESTNET_SUBMENU = SubMenu(
    key="litvm_testnet",
    label="LiteForge testnet",
    description="Выберите пресет",
    icon="⚒️",
    items=[
        MenuItem(
            key="faucet",
            label="Кран zkLTC",
            description="запросить тестовые zkLTC на Caldera Hub",
            icon="🚰",
        ),
        MenuItem(
            key="bridge",
            label="Мост Sepolia ⇄ LiteForge",
            description="перенести zkLTC между Sepolia и LiteForge",
            icon="🌉",
        ),
        MenuItem(
            key="lester_minter",
            label="Lester Minter",
            description="деплой случайных ERC-20 на lester-labs.com",
            icon="🪙",
        ),
        MenuItem(
            key="midas",
            label="Midas Prediction Market",
            description="регистрация, краны, ежедневный вход, ставки",
            icon="🎯",
        ),
        MenuItem(
            key="aynilabs",
            label="Aynilabs",
            description="обернуть zkLTC в wzkLTC",
            icon="📦",
            badge="ПАУЗА",
            badge_style="warn",
        ),
        MenuItem(
            key="onmi",
            label="Onmi.fun · выпуск токенов",
            description="выпуск мем-токенов на bonding-curve",
            icon="🚀",
        ),
        MenuItem(
            key="onmi_trade",
            label="Onmi.fun · торговля",
            description="случайные покупки и продажи между кошельками",
            icon="🎲",
        ),
        MenuItem(
            key="onmi_swap",
            label="Onmi.fun · свапы",
            description="обмен graduated-токенов по UniswapV2",
            icon="💱",
        ),
        MenuItem(
            key="onmi_liquidity",
            label="Onmi.fun · ликвидность",
            description="добавить ликвидность или вывести всё сразу",
            icon="💧",
        ),
        MenuItem(
            key="zns_bio",
            label="ZNS.bio · домены .lit",
            description="случайные никнеймы в зоне .lit",
            icon="🪪",
        ),
        MenuItem(key=BACK_KEY, label="Назад", description="", icon="←"),
    ],
)

# Импорт ленивый: тянуть web3 и patchright ради показа списка незачем.
_HANDLERS: dict[str, tuple[str, str]] = {
    "faucet": ("modules.litvm_testnet.faucet", "run_litvm_faucet"),
    "bridge": ("modules.litvm_testnet.bridge", "run_litvm_bridge"),
    "lester_minter": ("modules.litvm_testnet.lester_minter", "run_litvm_minter"),
    "midas": ("modules.litvm_testnet.midas", "run_litvm_midas"),
    "aynilabs": ("modules.litvm_testnet.aynilabs", "run_litvm_aynilabs"),
    "onmi": ("modules.litvm_testnet.onmi", "run_litvm_onmi"),
    "onmi_trade": ("modules.litvm_testnet.onmi.trade", "run_litvm_onmi_trade"),
    "onmi_swap": ("modules.litvm_testnet.onmi.swap", "run_litvm_onmi_swap"),
    "onmi_liquidity": ("modules.litvm_testnet.onmi.liquidity",
                       "run_litvm_onmi_liquidity"),
    "zns_bio": ("modules.litvm_testnet.zns_bio", "run_litvm_zns_bio"),
}


def litvm_testnet_menu() -> None:
    """Главное меню проекта LiteForge — выбор пресета."""
    while True:
        action = ui.show_items(
            "⚒️ LiteForge testnet — выберите пресет",
            LITVM_TESTNET_SUBMENU.items,
        )
        if action in (None, BACK_KEY):
            return

        target = _HANDLERS.get(action)
        if target is None:
            continue
        module_name, entry_point = target
        getattr(import_module(module_name), entry_point)()


__all__ = ["LITVM_TESTNET_SUBMENU", "litvm_testnet_menu"]
