#!/usr/bin/env python3
"""
alpha_main.py  —  ETHmachine TUI (archinstall-style two-panel menu).

Replaces main.py with an ncurses two-panel interface.
Identical startup sequence: requirements > files > version > backup > config > data file.
Same handlers — calls the exact same module functions as main.py.

Target: Ubuntu 24.04 / 25.10  (Windows OK with `pip install windows-curses`)
"""

from __future__ import annotations

import curses
import locale
import os
import platform
import sys
import time
import csv
import unicodedata
from dataclasses import dataclass, field
from typing import Optional, Callable, List


# ===================================================================
#  Display-width helpers  (emoji / wide chars take 2 terminal columns)
# ===================================================================

def _char_width(ch: str) -> int:
    eaw = unicodedata.east_asian_width(ch)
    return 2 if eaw in ('W', 'F') else 1


def _dw(s: str) -> int:
    """Display width of a string (accounts for wide/emoji characters)."""
    return sum(_char_width(c) for c in s)


def _clip(s: str, max_w: int) -> str:
    """Clip string so its display width does not exceed *max_w*."""
    w = 0
    for i, ch in enumerate(s):
        cw = _char_width(ch)
        if w + cw > max_w:
            return s[:i]
        w += cw
    return s


def _pad(s: str, width: int) -> str:
    """Pad string with spaces to reach given display *width*."""
    dw = _dw(s)
    return s + ' ' * max(0, width - dw)


# ===================================================================
#  Pre-TUI bootstrap  (runs in normal terminal before curses starts)
# ===================================================================

def _bootstrap():
    """Startup exactly like main.py: requirements, files, version,
    backup, config, data file select, live monitoring, logo."""

    # 1. Requirements
    from modules.requirements_checker import check_requirements
    if not check_requirements():
        input("\nPress Enter to exit...")
        sys.exit(1)

    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)

    # 2. Files & dirs
    from main import check_and_create_files
    check_and_create_files()

    # 3. Version check
    from modules.GitHub.check_version import check_version
    check_version("ETHmachine")

    # 4. Backup
    from modules.backup import create_backup
    create_backup()
    print(Style.RESET_ALL, end='')

    # 5. Config validation
    from modules.config_validator import validate_configuration
    print(Fore.CYAN + "\n\U0001f50d Checking configuration..." + Style.RESET_ALL)
    if not validate_configuration():
        print(Fore.RED + "\n\u274c Configuration problems detected!" + Style.RESET_ALL)
        print(Fore.YELLOW + "Fix errors and restart the script." + Style.RESET_ALL)
        input("\nPress Enter to exit...")
        sys.exit(1)

    # 6. Data file selection
    from modules.data_manager import select_data_file
    select_data_file()

    # 7. Live monitoring (optional)
    backup_manager = None
    try:
        from config.modules.cfg_backup import (
            SFTP_LIVE_SYNC_ENABLE, SFTP_SERVER_INTO_BACKUP_ENABLE,
        )
        if SFTP_SERVER_INTO_BACKUP_ENABLE and SFTP_LIVE_SYNC_ENABLE:
            from modules.backup.backup_manager import BackupManager
            backup_manager = BackupManager()
            backup_manager.start_live_monitoring()
    except Exception as e:
        print(Fore.YELLOW + f"\u26a0\ufe0f Could not start live monitoring: {e}")

    try:
        from config.modules.cfg_backup import DISPLAY_LIST_BACKUPS
        if DISPLAY_LIST_BACKUPS:
            from modules.backup import list_backups
            list_backups()
    except Exception:
        pass

    # 8. Print logo
    from main import print_welcome_message
    print_welcome_message()

    return backup_manager


# ===================================================================
#  Handlers  (call the exact same modules as main.py)
# ===================================================================

def _run_handler(key: str):
    """Run the handler registered for *key*."""
    handler = _HANDLERS.get(key)
    if handler:
        handler()
    else:
        print(f"\n\u26a0\ufe0f  No handler for '{key}' yet.")
        input("Press Enter...")


def _get_os_type() -> str:
    s = platform.system().lower()
    return 'windows' if s == 'windows' else ('macos' if s == 'darwin' else 'linux')


# --- Balances ---------------------------------------------------------

def _h_check_wallet_balances_eth():
    from modules.eth.eth_get_balaces import check_wallet_balances_menu
    check_wallet_balances_menu()

def _h_check_token_balances():
    from modules.eth.eth_get_token_balance import check_token_balance_menu
    check_token_balance_menu()

def _h_check_wallet_balances_sol():
    from modules.sol.sol_get_balances import solana_balance_checker
    solana_balance_checker()

def _h_check_token_balances_sol():
    from main import show_wip_message
    show_wip_message("SOL Token Balance Checker")

def _h_eclipse_balance():
    from modules.sol.eclipse_get_balances import eclipse_balance_checker
    eclipse_balance_checker()

def _h_debank_checker():
    from modules.debank.debank_checker import debank_checker_menu
    debank_checker_menu()

def _h_debank_protocols():
    from modules.debank.debank_protocol_checker import debank_protocol_menu
    debank_protocol_menu()

# --- Transactions -----------------------------------------------------

def _h_eth_drainers():
    from modules.eth.eth_drainers import eth_drainers
    eth_drainers()

def _h_sol_drainers():
    from main import show_wip_message
    show_wip_message("SOL Drainers")

def _h_transfer_wallets():
    from main import MenuHandlers
    MenuHandlers._handle_transfer_wallets()

