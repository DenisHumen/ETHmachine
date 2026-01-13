"""
База данных для хранения прогресса выполнения Twitter задач
"""
import sqlite3
import json
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from loguru import logger

# Количество попыток для операций с БД
DB_RETRY_COUNT = 5
DB_RETRY_DELAY = 0.5  # секунды между попытками


def with_retry(func):
    """Декоратор для повторных попыток при ошибках SQLite"""
    def wrapper(*args, **kwargs):
        last_error = None
        for attempt in range(DB_RETRY_COUNT):
            try:
                return func(*args, **kwargs)
            except sqlite3.OperationalError as e:
                last_error = e
                error_msg = str(e).lower()
                # Ошибки, которые можно повторить
                if 'disk i/o error' in error_msg or 'database is locked' in error_msg or 'busy' in error_msg:
                    if attempt < DB_RETRY_COUNT - 1:
                        logger.warning(f"SQLite ошибка (попытка {attempt + 1}/{DB_RETRY_COUNT}): {e}")
                        time.sleep(DB_RETRY_DELAY * (attempt + 1))  # Увеличиваем задержку
                        continue
                raise
        raise last_error
    return wrapper


class TwitterTaskDatabase:
    """Управление базой данных для Twitter задач"""
    
    def __init__(self, db_path: str = "db/twitter_tasks_progress.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = None
        self.init_database()
    
    def init_database(self):
        """Инициализация базы данных"""
        try:
            self.conn = sqlite3.connect(
                self.db_path,
                timeout=30.0,  # Увеличенный таймаут для WSL
                isolation_level=None  # Autocommit для уменьшения блокировок
            )
            self.conn.row_factory = sqlite3.Row
            
            # Настройки для улучшения стабильности на WSL/сетевых дисках
            self.conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging
            self.conn.execute("PRAGMA synchronous=NORMAL")  # Баланс скорости и надежности
            self.conn.execute("PRAGMA busy_timeout=30000")  # 30 секунд ожидания при блокировке
            self.conn.execute("PRAGMA temp_store=MEMORY")  # Временные таблицы в памяти
            
            self._create_tables()
            logger.info(f"База данных инициализирована: {self.db_path}")
        except Exception as e:
            logger.error(f"Ошибка инициализации БД: {e}")
            raise
    
    @with_retry
    def _execute_commit(self):
        """Выполняет commit с retry"""
        self.conn.commit()
    
    def _create_tables(self):
        """Создание таблиц"""
        cursor = self.conn.cursor()
        
        # Таблица задач
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                task_link TEXT,
                task_value TEXT,
                repetitions INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending'
            )
        ''')
        
        # Таблица операций (развернутые задачи с повторениями)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                account_nickname TEXT NOT NULL,
                account_auth_token TEXT NOT NULL,
                account_proxy TEXT,
                account_index INTEGER,
                repetition_num INTEGER,
                status TEXT DEFAULT 'pending',
                result_username TEXT,
                result_message TEXT,
                executed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks (id)
            )
        ''')
        
        # Таблица результатов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_id INTEGER NOT NULL,
                account TEXT,
                username TEXT,
                task_type TEXT,
                task_link TEXT,
                task_value TEXT,
                repetition TEXT,
                status TEXT,
                message TEXT,
                timestamp TIMESTAMP,
                FOREIGN KEY (operation_id) REFERENCES operations (id)
            )
        ''')
        
        # Таблица сессий (для отслеживания запусков)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                total_operations INTEGER DEFAULT 0,
                completed_operations INTEGER DEFAULT 0,
                successful_operations INTEGER DEFAULT 0,
                failed_operations INTEGER DEFAULT 0,
                status TEXT DEFAULT 'running'
            )
        ''')
        
        # Индексы для быстрого поиска
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_operations_status ON operations(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_operations_task_id ON operations(task_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)')
        
        self._execute_commit()
        logger.success("Таблицы базы данных созданы")
    
    def create_session(self, session_id: str, total_operations: int) -> int:
        """Создает новую сессию"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO sessions (session_id, total_operations, status)
            VALUES (?, ?, 'running')
        ''', (session_id, total_operations))
        self._execute_commit()
        logger.info(f"Создана сессия: {session_id}")
        return cursor.lastrowid
    
    def get_active_session(self) -> Optional[Dict]:
        """Получает активную сессию"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM sessions 
            WHERE status = 'running' 
            ORDER BY started_at DESC 
            LIMIT 1
        ''')
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def update_session_progress(self, session_id: str, completed: int, successful: int, failed: int):
        """Обновляет прогресс сессии"""
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE sessions 
            SET completed_operations = ?,
                successful_operations = ?,
                failed_operations = ?
            WHERE session_id = ?
        ''', (completed, successful, failed, session_id))
        self._execute_commit()
    
    def complete_session(self, session_id: str):
        """Завершает сессию"""
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE sessions 
            SET status = 'completed',
                completed_at = CURRENT_TIMESTAMP
            WHERE session_id = ?
        ''', (session_id,))
        self._execute_commit()
        logger.success(f"Сессия завершена: {session_id}")
    
    def save_tasks(self, tasks: List[Dict]) -> List[int]:
        """Сохраняет задачи в БД"""
        cursor = self.conn.cursor()
        task_ids = []
        
        for task in tasks:
            # Определяем количество повторений
            if task['type'] in ['tweet', 'comment']:
                repetitions = 1
            else:
                try:
                    repetitions = int(task['value']) if task['value'] else 1
                    repetitions = max(1, repetitions)
                except (ValueError, TypeError):
                    repetitions = 1
            
            cursor.execute('''
                INSERT INTO tasks (task_type, task_link, task_value, repetitions, status)
                VALUES (?, ?, ?, ?, 'pending')
            ''', (task['type'], task['link'], task['value'], repetitions))
            
            task_ids.append(cursor.lastrowid)
        
        self._execute_commit()
        logger.info(f"Сохранено {len(task_ids)} задач в БД")
        return task_ids
    
    def save_operations(self, operations: List[Dict]) -> List[int]:
        """Сохраняет операции в БД"""
        cursor = self.conn.cursor()
        operation_ids = []
        
        for op in operations:
            cursor.execute('''
                INSERT INTO operations 
                (task_id, account_nickname, account_auth_token, account_proxy, 
                 account_index, repetition_num, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
            ''', (
                op['task_id'],
                op['account']['nickname'],
                op['account']['auth_token'],
                op['account']['proxy'],
                op['account_index'],
                op['repetition']
            ))
            
            operation_ids.append(cursor.lastrowid)
        
        self._execute_commit()
        logger.info(f"Сохранено {len(operation_ids)} операций в БД")
        return operation_ids
    
    def get_pending_operations(self) -> List[Dict]:
        """Получает незавершенные операции"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT o.*, t.task_type, t.task_link, t.task_value
            FROM operations o
            JOIN tasks t ON o.task_id = t.id
            WHERE o.status = 'pending'
            ORDER BY o.id
        ''')
        
        operations = []
        for row in cursor.fetchall():
            operations.append({
                'id': row['id'],
                'task_id': row['task_id'],
                'task': {
                    'type': row['task_type'],
                    'link': row['task_link'],
                    'value': row['task_value']
                },
                'account': {
                    'nickname': row['account_nickname'],
                    'auth_token': row['account_auth_token'],
                    'proxy': row['account_proxy']
                },
                'account_index': row['account_index'],
                'repetition': row['repetition_num']
            })
        
        logger.info(f"Найдено {len(operations)} незавершенных операций")
        return operations
    
    def update_operation_status(self, operation_id: int, status: str, 
                               username: str = None, message: str = None):
        """Обновляет статус операции"""
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE operations 
            SET status = ?,
                result_username = ?,
                result_message = ?,
                executed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (status, username, message, operation_id))
        self._execute_commit()
    
    def save_result(self, operation_id: int, result: Dict):
        """Сохраняет результат выполнения"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO results 
            (operation_id, account, username, task_type, task_link, task_value,
             repetition, status, message, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            operation_id,
            result.get('account', ''),
            result.get('username', ''),
            result.get('task_type', ''),
            result.get('task_link', ''),
            result.get('task_value', ''),
            result.get('repetition', ''),
            result.get('status', 'failed'),
            result.get('message', ''),
            result.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        ))
        self._execute_commit()
    
    def get_all_results(self) -> List[Dict]:
        """Получает все результаты"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM results ORDER BY id')
        
        results = []
        for row in cursor.fetchall():
            results.append(dict(row))
        
        return results
    
    def get_statistics(self) -> Dict:
        """Получает статистику выполнения"""
        cursor = self.conn.cursor()
        
        # Общая статистика операций
        cursor.execute('''
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending
            FROM operations
        ''')
        stats = dict(cursor.fetchone())
        
        # Статистика по типам задач
        cursor.execute('''
            SELECT 
                t.task_type,
                COUNT(o.id) as total,
                SUM(CASE WHEN o.status = 'success' THEN 1 ELSE 0 END) as successful,
                SUM(CASE WHEN o.status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN o.status = 'pending' THEN 1 ELSE 0 END) as pending
            FROM operations o
            JOIN tasks t ON o.task_id = t.id
            GROUP BY t.task_type
        ''')
        
        stats['by_task_type'] = {}
        for row in cursor.fetchall():
            stats['by_task_type'][row['task_type']] = dict(row)
        
        return stats
    
    def clear_all_data(self):
        """Очищает все данные (для нового запуска)"""
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM results')
        cursor.execute('DELETE FROM operations')
        cursor.execute('DELETE FROM tasks')
        cursor.execute('DELETE FROM sessions')
        self._execute_commit()
        logger.warning("Все данные из БД удалены")
    
    def has_pending_operations(self) -> bool:
        """Проверяет наличие незавершенных операций"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) as count FROM operations WHERE status = "pending"')
        count = cursor.fetchone()['count']
        return count > 0
    
    def close(self):
        """Закрывает соединение с БД"""
        if self.conn:
            self.conn.close()
            logger.info("Соединение с БД закрыто")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
