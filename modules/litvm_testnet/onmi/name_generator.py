"""Генератор meme-coin метаданных для Onmi.fun.

Цель — правдоподобные «meme-coin» имена/тикеры (Pepe-style, Doge-style,
Wojak-style и пр.), а не просто крипто-нативные название как у Lester.
Стратегия:
  • Слотовая сборка [adjective?] + [meme-noun] [+ suffix].
  • Веса акцентируют животных/мемы/космос.
  • Описание формируется только в `ONMI_DESCRIPTION_PROBABILITY` случаев.
"""
from __future__ import annotations

import random
import re
import string
from typing import Iterable, Optional


_ADJECTIVES = [
    "Mega", "Super", "Hyper", "Ultra", "Giga", "Tera", "Lucky", "Wild",
    "Crazy", "Funky", "Holy", "Sacred", "Spicy", "Frosty", "Cosmic",
    "Galactic", "Stellar", "Lunar", "Solar", "Neon", "Glitchy", "Royal",
    "Imperial", "Tactical", "Doge", "Pepe", "Frog", "Cat", "Dog", "Moon",
    "Sky", "Pixel", "Retro", "Cyber", "Quantum", "Atomic", "Sonic",
    "Astro", "Turbo", "Diamond", "Golden", "Silver", "Plasma", "Magic",
    "Fluffy", "Cute", "Tiny", "Big", "Fat", "Lazy", "Chad", "Based",
    "Comfy", "Wojak", "Smol",
]

_NOUNS = [
    "Pepe", "Doge", "Shiba", "Floki", "Wojak", "Chad", "Frog", "Cat", "Inu",
    "Bonk", "Moon", "Rocket", "Banana", "Mango", "Avocado", "Pizza",
    "Sushi", "Ramen", "Bagel", "Donut", "Cookie", "Cake", "Cheese",
    "Toast", "Bacon", "Pretzel", "Pickle", "Pepper", "Coffee",
    "Espresso", "Latte", "Boba", "Slime", "Goblin", "Gnome", "Ogre",
    "Troll", "Yeti", "Sasquatch", "Ghost", "Demon", "Angel", "Vampire",
    "Werewolf", "Zombie", "Unicorn", "Dragon", "Phoenix", "Griffin",
    "Kraken", "Octopus", "Squid", "Crab", "Shark", "Whale", "Dolphin",
    "Penguin", "Panda", "Koala", "Tiger", "Lion", "Wolf", "Fox",
    "Hamster", "Bunny", "Llama", "Alpaca", "Giraffe", "Capybara",
    "Hedgehog", "Sloth", "Owl", "Eagle", "Falcon", "Parrot", "Toucan",
    "Pigeon", "Duck", "Chicken", "Cow", "Pig", "Goat", "Sheep", "Camel",
    "Snail", "Ant", "Bee", "Butterfly", "Spider", "Scorpion", "Mantis",
    "Beetle", "Crystal", "Star", "Comet", "Planet", "Galaxy", "Nebula",
    "Vortex", "Portal", "Magic", "Spell", "Wand", "Crown", "Sword",
    "Shield", "Bonk", "Boop", "Yolo", "Hodl", "Lambo", "Wagmi", "Ngmi",
    "Fud", "Chad", "Smol",
]

_SUFFIXES = [
    "", "", "", "", "Coin", "Token", "Inu", "Cash", "Fi", "Verse", "World",
    "Lab", "Labs", "DAO", "Network", "Bro", "Bros", "Squad", "Gang",
    "Tribe", "Crew", "Army", "Cult", "Club", "Society",
]

_STYLES = [
    "plain", "compact", "compact", "the_prefix", "suffix", "x_prefix",
    "plain", "compact",
]