def _h_transfer_erc20():
    from modules.eth.transfer_erc20_tokens import run_transfer_erc20_tokens
    run_transfer_erc20_tokens()

def _h_relay_bridge():
    from modules.relay_link.relay_link import main as relay_bridge_main
    relay_bridge_main()

# --- Claimer ----------------------------------------------------------

def _h_zora_claimer():
    from modules.claim.zora_claimer.menu import claimer_menu
    claimer_menu()

# --- Twitter ----------------------------------------------------------

def _h_twitter_check():
    from modules.twitter.twitter_check import run_twitter_check
    run_twitter_check(_get_os_type())

def _h_twitter_info():
    from modules.twitter.twitter_check import run_twitter_check
    run_twitter_check(_get_os_type())

def _h_twitter_task():
    from modules.twitter.twitter_task_runner import run_twitter_tasks
    run_twitter_tasks()

# --- Projects ---------------------------------------------------------

def _h_pharos():
    from modules.pharos.menu import pharos_menu
    pharos_menu()

def _h_xstocks():
    from modules.xstocks.menu import xstocks_menu
    xstocks_menu()

def _h_abs_portal():
    from modules.abs.menu import abs_menu
    abs_menu()

def _h_neura():
    try:
        from modules.statistics.neura_stats import neura_statistics
        neura_statistics()
    except Exception as e:
        print(f"\n\u26a0\ufe0f  Neura Statistics unavailable: {e}")
        print(f"OS: {_get_os_type()}, Python: {platform.python_version()}")
        input("\nPress Enter...")

def _h_perle():
    from modules.statistics.perle.menu import perle_menu
    perle_menu()

# --- CEX > OKX --------------------------------------------------------

def _h_okx_withdraw():
    from modules.cex.okx.okx_withdraw import okx_withdraw
    okx_withdraw()

def _h_okx_balances():
    from modules.cex.okx.okx_SubAccount import get_balances_okx
    get_balances_okx()

def _h_okx_subaccount():
    from modules.cex.okx.okx_SubAccount import check_okx_subaccounts_and_balances
    check_okx_subaccounts_and_balances()

def _h_okx_spot():
    from modules.cex.okx.okx_SpotTrade import start_okx_spot_trading
    start_okx_spot_trading()

# --- CEX > Binance ----------------------------------------------------

def _h_binance_withdraw():
    from modules.cex.binance.binance_withdraw import binance_withdraw
    binance_withdraw()

def _h_binance_balances():
    from modules.cex.binance.binance_SubAccount import get_balances_binance
    get_balances_binance()

def _h_binance_subaccount():
    from modules.cex.binance.binance_SubAccount import subaccount_collector_binance
    subaccount_collector_binance()

# --- CEX > Bitget -----------------------------------------------------

def _h_bitget_withdraw():
    from modules.cex.bitget.bitget_withdraw import bitget_withdraw
    bitget_withdraw()

def _h_bitget_balances():
    from main import show_wip_message
    show_wip_message("Bitget Balances")

def _h_bitget_subaccount():
    from modules.cex.bitget.bitget_SubAccount import check_bitget_subaccounts_and_balances
    check_bitget_subaccounts_and_balances()

# --- CEX > MEXC -------------------------------------------------------

def _h_mexc_withdraw():
    from modules.cex.mexc.mexc_withdraw import mexc_withdraw
    mexc_withdraw()

# --- Tools ------------------------------------------------------------

def _h_gas_price():
    from modules.get_gas_price import check_all_gas_prices
    check_all_gas_prices()

def _h_gen_wallets():
    from main import MenuHandlers
    MenuHandlers._handle_generate_wallets()

def _h_convert_tool():
    from main import MenuHandlers
    MenuHandlers._handle_convert_tool()

def _h_password_gen():
    from modules.password_generator import password_generator_menu
    password_generator_menu()

def _h_nickname_gen():
    from modules.nickname_generator import generate_nicknames
    generate_nicknames()

def _h_fullname_gen():
    from modules.fullname_generator import generate_fullnames_menu
    generate_fullnames_menu()

def _h_check_proxy():
    from modules.check_proxy import check_proxy_menu
    check_proxy_menu()

def _h_last_tx():
    from modules.eth.eth_last_tx import check_last_transactions
    check_last_transactions()

def _h_discord_age():
    from main import MenuHandlers
    MenuHandlers._handle_discord_check()

def _h_email_checker():
    from modules.email.email_imap_checker import run_email_checker
    run_email_checker()

# --- Backup & Info ----------------------------------------------------

def _h_backup_menu():
    from modules.backup import backup_menu
    backup_menu()

def _h_info():
    from modules.info import info
    info()

# --- Exit -------------------------------------------------------------

def _h_exit():
    from main import show_exit_animation
    show_exit_animation()


