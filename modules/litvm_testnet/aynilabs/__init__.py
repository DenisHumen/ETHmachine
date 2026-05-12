"""Aynilabs — wrap zkLTC → WzkLTC on LiteForge (https://www.aynilabs.xyz/).

Сайт с низким функционалом — единственная on-chain активность это
«Get WzkLTC», т.е. вызов `WzkLTC.deposit()` payable с native value.
Подробности — в `worker.py`.
"""
from modules.litvm_testnet.aynilabs.menu import run_litvm_aynilabs

__all__ = ["run_litvm_aynilabs"]
