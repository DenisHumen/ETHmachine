"""Генератор названий и символов токенов для Lester Minter.

Цель — максимальная вариативность при сохранении правдоподобности (имена
должны выглядеть как реальные крипто-токены, а не как ASCII-шум).

Стратегия:
  • Имя собирается из нескольких независимых слотов: [adjective] +
    {theme-noun | mythology | element | tech | finance} [+ suffix].
  • Каждый слот имеет 30-150 вариантов; суммарное пространство комбинаций
    ~10^6, что снимает повторы при сотнях деплоев.
  • Иногда применяются стилизации (CamelCase, X-prefix, sci-fi suffix).
  • Символ генерируется отдельно из самого имени (initials/consonants) +
    случайные модификаторы; всегда UPPERCASE 3..6 символов.
"""
from __future__ import annotations

import random
import re
import string
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# Словари
# ---------------------------------------------------------------------------

_ADJECTIVES = [
    "Alpha", "Apex", "Astral", "Atomic", "Aurora", "Azure", "Binary", "Black",
    "Blazing", "Boundless", "Bright", "Celestial", "Chrono", "Cipher", "Clever",
    "Cobalt", "Cosmic", "Crimson", "Cyber", "Daring", "Dark", "Dawn", "Deep",
    "Digital", "Diamond", "Dynamic", "Eclipse", "Elite", "Eternal", "Ether",
    "Fierce", "Flux", "Frost", "Fusion", "Galactic", "Genesis", "Gilded",
    "Golden", "Grand", "Hyper", "Iconic", "Imperial", "Indigo", "Infinite",
    "Iron", "Jade", "Lone", "Lunar", "Lustrous", "Magma", "Marble", "Meta",
    "Mighty", "Mystic", "Nano", "Neon", "Nimbus", "Noble", "Nova", "Obsidian",
    "Onyx", "Orbital", "Pearl", "Phantom", "Pixel", "Polar", "Prime",
    "Prismatic", "Pulse", "Quantum", "Radiant", "Rapid", "Raven", "Reactive",
    "Royal", "Ruby", "Sapphire", "Savage", "Silver", "Silent", "Singular",
    "Solar", "Sonic", "Stellar", "Stoic", "Stormy", "Sublime", "Sunset",
    "Swift", "Synth", "Titan", "Twilight", "Ultra", "Velvet", "Vivid", "Void",
    "Wild", "Zen", "Zero",
]

_THEMES = {
    "animal": [
        "Wolf", "Panther", "Falcon", "Phoenix", "Lion", "Tiger", "Eagle",
        "Cobra", "Viper", "Hawk", "Shark", "Whale", "Bear", "Fox", "Owl",
        "Stag", "Dragon", "Kraken", "Mantis", "Lynx", "Raven", "Stallion",
        "Pegasus", "Griffin", "Hydra", "Manta", "Orca", "Wolverine", "Octopus",
    ],
    "space": [
        "Nebula", "Pulsar", "Quasar", "Comet", "Nova", "Orbit", "Galaxy",
        "Cosmos", "Stardust", "Eclipse", "Meteor", "Asteroid", "Singularity",
        "Vortex", "Helios", "Solaris", "Voyager", "Polaris", "Andromeda",
        "Sirius", "Vega", "Cetus", "Lyra", "Orion", "Nebulon", "Pleiades",
    ],
    "mythology": [
        "Odin", "Thor", "Loki", "Hermes", "Athena", "Apollo", "Artemis",
        "Hades", "Hera", "Zeus", "Anubis", "Ra", "Horus", "Osiris", "Bastet",
        "Quetzal", "Yggdrasil", "Valkyrie", "Olympus", "Asgard", "Avalon",
        "Excalibur", "Merlin", "Khepri", "Mjolnir", "Aether", "Chronos",
    ],
    "element": [
        "Iron", "Silver", "Gold", "Copper", "Cobalt", "Tungsten", "Mercury",
        "Plasma", "Crystal", "Quartz", "Onyx", "Amber", "Pearl", "Ruby",
        "Opal", "Topaz", "Jade", "Marble", "Granite", "Ember", "Frost",
        "Flame", "Magma", "Cinder", "Storm", "Thunder", "Lightning", "Mist",
        "Rain", "Glacier", "Volcano",
    ],
    "tech": [
        "Pixel", "Byte", "Quark", "Logic", "Vector", "Matrix", "Circuit",
        "Cipher", "Codex", "Protocol", "Vault", "Forge", "Engine", "Beacon",
        "Catalyst", "Reactor", "Grid", "Cluster", "Stack", "Frame", "Mesh",
        "Sphere", "Cube", "Prism", "Loop", "Node", "Edge", "Core", "Mainframe",
        "Lattice", "Helix", "Ledger", "Synapse",
    ],
    "finance": [
        "Capital", "Reserve", "Treasury", "Trust", "Vault", "Mint", "Anchor",
        "Bond", "Yield", "Equity", "Stake", "Bull", "Hedge", "Index", "Asset",
        "Coin", "Token", "Cash", "Funds", "Bank", "Stream", "Liquid",
        "Surplus", "Margin", "Quanta", "Tally", "Aurum",
    ],
    "abstract": [
        "Echo", "Mirage", "Whisper", "Spark", "Glow", "Bloom", "Drift",
        "Pulse", "Wave", "Wisp", "Aura", "Shade", "Glint", "Shimmer", "Dust",
        "Veil", "Surge", "Crest", "Bliss", "Charm", "Loop", "Flicker",
        "Halo", "Glitch", "Bounce", "Spire",
    ],
    "ancient": [
        "Atlas", "Sphinx", "Pharaoh", "Caesar", "Empire", "Citadel", "Bastion",
        "Oracle", "Templar", "Saga", "Rune", "Glyph", "Seal", "Crown",
        "Sceptre", "Throne", "Relic", "Chronicle", "Cathedral", "Pillar",
    ],
}

