# Закрытые / отработанные проекты

Здесь хранится журнал проектов и модулей, которые когда-то были интегрированы
в ETHmachine, а потом полностью удалены из скрипта (проект завершён, дроп
закончился, API недоступен и т.п.).

Запись добавляется при выпиле, чтобы можно было быстро вспомнить:
* что когда-то умел скрипт;
* какие папки/файлы были вырезаны (если потребуется поднять историю в git);
* почему этого больше нет.

## Журнал

| Дата       | Проект              | Модули и файлы                                                                                                                                                              | Причина                |
| ---------- | ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| 2026-05-05 | Perle               | `modules/statistics/perle/` (database.py, menu.py, worker.py), `docs/MODULE_PERLE_CHECKER.md`                                                                               | Проект закрыт          |
| 2026-05-05 | Pharos Testnet      | `modules/pharos/`, `modules/pharos_claim/`, `config/modules/cfg_pharos_claim.py`, авто-директории `result/pharos_discord/`, `result/pharos_auto/`                            | Проект закрыт          |
| 2026-05-05 | Abstract Portal     | `modules/abs/` (abs_client.py, abs_logger.py, abs_proxy.py, database.py, excel_export.py, menu.py, worker.py), `config/modules/cfg_abs.py`                                  | Проект закрыт          |
| 2026-05-05 | Zora Claimer        | `modules/claim/zora_claimer/` (client.py, database.py, menu.py, worker.py), пустой пакет `modules/claim/`, `docs/MODULE_ZORA_CLAIMER.md`, главное меню `💰 Claimer` + `CLAIMER_SUBMENU` | Проект закрыт          |
| 2026-05-05 | Check Gas Price     | `modules/get_gas_price.py`, `docs/MODULE_GET_GAS_PRICE.md`, пункт `⛽ Check Gas Price` в Tools                                                                                | Утилита больше не нужна |
| 2026-05-05 | Last Transactions   | `modules/eth/eth_last_tx.py`, пункт `🗂️ Last Transactions` в Tools                                                                                                          | Утилита больше не нужна |

## Поставленные на паузу

Проекты, которые ещё в коде, но временно не работают — помечены красным
бейджем `ПАУЗА` в меню (`config/menu_config.py`, поле `MenuItem.badge`):

| Проект        | Где в меню               | Что делает                          |
| ------------- | ------------------------ | ----------------------------------- |
| xStocks DeFi  | `🎮 PROJECTS → xStocks`  | Register, GM, Referrals, Points    |
