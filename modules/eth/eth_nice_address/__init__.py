"""
ETH Nice Address Generator Module

Генерация "красивых" Ethereum адресов с настраиваемыми паттернами.

Доступные реализации:
- Python: Медленная, но без зависимостей (python/eth_nice_address.py)
- Rust: Быстрая (10-100x), требует Cargo (rust/)

Использование:
    from modules.eth.eth_nice_address.python.eth_nice_address import eth_generate_nice_wallets
    from modules.eth.eth_nice_address.eth_nice_address_rust_wrapper import run_rust_generator
"""

__version__ = "1.0.0"
__all__ = ["eth_generate_nice_wallets", "run_rust_generator"]