# Handler registry  (key -> callable)
_HANDLERS: dict[str, Callable] = {
    # Balances
    'check_wallet_balances_eth': _h_check_wallet_balances_eth,
    'check_token_balances':      _h_check_token_balances,
    'check_wallet_balances_sol': _h_check_wallet_balances_sol,
    'check_token_balances_sol':  _h_check_token_balances_sol,
    'eclipse':                   _h_eclipse_balance,
    'debank_checker':            _h_debank_checker,
    'debank_protocols':          _h_debank_protocols,
    # Transactions
    'eth_drainers':              _h_eth_drainers,
    'sol_drainers':              _h_sol_drainers,
    'transfer_w2w':              _h_transfer_wallets,
    'transfer_erc20':            _h_transfer_erc20,
    'relay_bridge':              _h_relay_bridge,
    # Claimer
    'zora_claimer':              _h_zora_claimer,
    # Twitter
    'twitter_check':             _h_twitter_check,
    'twitter_info':              _h_twitter_info,
    'twitter_task':              _h_twitter_task,
    # Projects
    'pharos':                    _h_pharos,
    'xstocks':                   _h_xstocks,
    'abs_portal':                _h_abs_portal,
    'neura':                     _h_neura,
    'perle':                     _h_perle,
    # CEX > OKX
    'withdraw_from_okx':         _h_okx_withdraw,
    'get_balances_okx':          _h_okx_balances,
    'subaccount_collector_okx':  _h_okx_subaccount,
    'spot_trade_okx':            _h_okx_spot,
    # CEX > Binance
    'withdraw_from_binance':     _h_binance_withdraw,
    'get_balances_binance':      _h_binance_balances,
    'subaccount_collector_binance': _h_binance_subaccount,
    # CEX > Bitget
    'withdraw_from_bitget':      _h_bitget_withdraw,
    'get_balances_bitget':       _h_bitget_balances,
    'subaccount_collector_bitget': _h_bitget_subaccount,
    # CEX > MEXC
    'withdraw_from_mexc':        _h_mexc_withdraw,
    # Tools
    'check_gas_price':           _h_gas_price,
    'generate_wallets':          _h_gen_wallets,
    'convert_tool':              _h_convert_tool,
    'password_generator':        _h_password_gen,
    'nickname_generator':        _h_nickname_gen,
    'fullname_generator':        _h_fullname_gen,
    'check_proxy':               _h_check_proxy,
    'last_transactions':         _h_last_tx,
    'check_age_discord':         _h_discord_age,
    'email_checker':             _h_email_checker,
    # Backup & Info
    'backup_menu':               _h_backup_menu,
    'info':                      _h_info,
    # Exit
    'exit':                      _h_exit,
}


# ===================================================================
#  Menu Data Model
# ===================================================================

@dataclass
class MenuNode:
    """A single menu entry; may contain children (forming a tree)."""
    key: str
    label: str
    description: str = ""
    icon: str = ""
    children: List["MenuNode"] = field(default_factory=list)
    handler_key: str = ""       # key into _HANDLERS; empty = branch / stub
    is_wip: bool = False

    @property
    def has_children(self) -> bool:
        return bool(self.children)


@dataclass
class TreeLine:
    """One row produced by flattening a tree for the right panel."""
    node: MenuNode
    depth: int
    prefix: str        # accumulated indent  ("   ", "|  ", ...)
    connector: str     # "|- " or "`- "
    is_branch: bool    # True => node has children


def flatten_tree(nodes: List[MenuNode], prefix: str = "", depth: int = 0) -> List[TreeLine]:
    """Recursively flatten *nodes* into a printable list."""
    lines: List[TreeLine] = []
    for i, node in enumerate(nodes):
        last = i == len(nodes) - 1
        conn = "\u2514\u2500 " if last else "\u251c\u2500 "
        lines.append(TreeLine(node, depth, prefix, conn, node.has_children))
        if node.has_children:
            child_pfx = prefix + ("   " if last else "\u2502  ")
            lines.extend(flatten_tree(node.children, child_pfx, depth + 1))
    return lines


# ===================================================================
#  Menu Definition  (mirrors main.py + menu_config.py exactly)
# ===================================================================