_DESCRIPTIONS = [
    "The most based meme coin on LITVM. WAGMI.",
    "A fully degenerate community-driven experiment. NFA, DYOR.",
    "Vibes only. Just a meme. No utility, no roadmap, only joy.",
    "Powered by pure copium and hopium.",
    "We're not financial advisors, but we are meme connoisseurs.",
    "The chad of meme coins. Probably nothing.",
    "100% meme. 0% utility. Maximum fun.",
    "Built different. Diamond hands only.",
    "Shibarmy reporting in. To the moon.",
    "Bork bork bork.",
    "Frog supremacy. Hop in.",
    "For the culture. For the lulz.",
    "Send it. Ape in. Don't think.",
    "Just memes. Probably worthless. Hilarious.",
    "Cute coin go brrr.",
    "Powered by hopium and good vibes.",
    "We have memes at home.",
    "Mascot energy. Let's gooo.",
    "Pure fun, zero promises.",
    "Onchain comedy gold.",
]


def _pick(seq, rng) -> str:
    return rng.choice(seq)


def _apply_style(adj: Optional[str], noun: str, rng) -> str:
    style = rng.choice(_STYLES)
    if adj is None:
        # имя только из существительного + suffix
        suf = _pick(_SUFFIXES, rng)
        return (f"{noun} {suf}" if suf and rng.random() < 0.5
                else f"{noun}{suf}").strip()
    if style == "plain":
        return f"{adj} {noun}"
    if style == "compact":
        return f"{adj}{noun}"
    if style == "the_prefix":
        return f"The {adj} {noun}"
    if style == "x_prefix":
        return f"x{adj}{noun}"
    if style == "suffix":
        suf = _pick(_SUFFIXES, rng)
        return f"{adj}{noun}{suf}" if suf else f"{adj}{noun}"
    return f"{adj} {noun}"


def _symbol_from_name(name: str, rng, *, min_len: int = 3, max_len: int = 6) -> str:
    words = re.findall(r"[A-Za-z][a-z]*", name) or [name]
    target = rng.randint(min_len, max_len)
    strategy = rng.choices(
        ["initials", "first_word", "consonants", "mixed"],
        weights=[3, 4, 2, 2], k=1,
    )[0]
    if strategy == "initials" and len(words) >= 2:
        sym = "".join(w[0] for w in words[:max_len])
    elif strategy == "first_word":
        sym = words[0][:target]
    elif strategy == "consonants":
        cons = "".join(c for c in words[0] if c.isalpha()
                       and c.lower() not in "aeiou")
        if len(cons) < min_len and len(words) > 1:
            cons += "".join(c for c in words[1] if c.isalpha()
                            and c.lower() not in "aeiou")
        sym = cons[:target] or words[0][:target]
    else:
        head = words[0][0]
        tail = "".join(c for c in words[0][1:] if c.isalpha()
                       and c.lower() not in "aeiou")
        if len(words) > 1:
            tail += "".join(c for c in words[1] if c.isalpha()
                            and c.lower() not in "aeiou")
        sym = (head + tail)[:target]

    sym = re.sub(r"[^A-Za-z]", "", sym).upper()
    while len(sym) < min_len:
        sym += rng.choice(string.ascii_uppercase)
    return sym[:max_len]


def generate_coin_metadata(
    *,
    seed: Optional[int] = None,
    used_symbols: Optional[Iterable[str]] = None,
    description_probability: float = 0.05,
    max_attempts: int = 30,
) -> dict:
    """Возвращает `{name, symbol, description}` (description может быть None)."""
    rng = random.Random(seed) if seed is not None else random
    used = {s.upper() for s in (used_symbols or [])}

    name = ""
    symbol = ""
    for _ in range(max_attempts):
        # 25% — только существительное (короткое имя в стиле "DogeCoin")
        adj = None if rng.random() < 0.25 else _pick(_ADJECTIVES, rng)
        noun = _pick(_NOUNS, rng)
        name = _apply_style(adj, noun, rng)
        if len(name) > 32:
            name = name[:32].rstrip()
        symbol = _symbol_from_name(name, rng)
        if symbol not in used:
            break
    else:
        # дополним числовым суффиксом
        symbol = (symbol + str(rng.randint(0, 99)))[:6]

    description = None
    if rng.random() < float(description_probability):
        description = _pick(_DESCRIPTIONS, rng)

    return {"name": name, "symbol": symbol, "description": description}
