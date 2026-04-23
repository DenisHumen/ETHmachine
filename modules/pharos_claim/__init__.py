"""Pharos Claim Checker — проверка результатов на claim.pharos.xyz.

Модуль использует:
  - modules.proxy_manager  — прокси (1:1 к кошельку, ротация при ошибках)
  - modules.simple_logger  — единый loguru-логгер проекта
  - modules.data_manager   — загрузка приватных ключей/прокси из data.csv
  - SQLite (db/pharos_claim.db) — хранение задач и результатов
  - openpyxl               — экспорт результатов в XLSX

Запросы идут через curl_cffi с TLS-импресонацией реального Chrome,
реальный браузер не запускается (анти-детект, но без автоматизации UI).
"""
from modules.pharos_claim.runner import run_checker
from modules.pharos_claim.excel_export import export_latest_run

__all__ = ["run_checker", "export_latest_run"]
