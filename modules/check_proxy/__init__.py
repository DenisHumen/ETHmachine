"""
Продвинутый чекер прокси.

Архитектура:
    services.py     — каталог тестируемых сервисов и RPC.
    probe.py        — низкоуровневые сетевые пробы (DNS, TCP, TLS, CONNECT, TTFB).
    tester.py       — высокоуровневое тестирование одного прокси (уровни 1-4).
    database.py     — SQLite: хранение запусков, задач и результатов.
    excel_export.py — выгрузка результатов в xlsx.
    menu.py         — интерактивное меню (выбор уровня и запуск).

Точка входа: ``check_proxy_menu()``.
"""

from .menu import check_proxy_menu

__all__ = ["check_proxy_menu"]
