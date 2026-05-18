"""bech32 ↔ EVM address conversion for Kava chain.

Kava (Cosmos-SDK) использует bech32 (BIP-173) с HRP=`kava` для представления
тех же 20-байтовых аккаунтов, что и EVM 0x-адреса. Один private key
контролирует обе репрезентации, поэтому конвертер ниже — это просто перекодирование
20-байтового payload между bech32 и hex.

Реализация — каноническая референсная BIP-173 (Pieter Wuille), inline,
без внешних зависимостей.
"""
from __future__ import annotations

from typing import Optional, Tuple, List

# BIP-173 alphabet
_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

KAVA_HRP = "kava"


def _bech32_polymod(values: List[int]) -> int:
    GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1ffffff) << 5) ^ v
        for i in range(5):
            if (b >> i) & 1:
                chk ^= GEN[i]
    return chk


def _bech32_hrp_expand(hrp: str) -> List[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _bech32_verify_checksum(hrp: str, data: List[int]) -> bool:
    return _bech32_polymod(_bech32_hrp_expand(hrp) + data) == 1


def _bech32_create_checksum(hrp: str, data: List[int]) -> List[int]:
    values = _bech32_hrp_expand(hrp) + data
    polymod = _bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]


def bech32_decode(addr: str) -> Tuple[Optional[str], Optional[List[int]]]:
    if any(ord(c) < 33 or ord(c) > 126 for c in addr):
        return (None, None)
    if addr.lower() != addr and addr.upper() != addr:
        return (None, None)
    addr = addr.lower()
    pos = addr.rfind("1")
    if pos < 1 or pos + 7 > len(addr) or len(addr) > 90:
        return (None, None)
    hrp = addr[:pos]
    if not all(33 <= ord(c) <= 126 for c in hrp):
        return (None, None)
    data: List[int] = []
    for c in addr[pos + 1:]:
        if c not in _CHARSET:
            return (None, None)
        data.append(_CHARSET.index(c))
    if not _bech32_verify_checksum(hrp, data):
        return (None, None)
    return (hrp, data[:-6])


def bech32_encode(hrp: str, data: List[int]) -> str:
    combined = data + _bech32_create_checksum(hrp, data)
    return hrp + "1" + "".join(_CHARSET[d] for d in combined)


def _convertbits(data, frombits: int, tobits: int, pad: bool = True) -> Optional[List[int]]:
    acc = 0
    bits = 0
    ret: List[int] = []
    maxv = (1 << tobits) - 1
    max_acc = (1 << (frombits + tobits - 1)) - 1
    for v in data:
        if v < 0 or (v >> frombits):
            return None
        acc = ((acc << frombits) | v) & max_acc
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return None
    return ret


def kava_bech32_to_evm(addr: str) -> str:
    """Преобразовать `kava1...` → checksummed `0x...` 20-байтовый EVM-адрес.

    Raises ValueError при невалидном адресе.
    """
    s = (addr or "").strip()
    if not s:
        raise ValueError("empty kava address")
    hrp, data = bech32_decode(s)
    if hrp is None or data is None:
        raise ValueError(f"invalid bech32: {addr!r}")
    if hrp != KAVA_HRP:
        raise ValueError(f"expected HRP 'kava', got {hrp!r}")
    decoded = _convertbits(data, 5, 8, False)
    if decoded is None or len(decoded) != 20:
        raise ValueError(f"bech32 payload not 20 bytes: {addr!r} (got {len(decoded) if decoded else 0})")
    hex_addr = "0x" + bytes(decoded).hex()
    # checksum via web3 (Account) — импорт локальный, чтобы модуль работал
    # и в окружении без web3 (тестов).
    try:
        from web3 import Web3
        return Web3.to_checksum_address(hex_addr)
    except Exception:
        return hex_addr


def evm_to_kava_bech32(addr: str) -> str:
    """0x... → kava1... (обратное преобразование, для отладки/тестов)."""
    s = (addr or "").strip()
    if s.startswith("0x") or s.startswith("0X"):
        s = s[2:]
    if len(s) != 40:
        raise ValueError(f"hex address must be 20 bytes: {addr!r}")
    raw = bytes.fromhex(s)
    five = _convertbits(list(raw), 8, 5, True)
    if five is None:
        raise ValueError("convertbits failed")
    return bech32_encode(KAVA_HRP, five)


__all__ = [
    "KAVA_HRP",
    "kava_bech32_to_evm",
    "evm_to_kava_bech32",
    "bech32_decode",
    "bech32_encode",
]