def build_menu() -> List[MenuNode]:
    return [
        # -- 1. BALANCES -----------------------------------------------
        MenuNode("check_balances", "BALANCES", "Check native/token balances", "\U0001f4b2", [
            MenuNode("eth", "ETH", "Ethereum & EVM chains", "\U0001f4b2", [
                MenuNode("chk_eth_bal", "Check Wallet Balances",
                         "Check ETH wallet balances", "\U0001f4b2",
                         handler_key="check_wallet_balances_eth"),
                MenuNode("chk_tok_bal", "Check Token Balances",
                         "Check ERC20 token balances", "\U0001f4b2",
                         handler_key="check_token_balances"),
            ]),
            MenuNode("sol", "SOL", "Solana", "\U0001f4b2", [
                MenuNode("chk_sol_bal", "Check Wallet Balances",
                         "Check SOL wallet balances", "\U0001f4b2",
                         handler_key="check_wallet_balances_sol"),
                MenuNode("chk_sol_tok", "Check Token Balances",
                         "Check SOL token balances (WIP)", "\U0001f4b2",
                         handler_key="check_token_balances_sol", is_wip=True),
            ]),
            MenuNode("eclipse", "Eclipse", "Eclipse Network", "\U0001f4b2",
                     handler_key="eclipse"),
            MenuNode("debank_checker", "DeBank Checker",
                     "Check all balances via DeBank", "\U0001f3e6",
                     handler_key="debank_checker"),
            MenuNode("debank_protocols", "DeBank Protocols",
                     "DeFi positions (staking, lending, locked)", "\U0001f517",
                     handler_key="debank_protocols"),
        ]),

        # -- 2. TRANSACTIONS -------------------------------------------
        MenuNode("transactions", "TRANSACTIONS", "Wallet-to-wallet transactions", "\U0001f680", [
            MenuNode("drainers", "Drainers", "Collect balances to main wallet", "\U0001f9f9", [
                MenuNode("eth_drainers", "ETH Drainers", "Collect ETH", "\U0001f4b2",
                         handler_key="eth_drainers"),
                MenuNode("sol_drainers", "SOL Drainers", "Collect SOL (WIP)", "\U0001f4b2",
                         handler_key="sol_drainers", is_wip=True),
            ]),
            MenuNode("transfer_w2w", "Transfer Wallets to Wallets",
                     "Send native tokens between wallets", "\U0001f504",
                     handler_key="transfer_w2w"),
            MenuNode("transfer_erc20", "Transfer ERC20 Tokens",
                     "Send ERC20 tokens between wallets", "\U0001f48e",
                     handler_key="transfer_erc20"),
            MenuNode("relay_bridge", "Relay Bridge",
                     "Bridge between chains via Relay Link", "\U0001f309",
                     handler_key="relay_bridge"),
        ]),

        # -- 3. Claimer ------------------------------------------------
        MenuNode("claimer", "Claimer", "Claim rewards Zora Protocol (Base/Zora)", "\U0001f4b0", [
            MenuNode("zora_claimer", "Zora Claimer",
                     "Claim Zora Protocol rewards (Base/Zora)", "\U0001f48e",
                     handler_key="zora_claimer"),
        ]),

        # -- 4. Twitter ------------------------------------------------
        MenuNode("twitter", "Twitter", "Twitter data collection", "\U0001f426", [
            MenuNode("twitter_check", "Twitter Check",
                     "Check Twitter accounts", "\U0001f426",
                     handler_key="twitter_check"),
            MenuNode("twitter_info", "Twitter Info",
                     "Get Twitter information", "\U0001f426",
                     handler_key="twitter_info"),
            MenuNode("twitter_task", "Twitter Task",
                     "Execute Twitter tasks", "\U0001f426",
                     handler_key="twitter_task"),
        ]),

        # -- 5. PROJECTS -----------------------------------------------
        MenuNode("projects", "PROJECTS", "Project automation", "\U0001f3ae", [
            MenuNode("pharos", "Pharos Testnet",
                     "Faucet, Check-in, Quests, Send & Verify", "\U0001f7e2",
                     handler_key="pharos"),
            MenuNode("xstocks", "xStocks DeFi",
                     "Register, GM, Referrals, Points", "\U0001f7e2",
                     handler_key="xstocks"),
            MenuNode("abs_portal", "Abstract Portal",
                     "Stats, Badges, XP Recap", "\U0001f7e2",
                     handler_key="abs_portal"),
            MenuNode("neura", "Neura",
                     "ETHmachine statistics (Windows only)", "\U0001f7e2",
                     handler_key="neura"),
            MenuNode("perle", "Perle",
                     "Check SOL wallet eligibility", "\U0001f7e2",
                     handler_key="perle"),
        ]),

        # -- 6. CEX ----------------------------------------------------
        MenuNode("cex", "CEX", "Exchange functionality", "\U0001f3e6", [
            MenuNode("okx", "OKX", "OKX operations", "\U0001f4b2", [
                MenuNode("withdraw_okx", "Withdraw from OKX",
                         "Withdraw from OKX", "\U0001f4b2",
                         handler_key="withdraw_from_okx"),
                MenuNode("bal_okx", "Get Balances",
                         "Get OKX balances", "\U0001f4b2",
                         handler_key="get_balances_okx"),
                MenuNode("sub_okx", "Subaccount Collector",
                         "Collect OKX subaccounts", "\U0001f4b2",
                         handler_key="subaccount_collector_okx"),
                MenuNode("spot_okx", "Auto Spot Trade",
                         "Spot trading on OKX", "\U0001f4b2",
                         handler_key="spot_trade_okx"),
            ]),
            MenuNode("binance", "Binance", "Binance operations", "\U0001f4b2", [
                MenuNode("withdraw_bin", "Withdraw from Binance",
                         "Withdraw from Binance", "\U0001f4b2",
                         handler_key="withdraw_from_binance"),
                MenuNode("bal_bin", "Get Balances",
                         "Get Binance balances", "\U0001f4b2",
                         handler_key="get_balances_binance"),
                MenuNode("sub_bin", "Subaccount Collector",
                         "Collect Binance subaccounts", "\U0001f4b2",
                         handler_key="subaccount_collector_binance"),
            ]),
            MenuNode("bitget", "Bitget", "Bitget operations", "\U0001f4b2", [
                MenuNode("withdraw_bit", "Withdraw from Bitget",
                         "Withdraw from Bitget", "\U0001f4b2",
                         handler_key="withdraw_from_bitget"),
                MenuNode("bal_bit", "Get Balances",
                         "Get Bitget balances (WIP)", "\U0001f4b2",
                         handler_key="get_balances_bitget", is_wip=True),
                MenuNode("sub_bit", "Subaccount Collector",
                         "Collect Bitget subaccounts", "\U0001f4b2",
                         handler_key="subaccount_collector_bitget"),
            ]),
            MenuNode("mexc", "MEXC", "MEXC operations", "\U0001f4b2", [
                MenuNode("withdraw_mexc", "Withdraw from MEXC",
                         "Withdraw from MEXC", "\U0001f4b2",
                         handler_key="withdraw_from_mexc"),
            ]),
        ]),

        # -- 7. Tools --------------------------------------------------
        MenuNode("tools", "Tools", "Miscellaneous utilities", "\U0001f9f0", [
            MenuNode("gas", "Check Gas Price",
                     "Check current gas prices", "\u26fd",
                     handler_key="check_gas_price"),
            MenuNode("gen_wallets", "Generate Wallets",
                     "Generate wallets", "\U0001fa99",
                     handler_key="generate_wallets"),
            MenuNode("conv_tool", "ETH/SOL Convert Tool",
                     "Mnemonic/privkey to wallet address", "\U0001f6e0\ufe0f",
                     handler_key="convert_tool"),
            MenuNode("pwd_gen", "Password Generator",
                     "Generate passwords", "\U0001f511",
                     handler_key="password_generator"),
            MenuNode("nick_gen", "Nickname Generator",
                     "Generate human-like nicknames", "\U0001f3ad",
                     handler_key="nickname_generator"),
            MenuNode("name_gen", "Fullname Generator",
                     "Generate names (RU/UA/ENG)", "\U0001f464",
                     handler_key="fullname_generator"),
            MenuNode("chk_proxy", "Check Proxy",
                     "Validate proxy connections", "\U0001f6e0\ufe0f",
                     handler_key="check_proxy"),
            MenuNode("last_tx", "Last Transactions",
                     "Check last transactions", "\U0001f5c2\ufe0f",
                     handler_key="last_transactions"),
            MenuNode("discord_age", "Check Age Discord",
                     "Check Discord account age", "\U0001f5c2\ufe0f",
                     handler_key="check_age_discord"),
            MenuNode("email_chk", "Email IMAP Checker",
                     "Check email accounts via IMAP", "\U0001f4e7",
                     handler_key="email_checker"),
        ]),

        # -- 8. Backup -------------------------------------------------
        MenuNode("backup", "Backup", "Local & SFTP backups", "\U0001f4be",
                 handler_key="backup_menu"),

        # -- 9. INFO ---------------------------------------------------
        MenuNode("info", "INFO", "Information about all menu items", "\U0001f4d6",
                 handler_key="info"),

        # -- 10. Exit --------------------------------------------------
        MenuNode("exit", "Exit", "Exit the program", "\u274c",
                 handler_key="exit"),
    ]


