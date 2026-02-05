import sqlite3
import time
import random
import ccxt
import os
from datetime import datetime, timedelta
from loguru import logger
from typing import List, Dict, Optional
import sys

# Добавляем путь к корневой директории проекта
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
sys.path.append(project_root)

from config.modules.cfg_spot_trade import *

# Импорт селектора аккаунтов
from modules.cex.exchange_selector import select_okx_account


def colorize_price_change(price_change_percent: float) -> str:
    """
    Раскрашивает процент изменения цены:
    - Красный: если падение (отрицательный процент)
    - Желтый: если близко к нулю (-0.1% до +0.1%)
    - Зеленый: если рост (положительный процент)
    """
    if price_change_percent < -0.1:
        return f"<red>{price_change_percent:.2f}%</red>"
    elif -0.1 <= price_change_percent <= 0.1:
        return f"<yellow>{price_change_percent:.2f}%</yellow>"
    else:
        return f"<green>+{price_change_percent:.2f}%</green>"


def format_position_message(token: str, buy_price: float, current_price: float, 
                          price_change_percent: float, action_message: str, 
                          emoji: str = "📊") -> str:
    """
    Форматирует сообщение о позиции с цветной раскраской
    """
    colored_change = colorize_price_change(price_change_percent)
    
    if price_change_percent < 0:
        change_word = "падение"
    elif price_change_percent > 0:
        change_word = "рост"
    else:
        change_word = "изменение"
    
    return (f"      │    {emoji} {token}: цена покупки = {buy_price:.2f}, "
            f"текущая = {current_price}, {change_word} = {colored_change} → {action_message}")


def format_buy_message(token: str, price_change: float, threshold: float, 
                      message_type: str = "ПЕРВАЯ ПОКУПКА") -> str:
    """
    Форматирует сообщение о покупке с цветной раскраской
    """
    colored_change = colorize_price_change(price_change)
    colored_threshold = f"<red>-{threshold}%</red>"
    
    return (f"      │    📉 {token}: {message_type} | изменение за 24ч = {colored_change}, "
            f"порог = {colored_threshold} → 🛒 ПОКУПАЕМ!")


def format_averaging_message(token: str, last_price: float, current_price: float,
                           price_drop: float, threshold: float) -> tuple[str, str]:
    """Форматирует сообщение об усреднении с цветной раскраской"""
    msg1 = (f"      │    📉 {token}: УСРЕДНЕНИЕ | последняя покупка = <yellow>{last_price:.2f}</yellow>, "
            f"текущая = <yellow>{current_price:.2f}</yellow>")
    colored_drop = colorize_price_change(-price_drop)  # Делаем падение отрицательным для правильного цвета
    msg2 = (f"      │    📉 {token}: падение от последней покупки = {colored_drop}, "
            f"порог = <red>{threshold}%</red> → 🛒 УСРЕДНЯЕМ!")
    return msg1, msg2


def _get_cex_settings():
    """Получить настройки OKX с обработкой ошибок"""
    try:
        from config.cex_settings import OKX_ACCOUNTS, OKX_EU_TYPE
        return OKX_ACCOUNTS, OKX_EU_TYPE
    except ImportError:
        logger.error("Файл config/cex_settings.py не найден. Запустите main.py для создания.")
        return [], 0
    except Exception as e:
        logger.error(f"Ошибка в настройках OKX: {e}")
        return [], 0


