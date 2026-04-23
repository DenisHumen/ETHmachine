"""Главное меню Dune Analytics модулей."""
from questionary import Choice, select

from modules.dune.base.menu import base_menu


def dune_menu():
    """Меню выбора проекта внутри Dune."""
    while True:
        action = select(
            "🟦 Dune Analytics — выберите проект:",
            choices=[
                Choice('🟦 Base                              🌟 Чекер кошельков по дашборду Base Network Analytics', 'base'),
                Choice('🔙 Назад', 'back'),
            ],
            qmark='🟦',
            pointer='👉',
        ).ask()

        if action is None or action == 'back':
            return

        if action == 'base':
            base_menu()