# ===================================================================
#  Color Theme
# ===================================================================

class C:
    NORMAL    = 1
    HIGHLIGHT = 2
    BORDER    = 3
    HEADER    = 4
    DIM       = 5
    BRANCH    = 6
    LEAF      = 7
    STATUS    = 8
    ACCENT    = 9
    TITLE_ON  = 10
    TITLE_OFF = 11
    SEL_OFF   = 12
    DIALOG    = 13
    COUNTER   = 14
    WIP       = 15


def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(C.NORMAL,    curses.COLOR_WHITE,   -1)
    curses.init_pair(C.HIGHLIGHT, curses.COLOR_BLACK,   curses.COLOR_CYAN)
    curses.init_pair(C.BORDER,    curses.COLOR_CYAN,    -1)
    curses.init_pair(C.HEADER,    curses.COLOR_BLACK,   curses.COLOR_GREEN)
    curses.init_pair(C.DIM,       curses.COLOR_WHITE,   -1)
    curses.init_pair(C.BRANCH,    curses.COLOR_YELLOW,  -1)
    curses.init_pair(C.LEAF,      curses.COLOR_GREEN,   -1)
    curses.init_pair(C.STATUS,    curses.COLOR_BLACK,   curses.COLOR_WHITE)
    curses.init_pair(C.ACCENT,    curses.COLOR_YELLOW,  -1)
    curses.init_pair(C.TITLE_ON,  curses.COLOR_CYAN,    -1)
    curses.init_pair(C.TITLE_OFF, curses.COLOR_WHITE,   -1)
    curses.init_pair(C.SEL_OFF,   curses.COLOR_CYAN,    -1)
    curses.init_pair(C.DIALOG,    curses.COLOR_YELLOW,  -1)
    curses.init_pair(C.COUNTER,   curses.COLOR_WHITE,   -1)
    curses.init_pair(C.WIP,       curses.COLOR_RED,     -1)


# ===================================================================
#  Safe drawing helpers
# ===================================================================

def saddstr(win, y: int, x: int, text: str, attr: int = 0):
    """addstr that silently clips to window boundaries (display-width aware)."""
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x < 0 or x >= w:
        return
    text = _clip(str(text), w - x)
    if not text:
        return
    try:
        win.addstr(y, x, text, attr)
    except curses.error:
        pass


def hline(win, y: int, x: int, length: int, attr: int = 0):
    for i in range(length):
        saddstr(win, y, x + i, "\u2500", attr)


def vline(win, y: int, x: int, length: int, attr: int = 0):
    for i in range(length):
        saddstr(win, y + i, x, "\u2502", attr)


# ===================================================================
#  TUI Application
# ===================================================================

ENTER_KEYS = {curses.KEY_ENTER, 10, 13}


