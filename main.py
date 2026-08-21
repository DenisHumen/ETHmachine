"""ETHmachine — терминальный набор для автоматизации крипто-рутины.

Точка входа. Здесь только маршрутизация: меню объявлено в
``config/menu_config.py``, внешний вид — в ``modules/ui``, вся логика —
в модулях под ``modules/``.

Тяжёлые модули (web3, playwright, ccxt) импортируются лениво, прямо
в обработчиках: иначе запуск программы упирался бы в несколько секунд
импортов, большая часть которых пользователю в текущей сессии не нужна.
"""

from __future__ import annotations

import platform
import sys
import warnings

# ── stdout в UTF-8 ──────────────────────────────────────────────────────
# Нужно до любых импортов: рамки, эмодзи и русские логи иначе падают
# на Windows-консоли с кодировкой по умолчанию (cp866/cp1251).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

warnings.filterwarnings("ignore", category=DeprecationWarning)
try:
    from cryptography.utils import CryptographyDeprecationWarning  # type: ignore

    warnings.filterwarnings("ignore", category=CryptographyDeprecationWarning)
except Exception:
    pass

# ── Проверка зависимостей ───────────────────────────────────────────────
# Только stdlib — работает на чистом Python без установленных пакетов.
from modules.requirements_checker import check_requirements

if not check_requirements():
    input("\nEnter — выход...")
    sys.exit(1)

from config.menu_config import (
    BALANCES_SUBMENU, BINANCE_SUBMENU, BITGET_SUBMENU, CEX_SUBMENU,
    COLLECTORS_SUBMENU, CONVERT_TOOL_SUBMENU, DISCORD_OS_SUBMENU,
    ETH_BALANCES_SUBMENU, ETH_WALLETS_SUBMENU, GENERATE_WALLETS_SUBMENU,
    MAIN_MENU_CONFIG, MEXC_SUBMENU, OKX_SUBMENU, PROJECTS_SUBMENU,
    RUST_IMPL_SUBMENU, SOL_BALANCES_SUBMENU, SOL_WALLETS_SUBMENU,
    TOOLS_SUBMENU, TRANSACTIONS_SUBMENU, TWITTER_SUBMENU,
    WALLET_COUNT_OPTIONS, get_enabled_main_menu_items,
)
from modules.ui import BACK_KEY, banner, ui
from modules.ui.menu_model import SubMenu

BACK = BACK_KEY


# =============================================================================
# ВСПОМОГАТЕЛЬНОЕ
# =============================================================================

def get_os_type() -> str:
    """``windows`` / ``macos`` / ``linux``."""
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    if system == "darwin":
        return "macos"
    return "linux"


def ask(submenu: SubMenu):
    """Показывает подменю и возвращает выбранный ключ (``None`` при Ctrl+C)."""
    return ui.show_items(submenu.description or submenu.label, submenu.items)


def not_ready(name: str) -> None:
    ui.print_lines(ui.panel(
        name,
        [f"{ui.theme.FG_MUTED}Функционал ещё в разработке.{ui.theme.RESET}",
         f"{ui.theme.FG_MUTED}Следите за обновлениями в Telegram-канале.{ui.theme.RESET}"],
        color=ui.theme.FG_WARN,
    ))
    ui.pause()


# =============================================================================
# ОБРАБОТЧИКИ РАЗДЕЛОВ
# =============================================================================