class OKXSpotTrader:
    def __init__(self, account=None):
        # Получаем настройки безопасно
        OKX_ACCOUNTS, OKX_EU_TYPE = _get_cex_settings()
        self.OKX_ACCOUNTS = OKX_ACCOUNTS
        self.OKX_EU_TYPE = OKX_EU_TYPE
        
        # Если аккаунт не передан, выбираем его
        if not account:
            exchange_name, account = select_okx_account()
            if not account:
                raise ValueError("❌ Не выбран аккаунт OKX")
        
        logger.info(f"🏢 Используется аккаунт: {account['name']}")
        
        # Инициализация биржи с выбранным аккаунтом
        self.exchange = ccxt.okx({
            'apiKey': account['api_key'],
            'secret': account['api_secret'],
            'password': account['passphrase'],
            'sandbox': False,
            'enableRateLimit': True,
        })
        
        # Создаем директорию для БД если её нет - изменено на db/
        self.db_dir = os.path.join(project_root, "db")
        if not os.path.exists(self.db_dir):
            os.makedirs(self.db_dir)
            
        self.db_name = os.path.join(self.db_dir, f"okx_{BASE_NAME}.db")
        self.init_database()
        logger.info(f"Инициализирован OKX Spot Trader с базой данных: {self.db_name}")
        
        # Словарь для отслеживания отправленных уведомлений о недостаточной ликвидности
        # Ключ: токен, Значение: время последнего уведомления
        self.liquidity_warnings_sent = {}

    def init_database(self):
        """Инициализация базы данных"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        # Таблица транзакций с полной информацией для торговых решений
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL,
                buy_date TIMESTAMP NOT NULL,
                buy_amount REAL NOT NULL,
                buy_price REAL NOT NULL,
                buy_total_usdt REAL NOT NULL,
                target_sell_price REAL NOT NULL,
                sell_date TIMESTAMP,
                sell_amount REAL,
                sell_price REAL,
                sell_total_usdt REAL,
                status TEXT NOT NULL DEFAULT 'open',
                profit_usdt REAL,
                profit_percent REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица цен для анализа
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL,
                price REAL NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("База данных инициализирована в папке db/")
        
        # Проверяем содержимое БД при запуске
        self.log_database_status()

    def log_database_status(self):
        """Логирование состояния базы данных"""
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            # Проверяем количество транзакций
            cursor.execute("SELECT COUNT(*) FROM transactions")
            total_transactions = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM transactions WHERE status = 'open'")
            open_transactions = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM transactions WHERE status = 'success'")
            completed_transactions = cursor.fetchone()[0]
            
            logger.info(f"📊 Состояние БД (db/{os.path.basename(self.db_name)}): всего = {total_transactions}, открытых = {open_transactions}, завершенных = {completed_transactions}")
            
            # ДЕТАЛЬНЫЙ ВЫВОД ВСЕХ ТРАНЗАКЦИЙ
            if total_transactions > 0:
                cursor.execute('''
                    SELECT id, token, buy_date, buy_amount, buy_price, buy_total_usdt, target_sell_price, status,
                           sell_date, sell_price, profit_usdt, profit_percent
                    FROM transactions 
                    ORDER BY buy_date DESC
                ''')
                all_transactions = cursor.fetchall()
                logger.info("📋 ВСЕ ТРАНЗАКЦИИ В БД:")
                
                for i, (tid, token, buy_date, buy_amount, buy_price, buy_total, target_price, 
                       status, sell_date, sell_price, profit_usdt, profit_pct) in enumerate(all_transactions, 1):
                    
                    logger.info(f"   {i}. ID={tid} | {token} | {status.upper()}")
                    logger.info(f"      📅 Покупка: {buy_date} | {buy_amount:.8f} {token} по {buy_price:.2f} USDT")
                    logger.info(f"      💰 Потрачено: {buy_total:.6f} USDT | Цель: {target_price:.2f} USDT")
                    
                    if status == 'success' and sell_date:
                        logger.info(f"      📤 Продажа: {sell_date} | по {sell_price:.2f} USDT")
                        logger.info(f"      💎 Прибыль: {profit_usdt:.6f} USDT ({profit_pct:+.2f}%)")
                    logger.info("")
            
            conn.close()
        except Exception as e:
            logger.error(f"Ошибка проверки БД: {e}")

    def save_transaction_to_db(self, token: str, buy_price: float, buy_amount: float, total_usdt: float) -> int:
        """Сохранить новую транзакцию покупки в БД"""
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            buy_date = datetime.now()
            # Рассчитываем целевую цену продажи на основе настроек
            target_sell_price = buy_price * (1 + PROCENT_TO_BUY_SELL[1] / 100)
            
            cursor.execute('''
                INSERT INTO transactions (
                    token, buy_date, buy_amount, buy_price, buy_total_usdt, target_sell_price, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (token, buy_date, buy_amount, buy_price, total_usdt, target_sell_price, 'open'))
            
            transaction_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            logger.success(f"💾 Транзакция сохранена в db/{os.path.basename(self.db_name)}:")
            logger.success(f"   📦 ID={transaction_id} | {token} | Дата: {buy_date}")
            logger.success(f"   🛒 Куплено: {buy_amount:.8f} {token} по {buy_price:.2f} USDT")
            logger.success(f"   💰 Потрачено: {total_usdt:.6f} USDT")
            logger.success(f"   🎯 Цель продажи: {target_sell_price:.2f} USDT (+{PROCENT_TO_BUY_SELL[1]}%)")
            return transaction_id
            
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения транзакции в БД: {e}")
            return 0

    def update_transaction_sell(self, transaction_id: int, sell_price: float, sell_amount: float, sell_total_usdt: float) -> bool:
        """Обновить транзакцию при продаже"""
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            sell_date = datetime.now()
            
            # Получаем данные покупки для расчета прибыли
            cursor.execute('''
                SELECT buy_total_usdt FROM transactions WHERE id = ?
            ''', (transaction_id,))
            
            result = cursor.fetchone()
            if not result:
                logger.error(f"❌ Транзакция с ID={transaction_id} не найдена")
                conn.close()
                return False
            
            buy_total_usdt = result[0]
            profit_usdt = sell_total_usdt - buy_total_usdt
            profit_percent = (profit_usdt / buy_total_usdt) * 100 if buy_total_usdt > 0 else 0
            
            # Обновляем транзакцию
            cursor.execute('''
                UPDATE transactions 
                SET sell_date = ?, sell_amount = ?, sell_price = ?, sell_total_usdt = ?,
                    status = ?, profit_usdt = ?, profit_percent = ?
                WHERE id = ?
            ''', (sell_date, sell_amount, sell_price, sell_total_usdt, 
                 'success', profit_usdt, profit_percent, transaction_id))
            
            if cursor.rowcount > 0:
                conn.commit()
                logger.success(f"💾 Транзакция обновлена: ID={transaction_id}")
                logger.success(f"   📤 Продано: {sell_amount:.8f} по {sell_price:.2f} USDT")
                logger.success(f"   💰 Получено: {sell_total_usdt:.6f} USDT")
                logger.success(f"   💎 Прибыль: {profit_usdt:.6f} USDT ({profit_percent:+.2f}%)")
                conn.close()
                return True
            else:
                logger.error(f"❌ Не удалось обновить транзакцию ID={transaction_id}")
                conn.close()
                return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка обновления транзакции: {e}")
            return False

    def get_balance(self, token: str) -> float:
        """Получить баланс токена"""
        try:
            balance = self.exchange.fetch_balance()
            return balance['free'].get(token, 0)
        except Exception as e:
            logger.error(f"Ошибка получения баланса {token}: {e}")
            return 0

    def get_current_price(self, token: str) -> Optional[float]:
        """Получить текущую цену токена"""
        try:
            ticker = self.exchange.fetch_ticker(f"{token}/{TOKEN_TO_BUY_FOR}")
            price = ticker['last']
            logger.debug(f"Текущая цена {token}: {price}")
            return price
        except Exception as e:
            logger.error(f"Ошибка получения цены {token}: {e}")
            return None

    def save_price_to_db(self, token: str, price: float):
        """Сохранить цену в базу данных"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO price_history (token, price) VALUES (?, ?)",
            (token, price)
        )
        conn.commit()
        conn.close()

    def get_24h_price_change_from_api(self, token: str) -> Optional[float]:
        """Получить изменение цены за 24 часа через API биржи"""
        try:
            ticker = self.exchange.fetch_ticker(f"{token}/{TOKEN_TO_BUY_FOR}")
            if 'percentage' in ticker and ticker['percentage'] is not None:
                return ticker['percentage']
            elif 'change' in ticker and 'last' in ticker and ticker['change'] is not None and ticker['last'] is not None:
                return (ticker['change'] / ticker['last']) * 100
            return None
        except Exception as e:
            logger.error(f"Ошибка получения изменения цены {token} через API: {e}")
            return None

    def get_24h_price_change(self, token: str) -> Optional[float]:
        """Получить изменение цены за 24 часа в процентах"""
        # Сначала пробуем получить из API биржи
        api_change = self.get_24h_price_change_from_api(token)
        if api_change is not None:
            logger.debug(f"{token}: изменение за 24ч (API) = {api_change:.2f}%")
            return api_change
        
        # Если API не дает данные, пробуем из локальной БД
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        # Получаем цену 24 часа назад
        cursor.execute('''
            SELECT price FROM price_history 
            WHERE token = ? AND timestamp <= datetime('now', '-1 day')
            ORDER BY timestamp DESC LIMIT 1
        ''', (token,))
        
        old_price_row = cursor.fetchone()
        
        # Получаем текущую цену
        cursor.execute('''
            SELECT price FROM price_history 
            WHERE token = ? 
            ORDER BY timestamp DESC LIMIT 1
        ''', (token,))
        
        current_price_row = cursor.fetchone()
        conn.close()
        
        if not old_price_row or not current_price_row:
            logger.debug(f"{token}: недостаточно данных в БД для расчета изменения за 24ч")
            return None
            
        old_price = old_price_row[0]
        current_price = current_price_row[0]
        
        change_percent = ((current_price - old_price) / old_price) * 100
        logger.debug(f"{token}: изменение за 24ч (БД) = {change_percent:.2f}%")
        return change_percent

    def calculate_buy_amount(self) -> float:
        """Рассчитать сумму для покупки"""
        base_balance = self.get_balance(TOKEN_TO_BUY_FOR)
        
        if SUM_OR_PROCENT_TO_BUY['type_buy'] == 'sum':
            min_sum, max_sum = SUM_OR_PROCENT_TO_BUY['sum']
            amount = random.uniform(min_sum, max_sum)
            logger.info(f"💰 Расчет покупки по СУММЕ: {amount:.6f} {TOKEN_TO_BUY_FOR} (диапазон: {min_sum}-{max_sum})")
            return amount
        else:  # percent
            min_percent, max_percent = SUM_OR_PROCENT_TO_BUY['percent']
            percent = random.uniform(min_percent, max_percent)
            amount = (base_balance * percent) / 100
            logger.info(f"💰 Расчет покупки по ПРОЦЕНТУ: {percent:.2f}% от {base_balance:.6f} = {amount:.6f} {TOKEN_TO_BUY_FOR}")
            logger.info(f"💡 Для увеличения суммы покупки уменьшите процент или переключитесь на 'sum' в конфигурации")
            return amount

    def get_min_order_amounts(self):
        """Получить информацию о минимальных суммах заказов"""
        try:
            markets = self.exchange.load_markets()
            min_amounts = {}
            for token in TOKEN_TO_BUY:
                symbol = f"{token}/{TOKEN_TO_BUY_FOR}"
                if symbol in markets:
                    market = markets[symbol]
                    min_cost = market.get('limits', {}).get('cost', {}).get('min', None)
                    if min_cost:
                        min_amounts[token] = min_cost
                        logger.debug(f"Минимальная сумма заказа для {token}: {min_cost} {TOKEN_TO_BUY_FOR}")
            return min_amounts
        except Exception as e:
            logger.error(f"Ошибка получения минимальных сумм заказов: {e}")
            return {}

    def check_purchase_success(self, token: str, expected_spent: float, balance_before: dict, max_attempts: int = 5) -> tuple:
        """
        Фоновая проверка успешности покупки по изменению балансов
        Возвращает (success: bool, token_received: float, actual_spent: float)
        """
        for attempt in range(max_attempts):
            # Задержка между попытками
            time.sleep(2 if attempt == 0 else 3)
            
            # Получаем текущие балансы
            current_token_balance = self.get_balance(token)
            current_usdt_balance = self.get_balance(TOKEN_TO_BUY_FOR)
            
            # Рассчитываем изменения
            token_received = current_token_balance - balance_before[token]
            usdt_spent = balance_before[TOKEN_TO_BUY_FOR] - current_usdt_balance
            
            # Проверяем успешность покупки
            if token_received > 0 and usdt_spent > 0:
                # Проверяем, что потраченная сумма близка к ожидаемой (с допуском ±10%)
                spent_tolerance = expected_spent * 0.1
                if abs(usdt_spent - expected_spent) <= spent_tolerance:
                    return True, token_received, usdt_spent
            
            # Если последняя попытка - возвращаем результат
            if attempt == max_attempts - 1:
                return False, token_received, usdt_spent
        
        return False, 0, 0

    def check_sale_success(self, token: str, expected_received: float, balance_before: dict, max_attempts: int = 5) -> tuple:
        """
        Фоновая проверка успешности продажи по изменению балансов
        Возвращает (success: bool, token_sold: float, actual_received: float)
        """
        for attempt in range(max_attempts):
            # Задержка между попытками
            time.sleep(2 if attempt == 0 else 3)
            
            # Получаем текущие балансы
            current_token_balance = self.get_balance(token)
            current_usdt_balance = self.get_balance(TOKEN_TO_BUY_FOR)
            
            # Рассчитываем изменения
            token_sold = balance_before[token] - current_token_balance
            usdt_received = current_usdt_balance - balance_before[TOKEN_TO_BUY_FOR]
            
            # Проверяем успешность продажи
            if token_sold > 0 and usdt_received > 0:
                # Проверяем, что полученная сумма близка к ожидаемой (с допуском ±10%)
                received_tolerance = expected_received * 0.1
                if abs(usdt_received - expected_received) <= received_tolerance:
                    return True, token_sold, usdt_received
            
            # Если последняя попытка - возвращаем результат
            if attempt == max_attempts - 1:
                return False, token_sold, usdt_received
        
        return False, 0, 0

    def buy_token(self, token: str) -> bool:
        """Купить токен"""
        buy_amount_usdt = 0  # Инициализируем переменную
        
        try:
            current_price = self.get_current_price(token)
            if not current_price:
                logger.error(f"❌ Не удалось получить цену для {token}")
                return False
                
            buy_amount_usdt = self.calculate_buy_amount()
            base_balance = self.get_balance(TOKEN_TO_BUY_FOR)
            
            # Получаем информацию о минимальной сумме заказа
            min_amounts = self.get_min_order_amounts()
            min_required = min_amounts.get(token, "неизвестно")
            
            logger.info(f"📊 Анализ покупки {token}:")
            logger.info(f"   💱 Текущая цена: {current_price:,.2f} {TOKEN_TO_BUY_FOR}")
            logger.info(f"   💰 Ваш баланс: {base_balance:.6f} {TOKEN_TO_BUY_FOR}")
            logger.info(f"   🛒 Планируемая покупка: {buy_amount_usdt:.6f} {TOKEN_TO_BUY_FOR}")
            logger.info(f"   ⚖️ Минимум биржи: {min_required} {TOKEN_TO_BUY_FOR}")
            
            # Проверяем достаточность баланса
            if base_balance < buy_amount_usdt:
                logger.warning(f"❌ Недостаточно баланса для покупки {token}: нужно {buy_amount_usdt:.6f}, доступно {base_balance:.6f}")
                
                # Отправляем уведомление только если оно еще не было отправлено для этого токена
                # или прошло более 1 часа с последнего уведомления
                current_time = time.time()
                last_warning_time = self.liquidity_warnings_sent.get(token, 0)
                
                # Проверяем: если прошло больше 3600 секунд (1 час) или уведомление не отправлялось
                if current_time - last_warning_time > 3600:
                    self.send_notification(
                        "warning",
                        "Недостаточно ликвидности",
                        f"Нужно {buy_amount_usdt} {TOKEN_TO_BUY_FOR}, доступно {base_balance}",
                        token=token
                    )
                    # Запоминаем время отправки уведомления
                    self.liquidity_warnings_sent[token] = current_time
                    logger.info(f"📨 Уведомление о недостаточной ликвидности отправлено для {token}")
                else:
                    logger.debug(f"⏭️ Уведомление о недостаточной ликвидности для {token} уже отправлено недавно")
                
                return False
            
            # Рассчитываем количество токенов для покупки
            token_amount = buy_amount_usdt / current_price
            
            logger.info(f"🎯 Выполняем покупку {token}: {token_amount:.8f} {token} за {buy_amount_usdt:.6f} {TOKEN_TO_BUY_FOR}")
            
            # Сохраняем балансы до покупки
            balances_before = {
                token: self.get_balance(token),
                TOKEN_TO_BUY_FOR: self.get_balance(TOKEN_TO_BUY_FOR)
            }
            
            logger.info(f"📊 Балансы ДО покупки: {token}={balances_before[token]:.8f}, {TOKEN_TO_BUY_FOR}={balances_before[TOKEN_TO_BUY_FOR]:.6f}")
            
            # Выполняем покупку
            order = self.exchange.create_market_buy_order(f"{token}/{TOKEN_TO_BUY_FOR}", token_amount)
            
            logger.info(f"📋 Ответ биржи: статус = {order.get('status', 'неизвестно')}, ID = {order.get('id', 'неизвестно')}")
            
            # Фоновая проверка результата покупки
            success, token_received, actual_spent = self.check_purchase_success(
                token, buy_amount_usdt, balances_before
            )
            
            if success:
                # Рассчитываем реальную цену покупки
                actual_price = actual_spent / token_received if token_received > 0 else current_price
                
                logger.info(f"💰 Реальные данные покупки: получено {token_received:.8f} {token}, потрачено {actual_spent:.6f} {TOKEN_TO_BUY_FOR}")
                logger.info(f"💱 Реальная цена покупки: {actual_price:.2f} {TOKEN_TO_BUY_FOR}")
                
                # ИСПРАВЛЕНО: Правильно сохраняем транзакцию в БД
                try:
                    conn = sqlite3.connect(self.db_name)
                    cursor = conn.cursor()
                    
                    buy_date = datetime.now()
                    target_sell_price = actual_price * (1 + PROCENT_TO_BUY_SELL[1] / 100)
                    
                    cursor.execute('''
                        INSERT INTO transactions (
                            token, buy_date, buy_amount, buy_price, buy_total_usdt, target_sell_price, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (token, buy_date, token_received, actual_price, actual_spent, target_sell_price, 'open'))
                    
                    transaction_id = cursor.lastrowid
                    conn.commit()
                    conn.close()
                    
                    logger.success(f"💾 ТРАНЗАКЦИЯ СОХРАНЕНА В БД:")
                    logger.success(f"   📦 ID транзакции: {transaction_id}")
                    logger.success(f"   🪙 Токен: {token}")
                    logger.success(f"   📅 Дата покупки: {buy_date}")
                    logger.success(f"   🔢 Количество: {token_received:.8f} {token}")
                    logger.success(f"   💱 Цена покупки: {actual_price:.2f} {TOKEN_TO_BUY_FOR}")
                    logger.success(f"   💰 Потрачено всего: {actual_spent:.6f} {TOKEN_TO_BUY_FOR}")
                    logger.success(f"   🎯 Цель продажи: {target_sell_price:.2f} {TOKEN_TO_BUY_FOR} (+{PROCENT_TO_BUY_SELL[1]}%)")
                    logger.success(f"   📊 Статус: open")
                    
                    # Проверяем что запись действительно сохранилась
                    cursor = sqlite3.connect(self.db_name).cursor()
                    cursor.execute("SELECT COUNT(*) FROM transactions WHERE id = ?", (transaction_id,))
                    if cursor.fetchone()[0] > 0:
                        logger.success(f"✅ Подтверждение: запись с ID={transaction_id} найдена в БД")
                    else:
                        logger.error(f"❌ КРИТИЧНО: запись с ID={transaction_id} НЕ найдена в БД!")
                    cursor.close()
                    
                    self.send_notification(
                        "success",
                        "Покупка выполнена",
                        f"Куплено {token_received:.8f} {token} по цене {actual_price:.2f} {TOKEN_TO_BUY_FOR}",
                        token=token,
                        amount=f"{token_received:.8f}",
                        price=f"{actual_price:.2f}",
                        spent=f"{actual_spent:.6f} {TOKEN_TO_BUY_FOR}",
                        transaction_id=transaction_id,
                        sell_target=f"{target_sell_price:.2f} {TOKEN_TO_BUY_FOR}"
                    )
                    
                    # Логируем состояние БД после сохранения
                    self.log_database_status()
                    return True
                    
                except Exception as db_error:
                    logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА сохранения в БД: {db_error}")
                    return False
            else:
                logger.warning(f"⚠️ Покупка {token} не подтверждена изменением балансов")
                return False
            
        except Exception as e:
            logger.error(f"❌ Исключение при покупке {token}: {e}")
            
            # Проверяем специфические ошибки
            if "51020" in str(e) or "minimum order amount" in str(e).lower():
                logger.warning(f"⚠️ Сумма покупки {token} слишком мала: {buy_amount_usdt:.6f} {TOKEN_TO_BUY_FOR}")
                logger.warning(f"🔧 Настройки покупки: тип = {SUM_OR_PROCENT_TO_BUY['type_buy']}")
                
                if SUM_OR_PROCENT_TO_BUY['type_buy'] == 'percent':
                    logger.warning(f"📊 Процент: {SUM_OR_PROCENT_TO_BUY['percent']}% от баланса")
                    logger.warning(f"💡 РЕШЕНИЕ: Увеличьте процент в конфигурации или переключитесь на 'sum'")
                else:
                    logger.warning(f"💰 Сумма: {SUM_OR_PROCENT_TO_BUY['sum']} {TOKEN_TO_BUY_FOR}")
                    logger.warning(f"💡 РЕШЕНИЕ: Увеличьте минимальную сумму в конфигурации")
                
                min_amounts = self.get_min_order_amounts()
                min_required = min_amounts.get(token)
                if min_required:
                    logger.warning(f"⚖️ Минимальная сумма для {token}: {min_required} {TOKEN_TO_BUY_FOR}")
                
                self.send_notification(
                    "warning",
                    "Сумма покупки слишком мала",
                    f"Попытка купить {token} на {buy_amount_usdt:.6f} {TOKEN_TO_BUY_FOR}, но это меньше минимума биржи. Увеличьте параметры в конфигурации.",
                    token=token,
                    attempted_amount=f"{buy_amount_usdt:.6f} {TOKEN_TO_BUY_FOR}",
                    error_code="51020",
                    config_type=SUM_OR_PROCENT_TO_BUY['type_buy'],
                    config_percent=f"{SUM_OR_PROCENT_TO_BUY['percent']}"
                )
            else:
                logger.error(f"❌ Ошибка покупки {token}: {e}")
                self.send_notification(
                    "error",
                    "Ошибка покупки",
                    f"Ошибка при покупке {token}: {str(e)}",
                    token=token,
                    error_details=str(e)
                )
        return False

    def sell_token(self, transaction_id: int, token: str, buy_price: float, token_amount: float) -> bool:
        """Продать токен"""
        try:
            current_price = self.get_current_price(token)
            if not current_price:
                logger.error(f"❌ Не удалось получить цену для продажи {token}")
                return False
            
            logger.info(f"💰 Анализ продажи {token}:")
            logger.info(f"   📦 Количество к продаже: {token_amount:.8f} {token}")
            logger.info(f"   💱 Цена покупки: {buy_price:.2f} {TOKEN_TO_BUY_FOR}")
            logger.info(f"   💱 Текущая цена: {current_price:.2f} {TOKEN_TO_BUY_FOR}")
            
            # Получаем актуальный баланс токена
            token_balance = self.get_balance(token)
            sell_amount = min(token_amount, token_balance)
            
            logger.info(f"   🏦 Баланс токена: {token_balance:.8f} {token}")
            logger.info(f"   🎯 Продаем: {sell_amount:.8f} {token}")
            
            if sell_amount <= 0:
                logger.warning(f"❌ Недостаточно токенов для продажи {token}")
                return False
            
            # Сохраняем балансы до продажи
            balances_before = {
                token: self.get_balance(token),
                TOKEN_TO_BUY_FOR: self.get_balance(TOKEN_TO_BUY_FOR)
            }
            
            logger.info(f"📊 Балансы ДО продажи: {token}={balances_before[token]:.8f}, {TOKEN_TO_BUY_FOR}={balances_before[TOKEN_TO_BUY_FOR]:.6f}")
            
            # Рассчитываем ожидаемую сумму к получению
            expected_received = sell_amount * current_price
            
            # Выполняем продажу
            order = self.exchange.create_market_sell_order(f"{token}/{TOKEN_TO_BUY_FOR}", sell_amount)
            
            logger.info(f"📋 Ответ биржи (продажа): статус = {order.get('status', 'неизвестно')}, ID = {order.get('id', 'неизвестно')}")
            
            # Фоновая проверка результата продажи
            success, token_sold, actual_received = self.check_sale_success(
                token, expected_received, balances_before
            )
            
            if success:
                # Рассчитываем реальную цену продажи
                actual_sell_price = actual_received / token_sold if token_sold > 0 else current_price
                
                logger.info(f"💰 Реальные данные продажи: продано {token_sold:.8f} {token}, получено {actual_received:.6f} {TOKEN_TO_BUY_FOR}")
                logger.info(f"💱 Реальная цена продажи: {actual_sell_price:.2f} {TOKEN_TO_BUY_FOR}")
                
                # Обновляем транзакцию в БД
                if self.update_transaction_sell(transaction_id, actual_sell_price, token_sold, actual_received):
                    
                    # Получаем полную информацию о сделке для уведомления
                    conn = sqlite3.connect(self.db_name)
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT profit_usdt, profit_percent FROM transactions WHERE id = ?
                    ''', (transaction_id,))
                    result = cursor.fetchone()
                    conn.close()
                    
                    if result:
                        profit_usdt, profit_percent = result
                        
                        logger.success(f"✅ Продажа завершена:")
                        logger.success(f"   📤 Продано: {token_sold:.8f} {token}")
                        logger.success(f"   💰 По цене: {actual_sell_price:.2f} {TOKEN_TO_BUY_FOR}")
                        logger.success(f"   💰 Получено: {actual_received:.6f} {TOKEN_TO_BUY_FOR}")
                        logger.success(f"   💎 Прибыль: {profit_usdt:.6f} {TOKEN_TO_BUY_FOR} ({profit_percent:+.2f}%)")
                        
                        self.send_notification(
                            "success",
                            "Продажа выполнена",
                            f"Продано {token_sold:.8f} {token} по цене {actual_sell_price:.2f} {TOKEN_TO_BUY_FOR}",
                            token=token,
                            amount=f"{token_sold:.8f}",
                            price=f"{actual_sell_price:.2f}",
                            received=f"{actual_received:.6f} {TOKEN_TO_BUY_FOR}",
                            profit=f"{profit_usdt:.6f} {TOKEN_TO_BUY_FOR}",
                            profit_percent=f"{profit_percent:+.2f}",
                            transaction_id=transaction_id
                        )
                    return True
                else:
                    logger.error(f"❌ Не удалось обновить транзакцию продажи в БД для {token}")
                    return False
            else:
                logger.warning(f"⚠️ Продажа {token} не подтверждена изменением балансов")
                logger.warning(f"   📊 Изменение токена: -{token_sold:.8f} {token}")
                logger.warning(f"   📊 Изменение USDT: +{actual_received:.6f} {TOKEN_TO_BUY_FOR}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка при продаже токена {token}: {e}")
            self.send_notification(
                "error",
                "Ошибка продажи",
                f"Ошибка при продаже {token}: {str(e)}",
                token=token,
                transaction_id=transaction_id,
                error_details=str(e)
            )
            return False

    def send_notification(self, notif_type: str, title: str, message: str, **kwargs):
        """Отправить уведомление"""
        if not SPOT_TRADE_ENABLE_NOTIFICATIONS:
            return
            
        try:
            # Динамически импортируем notifications и временно меняем настройки
            import modules.notifications as notifications
            
            # Сохраняем оригинальные значения
            original_enable = notifications.ENABLE_NOTIFICATIONS
            original_token = notifications.TELEGRAM_BOT_TOKEN
            original_chat_id = notifications.TELEGRAM_CHAT_ID
            
            # Временно подменяем настройки
            notifications.ENABLE_NOTIFICATIONS = SPOT_TRADE_ENABLE_NOTIFICATIONS
            notifications.TELEGRAM_BOT_TOKEN = SPOT_TRADE_TELEGRAM_BOT_TOKEN
            notifications.TELEGRAM_CHAT_ID = SPOT_TRADE_TELEGRAM_CHAT_ID
            
            try:
                # Отправляем уведомление
                notifications.send_telegram_notification(
                    notif_type=notif_type,
                    title=title,
                    message=message,
                    main_title="OKX Spot Trading",
                    **kwargs
                )
            finally:
                # Восстанавливаем оригинальные настройки
                notifications.ENABLE_NOTIFICATIONS = original_enable
                notifications.TELEGRAM_BOT_TOKEN = original_token
                notifications.TELEGRAM_CHAT_ID = original_chat_id
                
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления: {e}")

    def process_trading_cycle(self):
        """Выполнить один цикл торговли"""
        try:
            logger.info("╔════════════════════════════════════════════════════════════════════════════════╗")
            logger.info("║                          🚀 НАЧАЛО ЦИКЛА ТОРГОВЛИ                              ║")
            logger.info("╚════════════════════════════════════════════════════════════════════════════════╝")
            
            # Обновляем цены для всех токенов
            logger.info("      ┌─ 📊 ПОЛУЧЕНИЕ ТЕКУЩИХ ЦЕН:")
            for token in TOKEN_TO_BUY:
                current_price = self.get_current_price(token)
                if current_price:
                    self.save_price_to_db(token, current_price)
                    logger.info(f"      │  💱 {token}: {current_price:,.2f} {TOKEN_TO_BUY_FOR}")
            
            # Проверяем баланс базовой валюты
            base_balance = self.get_balance(TOKEN_TO_BUY_FOR)
            logger.info(f"      └─ 💰 Баланс {TOKEN_TO_BUY_FOR}: {base_balance:,.6f}")
            logger.info("")
            
            # Показываем статус позиций
            logger.info("      ┌─ 🎯 СТАТУС ПОЗИЦИЙ:")
            for token in TOKEN_TO_BUY:
                has_position = self.has_open_position(token)
                if has_position:
                    last_buy_price = self.get_last_buy_price(token)
                    current_price = self.get_current_price(token)
                    if last_buy_price and current_price:
                        price_diff = ((current_price - last_buy_price) / last_buy_price) * 100
                        logger.info(f"      │  📦 {token}: ЕСТЬ ПОЗИЦИЯ | последняя покупка = {last_buy_price:.2f}, сейчас = {current_price:.2f} ({price_diff:+.2f}%)")
                else:
                    logger.info(f"      │  ⭕ {token}: НЕТ ПОЗИЦИИ")
            logger.info("      └─")
            logger.info("")
            
            # Проверяем открытые позиции на продажу
            open_transactions = self.get_open_transactions()
            logger.info("      ┌─ 📋 АНАЛИЗ ОТКРЫТЫХ ПОЗИЦИЙ НА ПРОДАЖУ:")
            logger.info(f"      │  📦 Открытых позиций: {len(open_transactions)}")
            
            if open_transactions:
                for transaction in open_transactions:
                    #logger.info(f"      │  🔍 Проверяем позицию {transaction['token']}: куплено по {transaction['buy_price']:.2f}")
                    if self.should_sell(transaction['token'], transaction['buy_price']):
                        logger.info(f"      │  🎯 Продаем {transaction['token']}")
                        if self.sell_token(
                            transaction['id'],
                            transaction['token'],
                            transaction['buy_price'],
                            transaction['buy_amount']
                        ):
                            logger.success(f"      │  ✅ Успешно продан {transaction['token']}")
                        else:
                            logger.error(f"      │  ❌ Ошибка продажи {transaction['token']}")
            else:
                logger.info("      │  ⭕ Нет открытых позиций")
            logger.info("      └─")
            logger.info("")
            
            # Проверяем возможности для покупки (с учетом усреднения)
            logger.info("      ┌─ 🛒 АНАЛИЗ ВОЗМОЖНОСТЕЙ ПОКУПКИ (С УСРЕДНЕНИЕМ):")
            has_purchases = False
            for token in TOKEN_TO_BUY:
                has_position = self.has_open_position(token)
                position_status = "УСРЕДНЕНИЕ" if has_position else "НОВАЯ ПОЗИЦИЯ"
                logger.info(f"      │  🔍 Анализируем {token} ({position_status})...")
                
                if self.should_buy(token):
                    action = "усредняем позицию" if has_position else "открываем новую позицию"
                    logger.info(f"      │  🎯 Условия покупки {token} выполнены, {action}...")
                    buy_result = self.buy_token(token)
                    if buy_result:
                        result_text = "усреднили позицию" if has_position else "открыли новую позицию"
                        logger.success(f"      │  ✅ Успешно {result_text} по {token}")
                        has_purchases = True
                    else:
                        logger.error(f"      │  ❌ Не удалось купить {token}")
                        logger.error(f"      │    💡 Проверьте баланс, минимальную сумму заказа или настройки биржи")
                else:
                    reason = "для усреднения" if has_position else "для новой позиции"
                    logger.info(f"      │  ⏳ Условия покупки {token} не выполнены {reason}")
            
            if not has_purchases:
                logger.info("      │  ⭕ Нет подходящих условий для покупки")
            logger.info("      └─")
            logger.info("")
            
            logger.info("╔════════════════════════════════════════════════════════════════════════════════╗")
            logger.info("║                           ✅ КОНЕЦ ЦИКЛА ТОРГОВЛИ                              ║")
            logger.info("╚════════════════════════════════════════════════════════════════════════════════╝")
                    
        except Exception as e:
            logger.error(f"❌ Ошибка в цикле торговли: {e}")

    def should_sell(self, token: str, buy_price: float) -> bool:
        """Проверить нужно ли продавать токен"""
        current_price = self.get_current_price(token)
        if not current_price:
            return False
        
        # Рассчитываем процент роста от цены покупки
        price_change_percent = ((current_price - buy_price) / buy_price) * 100
        sell_threshold = PROCENT_TO_BUY_SELL[1]  # Процент роста для продажи
        
        should_sell = price_change_percent >= sell_threshold
        
        if should_sell:
            colored_message = format_position_message(
                token, buy_price, current_price, price_change_percent, 
                "💰 ПРОДАЕМ!", "📈"
            )
            logger.opt(colors=True).success(colored_message)
        else:
            if price_change_percent < 0:
                colored_message = format_position_message(
                    token, buy_price, current_price, price_change_percent, 
                    "⏳ Ждем роста", "📉"
                )
                logger.opt(colors=True).warning(colored_message)
            else:
                colored_message = format_position_message(
                    token, buy_price, current_price, price_change_percent, 
                    "⏳ Недостаточный рост", "📊"
                )
                logger.opt(colors=True).info(colored_message)
        
        return should_sell

    def should_buy(self, token: str) -> bool:
        """Проверить нужно ли покупать токен с учетом усреднения позиций"""
        current_price = self.get_current_price(token)
        if not current_price:
            logger.warning(f"      │    ⚠️ {token}: Не удалось получить текущую цену")
            return False

        price_change = self.get_24h_price_change(token)
        if price_change is None:
            logger.warning(f"      │    ⚠️ {token}: Недостаточно данных для анализа покупки")
            return False
        
        buy_threshold = PROCENT_TO_BUY_SELL[0]  # Процент падения для покупки
        has_position = self.has_open_position(token)
        
        if not has_position:
            # Первая покупка - проверяем падение за 24ч
            should_buy = price_change <= -buy_threshold
            
            if should_buy:
                colored_message = format_buy_message(token, price_change, buy_threshold, "ПЕРВАЯ ПОКУПКА")
                logger.opt(colors=True).success(colored_message)
            else:
                if price_change < 0:
                    logger.info(f"      │    📊 {token}: изменение за 24ч = {price_change:.2f}%, порог = -{buy_threshold}% → ⏳ Недостаточное падение")
                else:
                    logger.info(f"      │    📈 {token}: изменение за 24ч = +{price_change:.2f}%, порог = -{buy_threshold}% → ⏳ Цена растет")
            
            return should_buy
        else:
            # Есть открытая позиция - проверяем усреднение
            last_buy_price = self.get_last_buy_price(token)
            if not last_buy_price:
                logger.warning(f"      │    ⚠️ {token}: Не удалось получить цену последней покупки")
                return False
            
            # Рассчитываем падение от последней покупки
            price_drop_from_last = ((last_buy_price - current_price) / last_buy_price) * 100
            should_average = price_drop_from_last >= buy_threshold
            
            if should_average:
                msg1, msg2 = format_averaging_message(token, last_buy_price, current_price, price_drop_from_last, buy_threshold)
                logger.opt(colors=True).success(msg1)
                logger.opt(colors=True).success(msg2)
            else:
                if price_drop_from_last > 0:
                    logger.info(f"      │    📊 {token}: ЕСТЬ ПОЗИЦИЯ | последняя покупка = {last_buy_price:.2f}, текущая = {current_price:.2f}")
                    logger.info(f"      │    📊 {token}: падение от последней = {price_drop_from_last:.2f}%, нужно = {buy_threshold}% → ⏳ Недостаточное падение для усреднения")
                else:
                    logger.info(f"      │    📈 {token}: ЕСТЬ ПОЗИЦИЯ | последняя покупка = {last_buy_price:.2f}, текущая = {current_price:.2f}")
                    logger.info(f"      │    📈 {token}: цена выше последней покупки на {abs(price_drop_from_last):.2f}% → ⏳ Ждем падения для усреднения")
            
            return should_average

    def process_trading_cycle(self):
        """Выполнить один цикл торговли"""
        try:
            logger.info("╔════════════════════════════════════════════════════════════════════════════════╗")
            logger.info("║                          🚀 НАЧАЛО ЦИКЛА ТОРГОВЛИ                              ║")
            logger.info("╚════════════════════════════════════════════════════════════════════════════════╝")
            
            # Обновляем цены для всех токенов
            logger.info("      ┌─ 📊 ПОЛУЧЕНИЕ ТЕКУЩИХ ЦЕН:")
            for token in TOKEN_TO_BUY:
                current_price = self.get_current_price(token)
                if current_price:
                    self.save_price_to_db(token, current_price)
                    logger.info(f"      │  💱 {token}: {current_price:,.2f} {TOKEN_TO_BUY_FOR}")
            
            # Проверяем баланс базовой валюты
            base_balance = self.get_balance(TOKEN_TO_BUY_FOR)
            logger.info(f"      └─ 💰 Баланс {TOKEN_TO_BUY_FOR}: {base_balance:,.6f}")
            logger.info("")
            
            # Показываем статус позиций
            logger.info("      ┌─ 🎯 СТАТУС ПОЗИЦИЙ:")
            for token in TOKEN_TO_BUY:
                has_position = self.has_open_position(token)
                if has_position:
                    last_buy_price = self.get_last_buy_price(token)
                    current_price = self.get_current_price(token)
                    if last_buy_price and current_price:
                        price_diff = ((current_price - last_buy_price) / last_buy_price) * 100
                        logger.info(f"      │  📦 {token}: ЕСТЬ ПОЗИЦИЯ | последняя покупка = {last_buy_price:.2f}, сейчас = {current_price:.2f} ({price_diff:+.2f}%)")
                else:
                    logger.info(f"      │  ⭕ {token}: НЕТ ПОЗИЦИИ")
            logger.info("      └─")
            logger.info("")
            
            # Проверяем открытые позиции на продажу
            open_transactions = self.get_open_transactions()
            logger.info("      ┌─ 📋 АНАЛИЗ ОТКРЫТЫХ ПОЗИЦИЙ НА ПРОДАЖУ:")
            logger.info(f"      │  📦 Открытых позиций: {len(open_transactions)}")
            
            if open_transactions:
                for transaction in open_transactions:
                    #logger.info(f"      │  🔍 Проверяем позицию {transaction['token']}: куплено по {transaction['buy_price']:.2f}")
                    if self.should_sell(transaction['token'], transaction['buy_price']):
                        logger.info(f"      │  🎯 Продаем {transaction['token']}")
                        if self.sell_token(
                            transaction['id'],
                            transaction['token'],
                            transaction['buy_price'],
                            transaction['buy_amount']
                        ):
                            logger.success(f"      │  ✅ Успешно продан {transaction['token']}")
                        else:
                            logger.error(f"      │  ❌ Ошибка продажи {transaction['token']}")
            else:
                logger.info("      │  ⭕ Нет открытых позиций")
            logger.info("      └─")
            logger.info("")
            
            # Проверяем возможности для покупки (с учетом усреднения)
            logger.info("      ┌─ 🛒 АНАЛИЗ ВОЗМОЖНОСТЕЙ ПОКУПКИ (С УСРЕДНЕНИЕМ):")
            has_purchases = False
            for token in TOKEN_TO_BUY:
                has_position = self.has_open_position(token)
                position_status = "УСРЕДНЕНИЕ" if has_position else "НОВАЯ ПОЗИЦИЯ"
                logger.info(f"      │  🔍 Анализируем {token} ({position_status})...")
                
                if self.should_buy(token):
                    action = "усредняем позицию" if has_position else "открываем новую позицию"
                    logger.info(f"      │  🎯 Условия покупки {token} выполнены, {action}...")
                    buy_result = self.buy_token(token)
                    if buy_result:
                        result_text = "усреднили позицию" if has_position else "открыли новую позицию"
                        logger.success(f"      │  ✅ Успешно {result_text} по {token}")
                        has_purchases = True
                    else:
                        logger.error(f"      │  ❌ Не удалось купить {token}")
                        logger.error(f"      │    💡 Проверьте баланс, минимальную сумму заказа или настройки биржи")
                else:
                    reason = "для усреднения" if has_position else "для новой позиции"
                    logger.info(f"      │  ⏳ Условия покупки {token} не выполнены {reason}")
            
            if not has_purchases:
                logger.info("      │  ⭕ Нет подходящих условий для покупки")
            logger.info("      └─")
            logger.info("")
            
            logger.info("╔════════════════════════════════════════════════════════════════════════════════╗")
            logger.info("║                           ✅ КОНЕЦ ЦИКЛА ТОРГОВЛИ                              ║")
            logger.info("╚════════════════════════════════════════════════════════════════════════════════╝")
                    
        except Exception as e:
            logger.error(f"❌ Ошибка в цикле торговли: {e}")

    def run_trading_bot(self):
        """Запустить торгового бота"""
        logger.info("╔════════════════════════════════════════════════════════════════════════════════╗")
        logger.info("║                        🤖 OKX SPOT TRADING BOT                                 ║")
        logger.info("║                              ЗАПУСК СИСТЕМЫ                                    ║")
        logger.info("╚════════════════════════════════════════════════════════════════════════════════╝")
        logger.info(f"🎯 Торгуемые токены: {', '.join(TOKEN_TO_BUY)}")
        logger.info(f"💱 Базовая валюта: {TOKEN_TO_BUY_FOR}")
        logger.info(f"📉 Порог покупки (падение): {PROCENT_TO_BUY_SELL[0]}%")
        logger.info(f"📈 Порог продажи (рост): {PROCENT_TO_BUY_SELL[1]}%")
        logger.info(f"⏰ Интервал проверки: {TIME_TO_CHECK_PRICE[0]}-{TIME_TO_CHECK_PRICE[1]} сек")
        logger.info("")
        
        # Отправляем уведомление о старте
        self.send_notification(
            "info",
            "Бот запущен",
            f"Торговля токенами: {', '.join(TOKEN_TO_BUY)}",
            base_token=TOKEN_TO_BUY_FOR
        )
        
        try:
            cycle_count = 0
            while True:
                cycle_count += 1
                logger.info(f"🔄 Выполняется цикл торговли #{cycle_count}...")
                logger.info("")
                
                self.process_trading_cycle()
                
                # Случайная задержка между проверками
                sleep_time = random.randint(TIME_TO_CHECK_PRICE[0], TIME_TO_CHECK_PRICE[1])
                logger.info(f"⏰ Следующая проверка через {sleep_time} секунд...")
                logger.info("═" * 80)
                logger.info("")
                time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            logger.info("")
            logger.info(" ╔════════════════════════════════════════════════════════════════════════════════╗")
            logger.info("║                           ⚠️ ОСТАНОВКА БОТА                                     ║")
            logger.info("╚════════════════════════════════════════════════════════════════════════════════╝")
            logger.info("🛑 Получен сигнал остановки. Завершение работы...")
            self.send_notification(
                "warning",
                "Бот остановлен",
                "Торговый бот был остановлен пользователем"
            )
        except Exception as e:
            logger.error("")
            logger.error("╔════════════════════════════════════════════════════════════════════════════════╗")
            logger.error("║                           ❌ КРИТИЧЕСКАЯ ОШИБКА                                ║")
            logger.error("╚════════════════════════════════════════════════════════════════════════════════╝")
            logger.error(f"💥 Критическая ошибка: {e}")
            self.send_notification(
                "error",
                "Критическая ошибка",
                f"Бот остановлен из-за ошибки: {str(e)}",
                error_details=str(e)
            )

    def get_open_transactions(self) -> List[Dict]:
        """Получить открытые транзакции с полной информацией"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, token, buy_price, buy_amount, buy_date, buy_total_usdt, target_sell_price 
            FROM transactions 
            WHERE status = 'open'
            ORDER BY buy_date DESC
        ''')
        transactions = []
        for row in cursor.fetchall():
            transactions.append({
                'id': row[0],
                'token': row[1],
                'buy_price': row[2],
                'buy_amount': row[3],
                'buy_time': row[4],
                'buy_total_usdt': row[5],
                'target_sell_price': row[6]
            })
        conn.close()
        return transactions

    def get_last_buy_price(self, token: str) -> Optional[float]:
        """Получить цену последней покупки для токена"""
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT buy_price FROM transactions 
                WHERE token = ? AND status = 'open'
                ORDER BY buy_date DESC LIMIT 1
            ''', (token,))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                return result[0]
            return None
        except Exception as e:
            logger.error(f"Ошибка получения последней цены покупки для {token}: {e}")
            return None

    def has_open_position(self, token: str) -> bool:
        """Проверить есть ли открытая позиция по токену"""
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM transactions 
                WHERE token = ? AND status = 'open'
            ''', (token,))
            
            count = cursor.fetchone()[0]
            conn.close()
            return count > 0
        except Exception as e:
            logger.error(f"Ошибка проверки открытой позиции для {token}: {e}")
            return False

    def should_sell(self, token: str, buy_price: float) -> bool:
        """Проверить нужно ли продавать токен"""
        current_price = self.get_current_price(token)
        if not current_price:
            return False
        
        # Рассчитываем процент роста от цены покупки
        price_change_percent = ((current_price - buy_price) / buy_price) * 100
        sell_threshold = PROCENT_TO_BUY_SELL[1]  # Процент роста для продажи
        
        should_sell = price_change_percent >= sell_threshold
        
        if should_sell:
            colored_message = format_position_message(
                token, buy_price, current_price, price_change_percent, 
                "💰 ПРОДАЕМ!", "📈"
            )
            logger.opt(colors=True).success(colored_message)
        else:
            if price_change_percent < 0:
                colored_message = format_position_message(
                    token, buy_price, current_price, price_change_percent, 
                    "⏳ Ждем роста", "📉"
                )
                logger.opt(colors=True).warning(colored_message)
            else:
                colored_message = format_position_message(
                    token, buy_price, current_price, price_change_percent, 
                    "⏳ Недостаточный рост", "📊"
                )
                logger.opt(colors=True).info(colored_message)
        
        return should_sell

    def should_buy(self, token: str) -> bool:
        """Проверить нужно ли покупать токен с учетом усреднения позиций"""
        current_price = self.get_current_price(token)
        if not current_price:
            logger.warning(f"      │    ⚠️ {token}: Не удалось получить текущую цену")
            return False

        price_change = self.get_24h_price_change(token)
        if price_change is None:
            logger.warning(f"      │    ⚠️ {token}: Недостаточно данных для анализа покупки")
            return False
        
        buy_threshold = PROCENT_TO_BUY_SELL[0]  # Процент падения для покупки
        has_position = self.has_open_position(token)
        
        if not has_position:
            # Первая покупка - проверяем падение за 24ч
            should_buy = price_change <= -buy_threshold
            
            if should_buy:
                colored_message = format_buy_message(token, price_change, buy_threshold, "ПЕРВАЯ ПОКУПКА")
                logger.opt(colors=True).success(colored_message)
            else:
                if price_change < 0:
                    logger.info(f"      │    📊 {token}: изменение за 24ч = {price_change:.2f}%, порог = -{buy_threshold}% → ⏳ Недостаточное падение")
                else:
                    logger.info(f"      │    📈 {token}: изменение за 24ч = +{price_change:.2f}%, порог = -{buy_threshold}% → ⏳ Цена растет")
            
            return should_buy
        else:
            # Есть открытая позиция - проверяем усреднение
            last_buy_price = self.get_last_buy_price(token)
            if not last_buy_price:
                logger.warning(f"      │    ⚠️ {token}: Не удалось получить цену последней покупки")
                return False
            
            # Рассчитываем падение от последней покупки
            price_drop_from_last = ((last_buy_price - current_price) / last_buy_price) * 100
            should_average = price_drop_from_last >= buy_threshold
            
            if should_average:
                msg1, msg2 = format_averaging_message(token, last_buy_price, current_price, price_drop_from_last, buy_threshold)
                logger.opt(colors=True).success(msg1)
                logger.opt(colors=True).success(msg2)
            else:
                if price_drop_from_last > 0:
                    logger.info(f"      │    📊 {token}: ЕСТЬ ПОЗИЦИЯ | последняя покупка = {last_buy_price:.2f}, текущая = {current_price:.2f}")
                    logger.info(f"      │    📊 {token}: падение от последней = {price_drop_from_last:.2f}%, нужно = {buy_threshold}% → ⏳ Недостаточное падение для усреднения")
                else:
                    logger.info(f"      │    📈 {token}: ЕСТЬ ПОЗИЦИЯ | последняя покупка = {last_buy_price:.2f}, текущая = {current_price:.2f}")
                    logger.info(f"      │    📈 {token}: цена выше последней покупки на {abs(price_drop_from_last):.2f}% → ⏳ Ждем падения для усреднения")
            
            return should_average

def start_okx_spot_trading():
    """Главная функция для запуска торговли"""
    # Выбираем аккаунт OKX
    exchange_name, account = select_okx_account()
    if not account:
        logger.error("❌ Не выбран аккаунт OKX")
        return
    
    # Создаем трейдера с выбранным аккаунтом
    trader = OKXSpotTrader(account=account)
    trader.run_trading_bot()


if __name__ == "__main__":
    start_okx_spot_trading()