_SUFFIXES = [
    "Network", "Protocol", "Finance", "Labs", "Chain", "Coin", "Token",
    "DAO", "Capital", "X", "Pay", "Hub", "Swap", "Vault", "Bridge",
    "Field", "World", "Verse", "Domain", "Sphere", "Realm", "Edge", "Core",
    "Stack", "Forge", "Studio", "Works", "Foundation",
]

# Стилизации, иногда применяемые поверх (post-processing).
_STYLES = [
    "plain",        # "Stellar Wolf"
    "compact",      # "StellarWolf"
    "x_prefix",     # "xStellarWolf"
    "suffix",       # "StellarWolf Network"
    "fi_suffix",    # "StellarWolfFi"
    "swap_suffix",  # "StellarWolfSwap"
    "the_prefix",   # "The Stellar Wolf"
    "v2",           # "StellarWolf V2"
    "ai_suffix",    # "StellarWolfAI"
]

# Веса для тем — слегка повышены animal/space/mythology (они звучат "крипто-нативно").
_THEME_WEIGHTS = {
    "animal": 18, "space": 18, "mythology": 14, "element": 12,
    "tech": 14, "finance": 10, "abstract": 8, "ancient": 6,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _pick_theme(rng: random.Random) -> str:
    themes = list(_THEME_WEIGHTS.keys())
    weights = [_THEME_WEIGHTS[t] for t in themes]
    return rng.choices(themes, weights=weights, k=1)[0]


def _pick_word(seq: list[str], rng: random.Random) -> str:
    return rng.choice(seq)


def _apply_style(adj: str, noun: str, rng: random.Random) -> str:
    style = rng.choice(_STYLES)
    if style == "plain":
        return f"{adj} {noun}"
    if style == "compact":
        return f"{adj}{noun}"
    if style == "x_prefix":
        return f"x{adj}{noun}"
    if style == "suffix":
        return f"{adj}{noun} {_pick_word(_SUFFIXES, rng)}"
    if style == "fi_suffix":
        return f"{adj}{noun}Fi"
    if style == "swap_suffix":
        return f"{adj}{noun}Swap"
    if style == "the_prefix":
        return f"The {adj} {noun}"
    if style == "v2":
        return f"{adj}{noun} V{rng.choice([2, 3])}"
    if style == "ai_suffix":
        return f"{adj}{noun}AI"
    return f"{adj} {noun}"


def _consonants(s: str) -> str:
    return "".join(ch for ch in s if ch.isalpha() and ch.lower() not in "aeiou")


def _vowels(s: str) -> str:
    return "".join(ch for ch in s if ch.isalpha() and ch.lower() in "aeiou")


def _symbol_from_name(name: str, rng: random.Random, *,
                     min_len: int = 3, max_len: int = 6) -> str:
    """Выводит символ из имени: initials + consonants, в зависимости от стиля."""
    words = re.findall(r"[A-Za-z][a-z]*", name) or [name]
    target_len = rng.randint(min_len, max_len)

    strategy = rng.choices(
        ["initials", "first_word", "consonants", "mixed"],
        weights=[3, 3, 2, 2], k=1,
    )[0]

    if strategy == "initials" and len(words) >= 2:
        sym = "".join(w[0] for w in words[:max_len])
    elif strategy == "first_word":
        sym = words[0][:target_len]
    elif strategy == "consonants":
        cons = _consonants(words[0])
        if len(cons) < min_len and len(words) > 1:
            cons += _consonants(words[1])
        sym = cons[:target_len] or words[0][:target_len]
    else:  # mixed: первая буква + согласные остатка
        head = words[0][0]
        tail = _consonants(words[0][1:]) + (_consonants(words[1]) if len(words) > 1 else "")
        sym = (head + tail)[:target_len]

    sym = re.sub(r"[^A-Za-z]", "", sym).upper()
    # дополним случайной буквой если слишком коротко
    while len(sym) < min_len:
        sym += rng.choice(string.ascii_uppercase)
    return sym[:max_len]


def generate_token_metadata(
    *,
    seed: Optional[int] = None,
    used_symbols: Optional[Iterable[str]] = None,
    max_attempts: int = 30,
) -> dict:
    """Возвращает {name, symbol}.

    Если `used_symbols` передан — гарантирует, что выбранный символ не входит
    в этот сет (до `max_attempts` попыток; затем добавляет числовой суффикс).
    """
    rng = random.Random(seed) if seed is not None else random
    used = {s.upper() for s in (used_symbols or [])}

    for _ in range(max_attempts):
        theme = _pick_theme(rng)
        adj = _pick_word(_ADJECTIVES, rng)
        noun = _pick_word(_THEMES[theme], rng)
        # шанс пропустить прилагательное (короткое имя)
        if rng.random() < 0.15:
            name = noun + (rng.choice([" Network", "X", " DAO", "Fi", ""])
                           if rng.random() < 0.5 else "")
            name = name.strip()
        else:
            name = _apply_style(adj, noun, rng)

        # подравниваем имя: не длиннее 50 символов (валидация сайта)
        if len(name) > 50:
            name = name[:50].rstrip()

        symbol = _symbol_from_name(name, rng)
        if symbol not in used:
            return {"name": name, "symbol": symbol}

    # fallback: добавляем числовой суффикс к символу
    suffix = str(rng.randint(2, 99))
    base = _symbol_from_name(name, rng, min_len=3, max_len=4)
    return {"name": name, "symbol": (base + suffix)[:6]}


def generate_total_supply(rng: Optional[random.Random] = None,
                          lo: int = 100_000, hi: int = 1_000_000_000) -> int:
    """Генерирует «красивый» total supply: round numbers (1M, 100M, 1B) с шансами.
    Никогда не возвращает странных 17_293_481 — крипто-токены обычно круглые."""
    rng = rng or random
    # «канонические» supplies — выбираем чаще
    canonical = [
        100_000, 250_000, 500_000, 1_000_000, 5_000_000, 10_000_000,
        21_000_000, 50_000_000, 100_000_000, 250_000_000, 500_000_000,
        1_000_000_000,
    ]
    canonical = [c for c in canonical if lo <= c <= hi]
    if canonical and rng.random() < 0.75:
        return rng.choice(canonical)
    # иначе — round до миллиона
    raw = rng.randint(max(1, lo // 1_000_000), max(1, hi // 1_000_000))
    return int(raw) * 1_000_000


def generate_features(rng: Optional[random.Random] = None,
                      true_prob: float = 0.55) -> dict:
    """{mintable, burnable, pausable} — каждый независимо с заданной p(True)."""
    rng = rng or random
    return {
        "mintable": rng.random() < true_prob,
        "burnable": rng.random() < true_prob,
        "pausable": rng.random() < true_prob,
    }