class MenuHandlers:
    """Маршрутизация пунктов меню в модули.

    Каждый ``handle_*`` крутится в собственном цикле, пока пользователь не
    выберет «Назад»: возвращать его в главное меню после каждого действия —
    лишние нажатия.
    """

    # ── Балансы ─────────────────────────────────────────────────────────

    @staticmethod
    def handle_check_balances() -> None:
        while True:
            choice = ask(BALANCES_SUBMENU)
            if choice in (None, BACK):
                return
            if choice == "ETH":
                MenuHandlers._handle_eth_balances()
            elif choice == "SOL":
                MenuHandlers._handle_sol_balances()
            elif choice == "Eclipse":
                from modules.sol.eclipse_get_balances import eclipse_balance_checker

                eclipse_balance_checker()
                ui.pause()
            elif choice == "debank_checker":
                from modules.debank.debank_checker import debank_checker_menu

                debank_checker_menu()
            elif choice == "debank_protocols":
                from modules.debank.debank_protocol_checker import debank_protocol_menu

                debank_protocol_menu()
            elif choice == "zksync_lite":
                from modules.zksync_lite import zksync_lite_menu

                zksync_lite_menu()

    @staticmethod
    def _handle_eth_balances() -> None:
        while True:
            choice = ask(ETH_BALANCES_SUBMENU)
            if choice in (None, BACK):
                return
            if choice == "check_wallet_balances_eth":
                from modules.eth.eth_get_balances import check_wallet_balances_menu

                check_wallet_balances_menu()
            elif choice == "check_token_balances":
                from modules.eth.eth_get_token_balance import check_token_balance_menu

                check_token_balance_menu()
            ui.pause()

    @staticmethod
    def _handle_sol_balances() -> None:
        while True:
            choice = ask(SOL_BALANCES_SUBMENU)
            if choice in (None, BACK):
                return
            if choice == "check_wallet_balances_sol":
                from modules.sol.sol_get_balances import solana_balance_checker

                solana_balance_checker()
                ui.pause()
            elif choice == "check_token_balances_sol":
                not_ready("Балансы SPL-токенов")

    # ── Транзакции ──────────────────────────────────────────────────────

    @staticmethod
    def handle_transactions() -> None:
        while True:
            choice = ask(TRANSACTIONS_SUBMENU)
            if choice in (None, BACK):
                return
            if choice == "collectors":
                MenuHandlers._handle_collectors()
            elif choice == "transfer_wallets_to_wallets_call":
                MenuHandlers._handle_transfer_wallets()
            elif choice == "transfer_erc20_tokens_call":
                from modules.eth.transfer_erc20_tokens import run_transfer_erc20_tokens

                run_transfer_erc20_tokens()
            elif choice == "transfer_kava_to_cex_call":
                from modules.eth.transfer_kava_to_cex import run_transfer_kava_to_cex

                run_transfer_kava_to_cex()
            elif choice == "relay_bridge":
                from modules.relay_link.relay_link import main as relay_bridge_main

                relay_bridge_main()

    @staticmethod
    def _handle_collectors() -> None:
        while True:
            choice = ask(COLLECTORS_SUBMENU)
            if choice in (None, BACK):
                return
            if choice == "eth_collectors":
                from modules.eth.eth_collectors import eth_collectors

                eth_collectors()
                ui.pause()
            elif choice == "sol_collectors":
                not_ready("Сборщик Solana")

    @staticmethod
    def _handle_transfer_wallets() -> None:
        from config.networks import get_mainnet_networks, get_testnet_networks

        ui.print_lines(ui.info_panel("Перевод нативных токенов", {
            "Данные читаются из data/data.csv": [
                f"private_key      {ui.glyphs.arrow} отправитель",
                f"evm_cex_address  {ui.glyphs.arrow} получатель (адрес или приватный ключ)",
                f"transfer_amount  {ui.glyphs.arrow} 0.1-0.2 — сумма, «90-100» или 90-100% — процент",
            ],
        }))

        network_type = ui.choose("Тип сети", [
            ("🌐 Mainnet", "mainnet"),
            ("🔧 Testnet", "testnet"),
        ])
        if network_type in (None, BACK):
            return

        networks = (get_mainnet_networks() if network_type == "mainnet"
                    else get_testnet_networks())
        network = ui.choose("В какой сети переводим", [(n, n) for n in networks])
        if network in (None, BACK):
            return

        from modules.data_manager import get_transfer_rows

        rows = get_transfer_rows()
        if not rows:
            ui.print_lines(ui.panel("Нет данных для перевода", [
                "Заполните в data/data.csv колонки:",
                "  private_key, evm_cex_address, transfer_amount",
            ], color=ui.theme.FG_WARN))
            ui.pause()
            return

        from modules.eth.transfer_wallets_to_wallets import run_transfer

        run_transfer(rows, network)
        ui.pause()

    # ── Twitter ─────────────────────────────────────────────────────────

    @staticmethod
    def handle_twitter() -> None:
        while True:
            choice = ask(TWITTER_SUBMENU)
            if choice in (None, BACK):
                return
            if choice == "twitter_check":
                from modules.twitter.twitter_check import run_twitter_check

                run_twitter_check(get_os_type())
                ui.pause()
            elif choice == "twitter_task":
                from modules.twitter.twitter_task_runner import run_twitter_tasks

                run_twitter_tasks()

    # ── Проекты ─────────────────────────────────────────────────────────

    @staticmethod
    def handle_projects() -> None:
        while True:
            choice = ask(PROJECTS_SUBMENU)
            if choice in (None, BACK):
                return
            if choice == "xstocks":
                from modules.xstocks.menu import xstocks_menu

                xstocks_menu()
            elif choice == "neura_stat":
                MenuHandlers._handle_neura()
            elif choice == "dune":
                from modules.dune import dune_menu

                dune_menu()
            elif choice == "fhenix":
                from modules.fhenix.menu import fhenix_menu

                fhenix_menu()
            elif choice == "litvm_testnet":
                from modules.litvm_testnet import litvm_testnet_menu

                litvm_testnet_menu()
            elif choice == "sahara":
                from modules.sahara import run_sahara

                run_sahara()
            elif choice == "safepal_x1":
                from modules.eth.safepal_x1_checker import safepal_x1_checker_menu

                safepal_x1_checker_menu()

    @staticmethod
    def _handle_neura() -> None:
        """Neura собран под Windows (зависит от pyarmor_runtime.pyd)."""
        if get_os_type() != "windows":
            ui.print_lines(ui.panel("Neura недоступен", [
                "Модуль собран только под Windows —",
                "он использует бинарный pyarmor_runtime.pyd.",
                "",
                f"Ваша ОС: {get_os_type()}, Python {platform.python_version()}",
            ], color=ui.theme.FG_WARN))
            ui.pause()
            return
        try:
            from modules.statistics.neura_stats import neura_statistics
        except Exception as exc:
            ui.print_lines(ui.panel("Не удалось загрузить Neura", [
                str(exc),
            ], color=ui.theme.FG_ERR))
            ui.pause()
            return
        neura_statistics()

    # ── Биржи ───────────────────────────────────────────────────────────

    @staticmethod
    def handle_cex() -> None:
        while True:
            exchange = ask(CEX_SUBMENU)
            if exchange in (None, BACK):
                return
            if exchange == "OKX":
                MenuHandlers._handle_okx()
            elif exchange == "Binance":
                MenuHandlers._handle_binance()
            elif exchange == "Bitget":
                MenuHandlers._handle_bitget()
            elif exchange == "MEXC":
                MenuHandlers._handle_mexc()

    @staticmethod
    def _handle_okx() -> None:
        while True:
            action = ask(OKX_SUBMENU)
            if action in (None, BACK):
                return
            if action == "withdraw_from_okx":
                from modules.cex.okx.okx_withdraw import okx_withdraw

                okx_withdraw()
            elif action == "get_balances_okx":
                from modules.cex.okx.okx_SubAccount import get_balances_okx

                get_balances_okx()
            elif action == "subaccount_collector_okx":
                from modules.cex.okx.okx_SubAccount import (
                    check_okx_subaccounts_and_balances,
                )

                check_okx_subaccounts_and_balances()
            elif action == "spot_trade_okx":
                from modules.cex.okx.okx_SpotTrade import start_okx_spot_trading

                start_okx_spot_trading()
            ui.pause()

    @staticmethod
    def _handle_binance() -> None:
        while True:
            action = ask(BINANCE_SUBMENU)
            if action in (None, BACK):
                return
            if action == "withdraw_from_binance":
                from modules.cex.binance.binance_withdraw import binance_withdraw

                binance_withdraw()
            elif action == "get_balances_binance":
                from modules.cex.binance.binance_SubAccount import get_balances_binance

                get_balances_binance()
            elif action == "subaccount_collector_binance":
                from modules.cex.binance.binance_SubAccount import (
                    subaccount_collector_binance,
                )

                subaccount_collector_binance()
            ui.pause()

    @staticmethod
    def _handle_bitget() -> None:
        while True:
            action = ask(BITGET_SUBMENU)
            if action in (None, BACK):
                return
            if action == "withdraw_from_bitget":
                from modules.cex.bitget.bitget_withdraw import bitget_withdraw

                bitget_withdraw()
                ui.pause()
            elif action == "get_balances_bitget":
                not_ready("Балансы Bitget")
            elif action == "subaccount_collector_bitget":
                from modules.cex.bitget.bitget_SubAccount import (
                    check_bitget_subaccounts_and_balances,
                )

                check_bitget_subaccounts_and_balances()
                ui.pause()

    @staticmethod
    def _handle_mexc() -> None:
        while True:
            action = ask(MEXC_SUBMENU)
            if action in (None, BACK):
                return
            if action == "withdraw_from_mexc":
                from modules.cex.mexc.mexc_withdraw import mexc_withdraw

                mexc_withdraw()
                ui.pause()

    # ── Инструменты ─────────────────────────────────────────────────────

    @staticmethod
    def handle_tools() -> None:
        while True:
            choice = ask(TOOLS_SUBMENU)
            if choice in (None, BACK):
                return
            if choice == "generate_wallets":
                MenuHandlers._handle_generate_wallets()
            elif choice == "ETH_convert_tool":
                MenuHandlers._handle_convert_tool()
            elif choice == "password_generator":
                from modules.password_generator import password_generator_menu

                password_generator_menu()
                ui.pause()
            elif choice == "nickname_generator":
                from modules.nickname_generator import generate_nicknames

                generate_nicknames()
                ui.pause()
            elif choice == "fullname_generator":
                from modules.fullname_generator import generate_fullnames_menu

                generate_fullnames_menu()
                ui.pause()
            elif choice == "check_proxy":
                from modules.check_proxy import check_proxy_menu

                check_proxy_menu()
            elif choice == "check_age_discord":
                MenuHandlers._handle_discord_check()
            elif choice == "email_checker":
                from modules.email.email_imap_checker import run_email_checker

                run_email_checker()
                ui.pause()
            elif choice == "pinterest_downloader":
                from modules.pinterest_downloader import pinterest_downloader_menu

                pinterest_downloader_menu()
            elif choice == "swap_all_polygon_zkevm_to_base":
                from modules.eth.swap_all_polygon_zkevm_to_base import (
                    run_swap_all_polygon_zkevm_to_base,
                )

                run_swap_all_polygon_zkevm_to_base()
            elif choice == "swap_all_zksync_era_to_base":
                from modules.eth.swap_all_zksync_era_to_base import (
                    run_swap_all_zksync_era_to_base,
                )

                run_swap_all_zksync_era_to_base()

    @staticmethod
    def _handle_generate_wallets() -> None:
        while True:
            wallet_type = ask(GENERATE_WALLETS_SUBMENU)
            if wallet_type in (None, BACK):
                return

            count = MenuHandlers._select_wallet_count()
            if count is None:
                continue

            if wallet_type == "eth_wallets":
                MenuHandlers._generate_eth_wallets(count)
            elif wallet_type == "sol_wallets":
                MenuHandlers._generate_sol_wallets(count)

    @staticmethod
    def _select_wallet_count() -> int | None:
        options = [
            (f"{option['label']}", option["value"])
            for option in WALLET_COUNT_OPTIONS
        ]
        choice = ui.menu("Сколько кошельков генерируем", options)
        if choice in (None, BACK):
            return None
        if choice == "manual":
            return ui.ask_int("Количество кошельков", minimum=1, maximum=10_000_000)
        return int(choice)

    @staticmethod
    def _generate_eth_wallets(count: int) -> None:
        choice = ask(ETH_WALLETS_SUBMENU)
        if choice in (None, BACK):
            return
        if choice == "generate":
            from modules.eth.eth_wallet_generator import eth_generate_wallets

            eth_generate_wallets(count)
            MenuHandlers._report_generated(count, "EVM-кошельков")
        elif choice == "nice_generate":
            MenuHandlers._generate_nice_eth_wallets(count)

    @staticmethod
    def _generate_nice_eth_wallets(count: int) -> None:
        from modules.eth.eth_nice_address.eth_nice_address_rust_wrapper import (
            check_cargo_installed, run_rust_generator,
        )
        from modules.eth.eth_nice_address.python.eth_nice_address import (
            eth_generate_nice_wallets,
        )

        impl = ask(RUST_IMPL_SUBMENU)
        if impl in (None, BACK):
            return

        if impl == "rust" and not check_cargo_installed():
            ui.print_lines(ui.panel("Cargo не установлен", [
                "Rust-генератор требует установленный Cargo.",
                "Ставится вместе с Rust: https://rustup.rs",
                "",
                "Продолжаем на Python-реализации.",
            ], color=ui.theme.FG_WARN))
            impl = "python"

        if impl == "python":
            eth_generate_nice_wallets(count)
            MenuHandlers._report_generated(count, "красивых EVM-кошельков")
            return

        threads = 0
        if not ui.confirm("Использовать все доступные потоки?", default=True):
            threads = ui.ask_int("Количество потоков", minimum=1, maximum=256,
                                 default=4) or 0
        run_rust_generator(
            num_wallets=count,
            config_path="config/modules/cfg_nice_address.py",
            output_path="result/result.csv",
            threads=threads,
            display_process=True,
        )

    @staticmethod
    def _generate_sol_wallets(count: int) -> None:
        choice = ask(SOL_WALLETS_SUBMENU)
        if choice in (None, BACK):
            return
        if choice == "generate":
            from modules.sol.sol_wallet_generator import sol_generate_wallets

            sol_generate_wallets(count)
            MenuHandlers._report_generated(count, "Solana-кошельков")
        elif choice == "nice_generate":
            from modules.sol.sol_nice_address import sol_generate_nice_wallets

            sol_generate_nice_wallets(count)
            MenuHandlers._report_generated(count, "красивых Solana-кошельков")

    @staticmethod
    def _report_generated(count: int, what: str) -> None:
        ui.print_lines(ui.panel("Готово", [
            f"Сгенерировано {count} {what}.",
            "Результат: result/result.csv",
        ], color=ui.theme.FG_OK))
        ui.pause()

    @staticmethod
    def _handle_convert_tool() -> None:
        while True:
            action = ask(CONVERT_TOOL_SUBMENU)
            if action in (None, BACK):
                return
            if action == "eth_mnemonic_to_privkey":
                from modules.eth.eth_mnemonic_to_privkey import process_mnemonics

                process_mnemonics()
            elif action == "eth_privkey_to_wallet":
                from modules.eth.eth_private_key_to_wallet_address import (
                    process_private_keys,
                )

                process_private_keys()
            elif action == "sol_mnemonic_to_privkey":
                from modules.sol.sol_mnemonic_to_privkey import sol_process_mnemonics

                sol_process_mnemonics()
            ui.pause()

    @staticmethod
    def _handle_discord_check() -> None:
        os_choice = ask(DISCORD_OS_SUBMENU)
        if os_choice in (None, BACK):
            return
        from modules.discord.discord_age import check_discord_accounts

        check_discord_accounts(os_choice)
        ui.pause()


