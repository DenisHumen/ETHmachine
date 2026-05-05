"""Каталог сервисов и RPC для проверки прокси."""

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Service:
    name: str
    url: str
    category: str           # general / crypto_cex / crypto_data / social / rpc / geo / speed
    method: str = "GET"
    expect_keyword: str = ""  # необязательная подстрока, которая должна встретиться в ответе


# --- Базовые геолокаторы (L1) -------------------------------------------------
GEO_PROVIDERS: List[Service] = [
    Service("ipapi.co",   "https://ipapi.co/json/",                 "geo"),
    Service("ipinfo.io",  "https://ipinfo.io/json",                 "geo"),
    Service("ipify.org",  "https://api.ipify.org?format=json",      "geo"),
    Service("ifconfig.me","https://ifconfig.me/all.json",           "geo"),
]

# --- Общие сайты (L2+) --------------------------------------------------------
GENERAL: List[Service] = [
    Service("Google",      "https://www.google.com/generate_204",     "general"),
    Service("Cloudflare",  "https://www.cloudflare.com/cdn-cgi/trace","general"),
    Service("GitHub",      "https://api.github.com",                  "general"),
    Service("YouTube",     "https://www.youtube.com",                 "general"),
    Service("Wikipedia",   "https://en.wikipedia.org/wiki/Main_Page", "general"),
    Service("Amazon",      "https://www.amazon.com/robots.txt",       "general"),
    Service("Microsoft",   "https://www.microsoft.com/robots.txt",    "general"),
]

# --- Соцсети / мессенджеры (L2+) ---------------------------------------------
SOCIAL: List[Service] = [
    Service("Twitter/X",   "https://api.x.com",                       "social"),
    Service("Discord",     "https://discord.com/api/v10/gateway",     "social"),
    Service("Telegram",    "https://web.telegram.org",                "social"),
    Service("Reddit",      "https://www.reddit.com/.json",            "social"),
    Service("Instagram",   "https://www.instagram.com/robots.txt",    "social"),
    Service("TikTok",      "https://www.tiktok.com/robots.txt",       "social"),
]

# --- Криптобиржи / API (L3+) -------------------------------------------------
CRYPTO_CEX: List[Service] = [
    Service("Binance",     "https://api.binance.com/api/v3/ping",     "crypto_cex"),
    Service("OKX",         "https://www.okx.com/api/v5/public/time",  "crypto_cex"),
    Service("Bybit",       "https://api.bybit.com/v5/market/time",    "crypto_cex"),
    Service("Bitget",      "https://api.bitget.com/api/v2/public/time","crypto_cex"),
    Service("MEXC",        "https://api.mexc.com/api/v3/ping",        "crypto_cex"),
    Service("Coinbase",    "https://api.exchange.coinbase.com/time",  "crypto_cex"),
    Service("Kraken",      "https://api.kraken.com/0/public/Time",    "crypto_cex"),
]

# --- Крипто-данные (L3+) ------------------------------------------------------
CRYPTO_DATA: List[Service] = [
    Service("CoinGecko",   "https://api.coingecko.com/api/v3/ping",      "crypto_data"),
    Service("CoinMarketCap","https://api.coinmarketcap.com",             "crypto_data"),
    Service("Etherscan",   "https://api.etherscan.io",                   "crypto_data"),
    Service("DeBank",      "https://api.debank.com",                     "crypto_data"),
    Service("DexScreener", "https://api.dexscreener.com/latest/dex/tokens/0xdac17f958d2ee523a2206206994597c13d831ec7", "crypto_data"),
]

# --- EVM/Solana RPC (L3+) -----------------------------------------------------
@dataclass(frozen=True)
class RpcEndpoint:
    name: str
    url: str
    chain: str          # eth/base/arb/op/polygon/bsc/sol
    kind: str = "evm"   # evm / solana


RPCS: List[RpcEndpoint] = [
    RpcEndpoint("ETH (LlamaRPC)",   "https://eth.llamarpc.com",          "eth", "evm"),
    RpcEndpoint("ETH (Merkle)",     "https://eth.merkle.io",             "eth", "evm"),
    RpcEndpoint("Base",             "https://mainnet.base.org",          "base","evm"),
    RpcEndpoint("Arbitrum One",     "https://arb1.arbitrum.io/rpc",      "arb", "evm"),
    RpcEndpoint("Optimism",         "https://mainnet.optimism.io",       "op",  "evm"),
    RpcEndpoint("Polygon",          "https://polygon-rpc.com",           "polygon","evm"),
    RpcEndpoint("BSC",              "https://bsc-dataseed.binance.org",  "bsc", "evm"),
    RpcEndpoint("Solana",           "https://api.mainnet-beta.solana.com","sol","solana"),
]

# --- Speed-test endpoint (L4) -------------------------------------------------
SPEED_TEST = Service(
    "Cloudflare Speed (1MB)",
    "https://speed.cloudflare.com/__down?bytes=1048576",
    "speed",
)


def services_for_level(level: int) -> List[Service]:
    """Возвращает плоский список сервисов под уровень детализации."""
    if level <= 1:
        return []
    if level == 2:
        return GENERAL + SOCIAL
    if level == 3:
        return GENERAL + SOCIAL + CRYPTO_CEX + CRYPTO_DATA
    return GENERAL + SOCIAL + CRYPTO_CEX + CRYPTO_DATA


def rpcs_for_level(level: int) -> List[RpcEndpoint]:
    if level <= 2:
        return []
    return RPCS