class App:
    MIN_W = 60
    MIN_H = 14

    def __init__(self, scr):
        self.scr = scr
        self.menu = build_menu()

        # Left panel state
        self.li = 0          # selected index
        self.ls = 0          # scroll offset

        # Right panel state (flattened tree)
        self.tree: List[TreeLine] = []
        self.ri = 0          # selected index
        self.rs = 0          # scroll offset
        self._rcy = 4        # right content start y

        # Focus & run state
        self.panel = "L"     # "L" or "R"
        self.running = True
        self._should_exit = False

        # Curses setup
        curses.curs_set(0)
        init_colors()
        scr.keypad(True)
        scr.timeout(100)
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        try:
            sys.stdout.write("\033[?1000h")
            sys.stdout.flush()
        except OSError:
            pass

        self._rebuild()

    # -- helpers -------------------------------------------------------

    def _rebuild(self):
        """Rebuild right-panel tree from the currently selected category."""
        if 0 <= self.li < len(self.menu):
            self.tree = flatten_tree(self.menu[self.li].children)
        else:
            self.tree = []
        self.ri = 0
        self.rs = 0

    @property
    def H(self): return self.scr.getmaxyx()[0]
    @property
    def W(self): return self.scr.getmaxyx()[1]
    @property
    def lw(self):
        """Left panel width (~30%, clamped 22..38)."""
        return max(22, min(38, self.W * 30 // 100))
    @property
    def rw(self): return self.W - self.lw
    @property
    def content_h(self):
        """Rows available inside a panel (header + top border + bottom border + status)."""
        return self.H - 4

    # -- main loop -----------------------------------------------------

    def run(self):
        try:
            while self.running:
                self._draw()
                self._input()
        finally:
            try:
                sys.stdout.write("\033[?1000l")
                sys.stdout.flush()
            except OSError:
                pass

    # ==================================================================
    #  Drawing
    # ==================================================================

    def _draw(self):
        self.scr.erase()
        h, w = self.H, self.W
        if h < self.MIN_H or w < self.MIN_W:
            msg = f"Terminal too small ({w}x{h}).  Need {self.MIN_W}x{self.MIN_H}+"
            saddstr(self.scr, h // 2, max(0, (w - len(msg)) // 2), msg,
                    curses.color_pair(C.ACCENT) | curses.A_BOLD)
            self.scr.refresh()
            return
        self._draw_header()
        self._draw_frame()
        self._draw_left()
        self._draw_right()
        self._draw_status()
        self.scr.refresh()

    def _draw_header(self):
        attr = curses.color_pair(C.HEADER) | curses.A_BOLD
        saddstr(self.scr, 0, 0, " ETHmachine ".center(self.W), attr)

    def _draw_frame(self):
        h, w, lw = self.H, self.W, self.lw
        a = curses.color_pair(C.BORDER)
        top, bot = 1, h - 2

        # corners
        saddstr(self.scr, top, 0,     "\u250c", a)
        saddstr(self.scr, top, w - 1, "\u2510", a)
        saddstr(self.scr, bot, 0,     "\u2514", a)
        saddstr(self.scr, bot, w - 1, "\u2518", a)

        # horizontal borders
        hline(self.scr, top, 1, w - 2, a)
        hline(self.scr, bot, 1, w - 2, a)

        # vertical borders + divider
        for y in range(top + 1, bot):
            saddstr(self.scr, y, 0,     "\u2502", a)
            saddstr(self.scr, y, w - 1, "\u2502", a)
            saddstr(self.scr, y, lw,    "\u2502", a)

        # T-junctions
        saddstr(self.scr, top, lw, "\u252c", a)
        saddstr(self.scr, bot, lw, "\u2534", a)

        # Panel titles
        la = curses.color_pair(C.TITLE_ON if self.panel == "L" else C.TITLE_OFF) | curses.A_BOLD
        saddstr(self.scr, top, 2, " Menu ", la)

        ra = curses.color_pair(C.TITLE_ON if self.panel == "R" else C.TITLE_OFF) | curses.A_BOLD
        if self.menu:
            cat = self.menu[self.li]
            icon = cat.icon + " " if cat.icon else ""
            saddstr(self.scr, top, lw + 2, f" {icon}{cat.label} ", ra)

        # Counters on bottom border
        cnt = f" {self.li + 1}/{len(self.menu)} "
        saddstr(self.scr, bot, 2, cnt, curses.color_pair(C.COUNTER) | curses.A_DIM)
        if self.tree:
            rcnt = f" {self.ri + 1}/{len(self.tree)} "
            saddstr(self.scr, bot, lw + 2, rcnt,
                    curses.color_pair(C.COUNTER) | curses.A_DIM)

    # -- left panel (categories) ---------------------------------------

    def _draw_left(self):
        ch = self.content_h
        lw = self.lw
        active = self.panel == "L"

        # scroll clamp
        if self.li < self.ls:
            self.ls = self.li
        elif self.li >= self.ls + ch:
            self.ls = self.li - ch + 1

        for i in range(ch):
            idx = self.ls + i
            if idx >= len(self.menu):
                break
            node = self.menu[idx]
            y = 2 + i
            sel = idx == self.li

            if sel and active:
                attr = curses.color_pair(C.HIGHLIGHT) | curses.A_BOLD
            elif sel:
                attr = curses.color_pair(C.SEL_OFF) | curses.A_BOLD
            else:
                attr = curses.color_pair(C.NORMAL)

            icon = f"{node.icon} " if node.icon else "  "
            mk = " \u25ba " if sel else "   "
            line = f"{mk}{icon}{node.label}"
            saddstr(self.scr, y, 1, _pad(line, lw - 1), attr)

        # scroll indicators
        a_ind = curses.color_pair(C.ACCENT) | curses.A_BOLD
        if self.ls > 0:
            saddstr(self.scr, 2, lw - 2, "\u25b2", a_ind)
        if self.ls + ch < len(self.menu):
            saddstr(self.scr, 2 + ch - 1, lw - 2, "\u25bc", a_ind)

    # -- right panel (tree view) ---------------------------------------

    def _draw_right(self):
        lw = self.lw
        rw = self.rw
        active = self.panel == "R"

        # category description
        desc = self.menu[self.li].description if self.menu else ""
        if desc:
            saddstr(self.scr, 2, lw + 3, desc,
                    curses.color_pair(C.DIM) | curses.A_DIM)
            # thin separator
            for x in range(lw + 2, lw + rw - 1):
                saddstr(self.scr, 3, x, "\u2500",
                        curses.color_pair(C.BORDER) | curses.A_DIM)
            self._rcy = 4
        else:
            self._rcy = 2

        tree_h = (self.H - 2) - self._rcy
        if tree_h <= 0:
            return

        # leaf item (no children) — show hint
        node = self.menu[self.li] if self.menu else None
        if node and not node.has_children:
            if node.handler_key:
                saddstr(self.scr, self._rcy, lw + 3, "Press Enter to execute",
                        curses.color_pair(C.LEAF))
            else:
                saddstr(self.scr, self._rcy, lw + 3, "(no sub-items)",
                        curses.color_pair(C.DIM) | curses.A_DIM)
            return

        if not self.tree:
            saddstr(self.scr, self._rcy, lw + 3, "(no sub-items)",
                    curses.color_pair(C.DIM) | curses.A_DIM)
            return

        # scroll clamp
        if self.ri < self.rs:
            self.rs = self.ri
        elif self.ri >= self.rs + tree_h:
            self.rs = self.ri - tree_h + 1

        for i in range(tree_h):
            idx = self.rs + i
            if idx >= len(self.tree):
                break
            tl = self.tree[idx]
            y = self._rcy + i

            pfx_text = f"{tl.prefix}{tl.connector}"
            icon = f"{tl.node.icon} " if tl.node.icon else ""
            label = f"{icon}{tl.node.label}"
            wip = " [Not Ready]" if tl.node.is_wip else ""
            d = f" \u2014 {tl.node.description}" if tl.node.description else ""

            sel = idx == self.ri and active

            if sel:
                full = f" {pfx_text}{label}{wip}{d} "
                saddstr(self.scr, y, lw + 1, _pad(full, rw - 2),
                        curses.color_pair(C.HIGHLIGHT) | curses.A_BOLD)
            else:
                saddstr(self.scr, y, lw + 3, pfx_text,
                        curses.color_pair(C.BORDER) | curses.A_DIM)
                lx = lw + 3 + _dw(pfx_text)
                la = (curses.color_pair(C.BRANCH) | curses.A_BOLD
                      if tl.is_branch
                      else curses.color_pair(C.LEAF))
                saddstr(self.scr, y, lx, label, la)
                if wip:
                    saddstr(self.scr, y, lx + _dw(label), wip,
                            curses.color_pair(C.WIP) | curses.A_BOLD)
                if d:
                    saddstr(self.scr, y, lx + _dw(label) + _dw(wip), d,
                            curses.color_pair(C.DIM) | curses.A_DIM)

        # scroll indicators
        a_ind = curses.color_pair(C.ACCENT) | curses.A_BOLD
        if self.rs > 0:
            saddstr(self.scr, self._rcy, lw + rw - 3, "\u25b2", a_ind)
        if self.rs + tree_h < len(self.tree):
            saddstr(self.scr, self._rcy + tree_h - 1, lw + rw - 3, "\u25bc", a_ind)

    # -- status bar ----------------------------------------------------

    def _draw_status(self):
        attr = curses.color_pair(C.STATUS)
        if self.panel == "L":
            txt = " \u2191\u2193 Navigate  \u2192/Enter Detail  Tab Switch  q Quit "
        else:
            txt = " \u2191\u2193 Navigate  \u2190/Esc Back  Enter Run  Tab Switch  q Quit "
        saddstr(self.scr, self.H - 1, 0, txt.ljust(self.W), attr)

    # ==================================================================
    #  Input
    # ==================================================================

    def _input(self):
        try:
            k = self.scr.getch()
        except curses.error:
            return
        if k == -1:
            return

        if k == curses.KEY_RESIZE:
            curses.update_lines_cols()
            self.scr.clear()
            return
        if k == curses.KEY_MOUSE:
            self._mouse()
            return
        if k == ord("q"):
            self.running = False
            return
        if k == 27:  # Escape
            if self.panel == "R":
                self.panel = "L"
            else:
                self.running = False
            return
        if k == ord("\t"):
            self._toggle()
            return

        if self.panel == "L":
            self._key_left(k)
        else:
            self._key_right(k)

    def _toggle(self):
        if self.panel == "L" and self.tree:
            self.panel = "R"
        else:
            self.panel = "L"

    # -- left panel keys -----------------------------------------------

    def _key_left(self, k):
        n = len(self.menu)
        if n == 0:
            return
        if k in (curses.KEY_UP, ord("k")):
            self.li = max(0, self.li - 1); self._rebuild()
        elif k in (curses.KEY_DOWN, ord("j")):
            self.li = min(n - 1, self.li + 1); self._rebuild()
        elif k == curses.KEY_HOME:
            self.li = 0; self._rebuild()
        elif k == curses.KEY_END:
            self.li = n - 1; self._rebuild()
        elif k == curses.KEY_PPAGE:
            self.li = max(0, self.li - self.content_h); self._rebuild()
        elif k == curses.KEY_NPAGE:
            self.li = min(n - 1, self.li + self.content_h); self._rebuild()
        elif k == curses.KEY_RIGHT or k in ENTER_KEYS:
            node = self.menu[self.li]
            if node.has_children:
                self.panel = "R"
            elif node.handler_key:
                self._run(node)

    # -- right panel keys ----------------------------------------------

    def _key_right(self, k):
        n = len(self.tree)
        if n == 0:
            self.panel = "L"; return
        if k in (curses.KEY_UP, ord("k")):
            self.ri = max(0, self.ri - 1)
        elif k in (curses.KEY_DOWN, ord("j")):
            self.ri = min(n - 1, self.ri + 1)
        elif k == curses.KEY_HOME:
            self.ri = 0
        elif k == curses.KEY_END:
            self.ri = n - 1
        elif k == curses.KEY_PPAGE:
            self.ri = max(0, self.ri - self.content_h)
        elif k == curses.KEY_NPAGE:
            self.ri = min(n - 1, self.ri + self.content_h)
        elif k == curses.KEY_LEFT:
            self.panel = "L"
        elif k in ENTER_KEYS:
            self._action()

    # -- mouse ---------------------------------------------------------

    def _mouse(self):
        try:
            _, mx, my, _, bs = curses.getmouse()
        except curses.error:
            return

        clicked = bs & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED)
        scroll_up = bs & getattr(curses, "BUTTON4_PRESSED", 0)
        scroll_dn = bs & getattr(curses, "BUTTON5_PRESSED", 0)

        if scroll_up or scroll_dn:
            delta = -3 if scroll_up else 3
            if mx < self.lw:
                self.li = max(0, min(len(self.menu) - 1, self.li + delta))
                self._rebuild()
            elif mx > self.lw:
                self.ri = max(0, min(len(self.tree) - 1, self.ri + delta))
            return

        if not clicked:
            return
        if my < 2 or my >= self.H - 2:
            return

        if mx < self.lw:
            idx = self.ls + (my - 2)
            if 0 <= idx < len(self.menu):
                self.panel = "L"
                if self.li != idx:
                    self.li = idx; self._rebuild()
                else:
                    node = self.menu[self.li]
                    if node.has_children:
                        self.panel = "R"
                    elif node.handler_key:
                        self._run(node)
        elif mx > self.lw:
            idx = self.rs + (my - self._rcy)
            if 0 <= idx < len(self.tree):
                self.panel = "R"
                if self.ri == idx:
                    self._action()
                else:
                    self.ri = idx

    # -- execute -------------------------------------------------------

    def _action(self):
        """Run the handler of the selected tree node."""
        if not (0 <= self.ri < len(self.tree)):
            return
        node = self.tree[self.ri].node
        self._run(node)

    def _run(self, node: MenuNode):
        """Leave curses, execute the handler, re-enter curses."""
        hk = node.handler_key
        if not hk:
            self._dialog(node.label, node.description or "(no handler)")
            return

        # Special: exit handler
        if hk == "exit":
            curses.def_prog_mode()
            curses.endwin()
            _run_handler(hk)
            self.running = False
            self._should_exit = True
            return

        curses.def_prog_mode()
        curses.endwin()

        try:
            _run_handler(hk)
        except KeyboardInterrupt:
            print("\n\nInterrupted.")
        except Exception as exc:
            print(f"\nError: {exc}")

        print()
        input("Press Enter to return to menu...")

        curses.reset_prog_mode()
        self.scr.clear()
        self.scr.refresh()

    # -- modal dialog --------------------------------------------------

    def _dialog(self, title: str, msg: str):
        h, w = self.H, self.W
        dw = max(30, min(56, w - 4))
        dh = 7
        dy = max(0, (h - dh) // 2)
        dx = max(0, (w - dw) // 2)

        ba = curses.color_pair(C.DIALOG) | curses.A_BOLD
        ta = curses.color_pair(C.NORMAL)

        for cy in range(dy, dy + dh):
            saddstr(self.scr, cy, dx, " " * dw, ta)

        saddstr(self.scr, dy, dx,          "\u250c", ba)
        saddstr(self.scr, dy, dx + dw - 1, "\u2510", ba)
        saddstr(self.scr, dy + dh - 1, dx,          "\u2514", ba)
        saddstr(self.scr, dy + dh - 1, dx + dw - 1, "\u2518", ba)
        hline(self.scr, dy, dx + 1, dw - 2, ba)
        hline(self.scr, dy + dh - 1, dx + 1, dw - 2, ba)
        vline(self.scr, dy + 1, dx, dh - 2, ba)
        vline(self.scr, dy + 1, dx + dw - 1, dh - 2, ba)

        saddstr(self.scr, dy, dx + 2, f" {title} ", ba)
        saddstr(self.scr, dy + 2, dx + 3, msg[: dw - 6], ta)
        saddstr(self.scr, dy + 4, dx + 3, "Press any key\u2026",
                curses.color_pair(C.DIM) | curses.A_DIM)

        self.scr.refresh()
        self.scr.timeout(-1)
        self.scr.getch()
        self.scr.timeout(100)


# ===================================================================
#  Entry point
# ===================================================================

def tui_main(scr):
    app = App(scr)
    app.run()
    return app._should_exit


if __name__ == "__main__":
    locale.setlocale(locale.LC_ALL, "")

    if sys.platform == "win32":
        try:
            import curses as _c  # noqa: F811
        except ImportError:
            print("Windows requires 'windows-curses':  pip install windows-curses")
            sys.exit(1)

    # Pre-TUI startup (normal terminal — same as main.py)
    backup_manager = _bootstrap()

    # TUI
    try:
        should_exit = curses.wrapper(tui_main)
    finally:
        if backup_manager:
            backup_manager.stop_live_monitoring()

    if not should_exit:
        print("\nGoodbye!")