# =============================================================================
# ГЛАВНОЕ МЕНЮ
# =============================================================================

_ROUTES = {
    "check_balances": MenuHandlers.handle_check_balances,
    "transactions": MenuHandlers.handle_transactions,
    "twitter": MenuHandlers.handle_twitter,
    "projects_menu": MenuHandlers.handle_projects,
    "CEX_menu": MenuHandlers.handle_cex,
    "miscellaneous": MenuHandlers.handle_tools,
}


def main_menu() -> None:
    while True:
        action = ui.show_items(
            MAIN_MENU_CONFIG["title"], get_enabled_main_menu_items(),
        )

        if action in (None, "exit"):
            banner.print_farewell()
            return

        handler = _ROUTES.get(action)
        if handler is not None:
            handler()
        elif action == "backup_menu":
            from modules.backup import backup_menu

            backup_menu()
        elif action == "info":
            from modules.info import info

            info()
        elif action == "faucets":
            not_ready("Faucets")


# =============================================================================
# ЗАПУСК
# =============================================================================

def _start_web_dashboard() -> str | None:
    """Поднимает веб-панель в фоне. Возвращает URL или ``None``."""
    try:
        import web

        if not web.startup():
            return None
        from config.modules.cfg_web import WEB_HOST, WEB_PORT

        host = "127.0.0.1" if WEB_HOST in ("0.0.0.0", "::", "") else WEB_HOST
        return f"http://{host}:{WEB_PORT}/"
    except Exception as exc:
        print(f"{ui.theme.FG_WARN}Веб-панель не запустилась: {exc}{ui.theme.RESET}")
        return None


def main() -> int:
    from modules.bootstrap import prepare_workspace

    prepare_workspace()

    web_url = _start_web_dashboard()

    from modules.GitHub.check_version import check_version

    check_version("ETHmachine")

    from modules.backup import create_backup, list_backups
    from modules.backup.backup_manager import BackupManager
    from config.modules.cfg_backup import DISPLAY_LIST_BACKUPS

    create_backup()

    from modules.config_validator import validate_configuration

    print(f"\n{ui.theme.FG_ACCENT}Проверка конфигурации...{ui.theme.RESET}")
    if not validate_configuration():
        print(ui.panel("В конфигурации есть ошибки", [
            "Исправьте пункты выше и запустите программу заново.",
        ], color=ui.theme.FG_ERR))
        input("\nEnter — выход...")
        return 1

    from modules.data_manager import get_selected_data_file, select_data_file

    select_data_file()

    backup_manager = None
    try:
        from config.modules.cfg_backup import (
            SFTP_LIVE_SYNC_ENABLE, SFTP_SERVER_INTO_BACKUP_ENABLE,
        )

        if SFTP_SERVER_INTO_BACKUP_ENABLE and SFTP_LIVE_SYNC_ENABLE:
            backup_manager = BackupManager()
            backup_manager.start_live_monitoring()
    except Exception as exc:
        print(f"{ui.theme.FG_WARN}Live-синхронизация не запустилась: "
              f"{exc}{ui.theme.RESET}")

    if DISPLAY_LIST_BACKUPS:
        list_backups()

    banner.print_welcome(data_profile=get_selected_data_file(), web_url=web_url)

    try:
        main_menu()
    except KeyboardInterrupt:
        print(f"\n{ui.theme.FG_WARN}Прервано пользователем.{ui.theme.RESET}")
    finally:
        if backup_manager is not None:
            backup_manager.stop_live_monitoring()
            print(f"{ui.theme.FG_MUTED}Live-синхронизация остановлена.{ui.theme.RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
