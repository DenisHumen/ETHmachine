"""
Модуль выполнения задач Twitter
Интеграция с существующим Twitter Task модулем
"""

import os
import csv
import asyncio
from datetime import datetime
from pathlib import Path
from modules.simple_logger import logger
from modules.ui import ui
from colorama import Fore

# Добавляем путь к корневой директории проекта
import sys
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.join(current_dir, '..', '..')
sys.path.append(project_root)

# Импортируем настройки из config
from config.modules.cfg_twitter import (
    TWITTER_TASK_SSL_VERIFICATION,
    TWITTER_TASK_DELAY_BETWEEN_TASKS,
    TWITTER_TASK_DELAY_BETWEEN_ACCOUNTS,
    TWITTER_TASK_RANDOM_ACCOUNT_SELECTION,
    TWITTER_TASK_MAX_ACCOUNT_SWITCHES
)
from config.modules.general_config import NUM_THREADS

# Импортируем Twitter класс из существующего модуля
from .twitter_task import Twitter
from .twitter_task_db import TwitterTaskDatabase
import random
import uuid

class Config:
    """Конфигурация для Twitter модуля"""
    SSL_VERIFICATION = TWITTER_TASK_SSL_VERIFICATION
    DELAY_BETWEEN_TASKS = TWITTER_TASK_DELAY_BETWEEN_TASKS
    DELAY_BETWEEN_ACCOUNTS = TWITTER_TASK_DELAY_BETWEEN_ACCOUNTS
    NUM_THREADS = NUM_THREADS
    RANDOM_ACCOUNT_SELECTION = TWITTER_TASK_RANDOM_ACCOUNT_SELECTION
    MAX_ACCOUNT_SWITCHES = TWITTER_TASK_MAX_ACCOUNT_SWITCHES


class TwitterTaskRunner:
    """Класс для выполнения Twitter задач с поддержкой БД"""

    def __init__(self):
        self.config = Config()
        self.accounts = []
        self.tasks = []
        self.results = []
        self.db = TwitterTaskDatabase()
        self.session_id = str(uuid.uuid4())[:8]

    def load_accounts(self):
        """Загружает аккаунты из data/twitter/twitters.csv"""
        accounts_file = 'data/twitter/twitters.csv'

        if not os.path.exists(accounts_file):
            logger.error(f"Файл аккаунтов не найден: {accounts_file}")
            return False

        self.accounts = []
        try:
            with open(accounts_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                account_counter = 1
                for row in reader:
                    # Безопасное получение значений
                    nickname = (row.get('nickname') or '').strip()
                    auth_token = (row.get('auth_token') or '').strip()
                    ct0 = (row.get('ct0') or '').strip()
                    proxy = (row.get('proxy') or '').strip()

                    # Пропускаем строки где нет auth_token
                    if not auth_token or auth_token.startswith('#'):
                        continue

                    # Если nickname пустой, генерируем автоматически
                    if not nickname:
                        nickname = f"account_{account_counter}"
                        account_counter += 1

                    # Пропускаем комментарии
                    if nickname.startswith('#'):
                        continue

                    # Добавляем поддержку пустого прокси
                    if not proxy:
                        proxy = None

                    account = {
                        'nickname': nickname,
                        'auth_token': auth_token,
                        'ct0': ct0,
                        'proxy': proxy
                    }
                    self.accounts.append(account)

            logger.info(f"Загружено {len(self.accounts)} аккаунтов")
            return True

        except Exception as e:
            logger.error(f"Ошибка загрузки аккаунтов: {e}")
            return False

    def load_tasks(self):
        """Загружает задачи из data/twitter/twitter_task.csv"""
        tasks_file = 'data/twitter/twitter_task.csv'

        if not os.path.exists(tasks_file):
            logger.error(f"Файл задач не найден: {tasks_file}")
            return False

        self.tasks = []
        try:
            with open(tasks_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Безопасное получение значений
                    link = (row.get('link') or '').strip()
                    task_type = (row.get('type') or '').strip()
                    value = (row.get('value') or '').strip()

                    # Пропускаем строки где type начинается с # (комментарии)
                    if not task_type or task_type.startswith('#'):
                        continue

                    # Для твитов link может быть пустым
                    if link.startswith('#'):
                        if task_type.lower() == 'tweet':
                            link = ''  # Для твитов link не обязателен
                        else:
                            continue  # Для остальных задач пропускаем комментарии

                    if task_type and (link or task_type.lower() == 'tweet'):
                        task = {
                            'link': link,
                            'type': task_type.lower(),
                            'value': value
                        }
                        self.tasks.append(task)

            logger.info(f"Загружено {len(self.tasks)} задач")
            return True

        except Exception as e:
            logger.error(f"Ошибка загрузки задач: {e}")
            return False

    def extract_tweet_id(self, link):
        """Извлекает ID твита из ссылки"""
        try:
            # Поддерживаем различные форматы ссылок
            if '/status/' in link:
                tweet_id = link.split('/status/')[-1].split('?')[0].split('/')[0]
            elif '/tweet/' in link:
                tweet_id = link.split('/tweet/')[-1].split('?')[0].split('/')[0]
            else:
                # Если это просто ID (только если состоит из цифр)
                tweet_id = link.strip()
                if not tweet_id.isdigit():
                    return None

            # Проверяем что ID состоит только из цифр
            if tweet_id.isdigit():
                return tweet_id
            else:
                return None

        except Exception as e:
            logger.error(f"Ошибка извлечения ID твита: {e}")
            return None

    def extract_username(self, link):
        """Извлекает username из ссылки на профиль"""
        try:
            # Убираем протокол и домен
            if '://' in link:
                link = link.split('://', 1)[1]

            if link.startswith('x.com/') or link.startswith('twitter.com/'):
                username = link.split('/', 1)[1].split('/')[0].split('?')[0]
                # Убираем @ если есть
                username = username.lstrip('@')
                return username

            # Если это просто username
            username = link.strip().lstrip('@')
            return username

        except Exception as e:
            logger.error(f"Ошибка извлечения username: {e}")
            return None

    async def execute_task(self, twitter_client, task, repetitions=1):
        """
        Выполняет одну задачу с возможностью повторений

        Args:
            twitter_client: Клиент Twitter
            task: Задача для выполнения
            repetitions: Количество повторений (по умолчанию 1)
        """
        task_type = task['type']
        link = task['link']
        value = task['value']

        try:
            if task_type == 'like':
                tweet_id = self.extract_tweet_id(link)
                if not tweet_id:
                    return False, "Не удалось извлечь ID твита"

                result = await twitter_client.like(tweet_id)
                return result, "Лайк поставлен" if result else "Ошибка лайка"

            elif task_type == 'retweet':
                tweet_id = self.extract_tweet_id(link)
                if not tweet_id:
                    return False, "Не удалось извлечь ID твита"

                result = await twitter_client.retweet(tweet_id)
                return result, "Ретвит выполнен" if result else "Ошибка ретвита"

            elif task_type == 'follow':
                username = self.extract_username(link)
                if not username:
                    return False, "Не удалось извлечь username"

                result = await twitter_client.follow(username)
                return result, f"Подписка на {username}" if result else f"Ошибка подписки на {username}"

            elif task_type == 'unfollow':
                username = self.extract_username(link)
                if not username:
                    return False, "Не удалось извлечь username"

                result = await twitter_client.unfollow(username)
                return result, f"Отписка от {username}" if result else f"Ошибка отписки от {username}"

            elif task_type == 'tweet':
                text = value if value else "Hello World! 🚀"
                result = await twitter_client.tweet(text)
                return result, "Твит опубликован" if result else "Ошибка публикации твита"

            elif task_type == 'comment':
                tweet_id = self.extract_tweet_id(link)
                if not tweet_id:
                    return False, "Не удалось извлечь ID твита"

                comment_text = value if value else "Great post! 👍"
                # Именованные аргументы: сигнатура comment() принимает text первым,
                # позиционный вызов молча менял местами текст и ID твита
                result = await twitter_client.comment(text=comment_text, tweet_id=tweet_id)
                return result, "Комментарий опубликован" if result else "Ошибка публикации комментария"

            else:
                return False, f"Неизвестный тип задачи: {task_type}"

        except Exception as e:
            return False, f"Ошибка выполнения задачи: {e}"

    async def check_and_choose_mode(self) -> str:
        """Проверяет наличие незавершенных задач и предлагает выбор"""
        if self.db.has_pending_operations():
            stats = self.db.get_statistics()
            pending = stats.get('pending', 0)
            completed = stats.get('successful', 0) + stats.get('failed', 0)
            total = stats.get('total', 0)

            print(Fore.YELLOW + f"\n⚠️  Найдены незавершенные задачи в базе данных!")
            print(Fore.WHITE + f"  📊 Прогресс: {completed}/{total} операций выполнено")
            print(Fore.WHITE + f"  ⏳ Осталось: {pending} операций\n")

            choice = ui.menu("Что делать?", [
                ("🔄 Продолжить с места остановки", "continue"),
                ("🆕 Начать заново — удалить старые данные", "restart"),
                ("❌ Отмена", "cancel"),
            ])

            if choice == "restart":
                if ui.confirm("Точно удалить весь прогресс?", default=False):
                    self.db.clear_all_data()
                    logger.warning("База данных очищена")
                    return "new"
                else:
                    return "cancel"

            return choice if choice else "cancel"

        return "new"

    async def run_all_tasks(self, mode: str = "new"):
        """
        Выполняет задачи с поддержкой БД для сохранения прогресса.
        Поддерживает продолжение с места остановки.

        Args:
            mode: Режим работы - "new" (новый запуск), "continue" (продолжение), "cancel" (отмена)
        """
        if not self.accounts:
            logger.error("Нет загруженных аккаунтов")
            return []

        if mode == "cancel":
            print(Fore.YELLOW + "Операция отменена пользователем")
            return []

        if mode == "continue":
            # Продолжаем выполнение незавершенных операций
            return await self._continue_execution()
        else:
            # Новый запуск
            if not self.tasks:
                logger.error("Нет загруженных задач")
                return []

            return await self._start_new_execution()

    async def _start_new_execution(self):
        """Начинает новое выполнение задач"""
        # Сохраняем задачи в БД
        task_ids = self.db.save_tasks(self.tasks)

        # Подготавливаем операции
        operations = []
        account_index = 0

        for task_idx, task in enumerate(self.tasks):
            task_id = task_ids[task_idx]
            task_type = task['type']

            # Определяем количество повторений
            if task_type in ['tweet', 'comment']:
                repetitions = 1
            else:
                try:
                    repetitions = int(task['value']) if task['value'] else 1
                    repetitions = max(1, repetitions)
                except (ValueError, TypeError):
                    repetitions = 1

            # Создаем операции для каждого повторения
            for rep in range(repetitions):
                # Выбираем аккаунт
                if self.config.RANDOM_ACCOUNT_SELECTION:
                    account = random.choice(self.accounts)
                    account_display_index = self.accounts.index(account) + 1
                else:
                    if account_index >= len(self.accounts):
                        account_index = 0
                    account = self.accounts[account_index]
                    account_display_index = account_index + 1
                    account_index += 1

                operations.append({
                    'task_id': task_id,
                    'task': task,
                    'account': account,
                    'account_index': account_display_index,
                    'repetition': rep + 1,
                    'total_repetitions': repetitions
                })

        # Сохраняем операции в БД
        operation_ids = self.db.save_operations(operations)

        # Добавляем ID операций
        for i, op in enumerate(operations):
            op['operation_id'] = operation_ids[i]

        # Создаем сессию
        self.db.create_session(self.session_id, len(operations))

        print(Fore.CYAN + f"\n📊 Планирование выполнения:")
        print(Fore.WHITE + f"  • Всего задач: {len(self.tasks)}")
        print(Fore.WHITE + f"  • Всего операций: {len(operations)}")
        print(Fore.WHITE + f"  • Доступно аккаунтов: {len(self.accounts)}")
        print(Fore.WHITE + f"  • Количество потоков: {self.config.NUM_THREADS}")
        print(Fore.WHITE + f"  • ID сессии: {self.session_id}")

        logger.info(f"Начало выполнения {len(self.tasks)} задач ({len(operations)} операций)")

        # Выполняем операции
        return await self._execute_operations(operations)

    async def _continue_execution(self):
        """Продолжает выполнение незавершенных операций"""
        # Получаем незавершенные операции из БД
        pending_ops = self.db.get_pending_operations()

        if not pending_ops:
            print(Fore.GREEN + "✅ Все задачи уже выполнены!")
            return []

        print(Fore.CYAN + f"\n🔄 Продолжение выполнения:")
        print(Fore.WHITE + f"  • Осталось операций: {len(pending_ops)}")
        print(Fore.WHITE + f"  • Количество потоков: {self.config.NUM_THREADS}")

        logger.info(f"Продолжение выполнения {len(pending_ops)} операций")

        # Выполняем операции
        return await self._execute_operations(pending_ops)

    async def _execute_operations(self, operations: list):
        """Выполняет список операций с многопоточностью"""
        # Создаем семафор
        semaphore = asyncio.Semaphore(self.config.NUM_THREADS)

        # Добавляем семафор в каждую операцию
        for op in operations:
            op['semaphore'] = semaphore

        print(Fore.CYAN + f"\n🚀 Запуск {len(operations)} операций...\n")

        # Выполняем параллельно
        tasks_list = [
            self._execute_operation_with_semaphore(op)
            for op in operations
        ]

        all_results = await asyncio.gather(*tasks_list, return_exceptions=True)

        # Фильтруем исключения
        self.results = [r for r in all_results if not isinstance(r, Exception)]

        # Обновляем статистику сессии
        successful = sum(1 for r in self.results if r.get('status') == 'success')
        failed = len(self.results) - successful
        self.db.update_session_progress(self.session_id, len(self.results), successful, failed)
        self.db.complete_session(self.session_id)

        print(Fore.CYAN + f"\n{'='*70}")
        logger.success(f"✅ Все задачи завершены! Выполнено {len(self.results)} операций")
        print(Fore.CYAN + f"{'='*70}\n")

        return self.results

    async def _execute_operation_with_semaphore(self, operation):
        """Выполняет операцию с учетом семафора и сохраняет в БД"""
        async with operation['semaphore']:
            operation_id = operation.get('operation_id') or operation.get('id')
            task = operation['task']
            account = operation['account']
            account_index = operation['account_index']
            repetition = operation['repetition']
            total_repetitions = operation.get('total_repetitions', 1)

            print(Fore.GREEN + f"[Поток] {task['type'].upper()} | " +
                  f"Повтор {repetition}/{total_repetitions} | " +
                  f"Аккаунт: {account['nickname']} (#{account_index})")

            # Выполняем задачу
            result = await self.execute_task_for_account(
                account,
                task,
                account_index,
                repetition,
                total_repetitions
            )

            # Сохраняем результат в БД
            if operation_id:
                status = 'success' if result.get('status') == 'success' else 'failed'
                self.db.update_operation_status(
                    operation_id,
                    status,
                    result.get('username'),
                    result.get('message')
                )
                self.db.save_result(operation_id, result)

            # Задержка между операциями
            delay = random.uniform(
                self.config.DELAY_BETWEEN_TASKS[0],
                self.config.DELAY_BETWEEN_TASKS[1]
            )
            await asyncio.sleep(delay)

            return result

    async def execute_task_for_account(self, account, task, account_index, repetition, total_repetitions):
        """Выполняет одну задачу для одного аккаунта"""
        nickname = account['nickname']
        auth_token = account['auth_token']
        proxy = account['proxy']

        result = {
            'account': nickname,
            'username': '',
            'task_type': task['type'],
            'task_link': task['link'],
            'task_value': task['value'],
            'repetition': f"{repetition}/{total_repetitions}",
            'status': 'failed',
            'message': '',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        try:
            async with Twitter(account_index, auth_token, proxy, self.config) as twitter_client:
                # Инициализация клиента
                if not await twitter_client.initialize():
                    result['message'] = f'Ошибка инициализации. Статус: {twitter_client.account_status}'
                    print(Fore.RED + f"   ❌ {result['message']}")
                    return result

                result['username'] = twitter_client.username
                print(Fore.GREEN + f"   ✓ Инициализирован: @{twitter_client.username}")

                # Выполняем задачу
                success, message = await self.execute_task(twitter_client, task, repetition)

                result['status'] = 'success' if success else 'failed'
                result['message'] = message

                if success:
                    print(Fore.GREEN + f"   ✅ {message}")
                else:
                    print(Fore.RED + f"   ❌ {message}")

        except Exception as e:
            result['message'] = f'Ошибка: {e}'
            print(Fore.RED + f"   ❌ {result['message']}")

        return result

    def save_results(self):
        """Сохраняет результаты из БД в CSV файл"""
        # Получаем все результаты из БД
        db_results = self.db.get_all_results()

        if not db_results and not self.results:
            logger.warning("Нет результатов для сохранения")
            return

        # Используем результаты из БД если они есть
        results_to_save = db_results if db_results else self.results

        # Создаем папку для результатов если её нет
        results_dir = Path('result/twitter')
        results_dir.mkdir(parents=True, exist_ok=True)

        # Генерируем имя файла с датой и временем
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        results_file = results_dir / f'twitter_tasks_results_{timestamp}.csv'

        try:
            with open(results_file, 'w', encoding='utf-8', newline='') as f:
                if results_to_save:
                    # Определяем поля для CSV
                    fieldnames = ['account', 'username', 'task_type', 'task_link',
                                'task_value', 'repetition', 'status', 'message', 'timestamp']
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()

                    for result in results_to_save:
                        # Фильтруем только нужные поля
                        row = {k: result.get(k, '') for k in fieldnames}
                        writer.writerow(row)

            logger.success(f"Результаты сохранены в: {results_file}")

            # Получаем статистику из БД
            stats = self.db.get_statistics()

            print(Fore.CYAN + f"\n{'='*70}")
            print(Fore.CYAN + f"📊 ИТОГОВАЯ СТАТИСТИКА")
            print(Fore.CYAN + f"{'='*70}")
            print(Fore.WHITE + f"\n  Всего операций: {stats.get('total', 0)}")
            print(Fore.GREEN + f"  ✅ Успешно: {stats.get('successful', 0)}")

            if stats.get('failed', 0) > 0:
                print(Fore.RED + f"  ❌ Ошибки: {stats.get('failed', 0)}")

            if stats.get('pending', 0) > 0:
                print(Fore.YELLOW + f"  ⏳ В ожидании: {stats.get('pending', 0)}")

            # Статистика по типам задач
            if stats.get('by_task_type'):
                print(Fore.CYAN + f"\n  По типам задач:")
                for task_type, task_stats in stats['by_task_type'].items():
                    total = task_stats.get('total', 0)
                    successful = task_stats.get('successful', 0)
                    print(Fore.WHITE + f"    • {task_type.upper():10} - {successful}/{total} успешно")

            print(Fore.CYAN + f"\n  📁 Результаты: {results_file.name}")
            print(Fore.CYAN + f"  🗄️  База данных: {self.db.db_path}")
            print(Fore.CYAN + f"{'='*70}\n")

        except Exception as e:
            logger.error(f"Ошибка сохранения результатов: {e}")

    def show_detailed_statistics(self):
        """Показывает детальную статистику из БД"""
        stats = self.db.get_statistics()

        print(Fore.CYAN + f"\n{'='*70}")
        print(Fore.CYAN + "📊 ДЕТАЛЬНАЯ СТАТИСТИКА")
        print(Fore.CYAN + f"{'='*70}\n")

        # Общая информация
        print(Fore.WHITE + "📈 Общая статистика:")
        print(Fore.WHITE + f"  • Всего операций: {stats.get('total', 0)}")
        print(Fore.GREEN + f"  • Успешно: {stats.get('successful', 0)}")
        print(Fore.RED + f"  • Ошибок: {stats.get('failed', 0)}")
        print(Fore.YELLOW + f"  • В ожидании: {stats.get('pending', 0)}")

        # Процент выполнения
        total = stats.get('total', 0)
        if total > 0:
            completed = stats.get('successful', 0) + stats.get('failed', 0)
            progress_pct = (completed / total) * 100
            print(Fore.CYAN + f"  • Прогресс: {progress_pct:.1f}%")

        # Статистика по типам
        if stats.get('by_task_type'):
            print(Fore.CYAN + f"\n📋 По типам задач:")
            for task_type, task_stats in stats['by_task_type'].items():
                total_type = task_stats.get('total', 0)
                successful = task_stats.get('successful', 0)
                failed = task_stats.get('failed', 0)
                pending = task_stats.get('pending', 0)

                success_rate = (successful / total_type * 100) if total_type > 0 else 0

                print(Fore.WHITE + f"\n  {task_type.upper()}:")
                print(Fore.WHITE + f"    • Всего: {total_type}")
                print(Fore.GREEN + f"    • Успешно: {successful} ({success_rate:.1f}%)")
                if failed > 0:
                    print(Fore.RED + f"    • Ошибок: {failed}")
                if pending > 0:
                    print(Fore.YELLOW + f"    • В ожидании: {pending}")

        # Информация о сессиях
        session = self.db.get_active_session()
        if session:
            print(Fore.CYAN + f"\n🔄 Активная сессия:")
            print(Fore.WHITE + f"  • ID: {session['session_id']}")
            print(Fore.WHITE + f"  • Начата: {session['started_at']}")
            print(Fore.WHITE + f"  • Прогресс: {session['completed_operations']}/{session['total_operations']}")

        print(Fore.CYAN + f"\n  🗄️  База данных: {self.db.db_path}")
        print(Fore.CYAN + f"{'='*70}\n")


def run_twitter_tasks():
    """Главная функция для запуска Twitter задач с поддержкой БД"""
    print(Fore.CYAN + "\n🐦 Twitter Task Runner")
    print("=" * 50)

    runner = TwitterTaskRunner()

    # Проверяем наличие незавершенных задач в БД
    if runner.db.has_pending_operations():
        stats = runner.db.get_statistics()
        pending = stats.get('pending', 0)
        completed = stats.get('successful', 0) + stats.get('failed', 0)
        total = stats.get('total', 0)

        print(Fore.YELLOW + f"\n⚠️  Найдены незавершенные задачи в базе данных!")
        print(Fore.WHITE + f"  📊 Прогресс: {completed}/{total} операций выполнено")
        print(Fore.WHITE + f"  ⏳ Осталось: {pending} операций")

        # Показываем статистику по типам задач
        if stats.get('by_task_type'):
            print(Fore.CYAN + f"\n  📋 По типам задач:")
            for task_type, task_stats in stats['by_task_type'].items():
                successful = task_stats.get('successful', 0)
                failed = task_stats.get('failed', 0)
                pending_type = task_stats.get('pending', 0)
                total_type = task_stats.get('total', 0)

                status = []
                if successful > 0:
                    status.append(f"{Fore.GREEN}✅ {successful}")
                if failed > 0:
                    status.append(f"{Fore.RED}❌ {failed}")
                if pending_type > 0:
                    status.append(f"{Fore.YELLOW}⏳ {pending_type}")

                print(Fore.WHITE + f"    • {task_type.upper():10} [{' '.join(status)}{Fore.WHITE}] из {total_type}")

        print()

        # Предлагаем выбор действия
        action = ui.menu("Что делаем?", [
            ("🔄 Продолжить с места остановки", "continue"),
            ("🆕 Начать заново — очистить БД и создать задачи", "restart"),
            ("📊 Только посмотреть статистику", "stats"),
            ("❌ Отмена", "cancel"),
        ])

        if action == "cancel":
            print(Fore.YELLOW + "Операция отменена")
            return

        if action == "stats":
            # Показываем детальную статистику
            runner.show_detailed_statistics()
            return

        if action == "restart":
            if not ui.confirm("Точно удалить весь прогресс?", default=False):
                print(Fore.YELLOW + "Операция отменена")
                return

            runner.db.clear_all_data()
            logger.warning("База данных очищена")
            print(Fore.GREEN + "✅ База данных очищена, загрузка новых задач...\n")

            # Загружаем новые задачи
            if not load_and_prepare_tasks(runner):
                return

            execution_mode = "new"

        elif action == "continue":
            # Загружаем только аккаунты для продолжения
            print(Fore.YELLOW + "\n📥 Загрузка аккаунтов...")
            if not runner.load_accounts():
                print(Fore.RED + "❌ Не удалось загрузить аккаунты")
                return

            print(Fore.GREEN + f"✅ Загружено аккаунтов: {len(runner.accounts)}")

            # Подтверждение продолжения
            if not ui.confirm(f"Продолжить {pending} незавершённых операций?",
                              default=True):
                print(Fore.YELLOW + "Операция отменена")
                return

            execution_mode = "continue"
    else:
        # Нет незавершенных задач - загружаем новые
        print(Fore.GREEN + "\n✅ Нет незавершенных задач в БД")
        if not load_and_prepare_tasks(runner):
            return
        execution_mode = "new"

    # Запускаем выполнение
    print(Fore.CYAN + f"\n{'='*70}")
    print(Fore.CYAN + "🚀 НАЧАЛО ВЫПОЛНЕНИЯ")
    print(Fore.CYAN + f"{'='*70}\n")

    try:
        results = asyncio.run(runner.run_all_tasks(mode=execution_mode))

        if results:
            # Сохраняем результаты
            runner.save_results()

    except KeyboardInterrupt:
        print(Fore.YELLOW + "\n⚠️  Выполнение прервано пользователем")
        print(Fore.CYAN + "💾 Прогресс сохранен в базе данных")
        print(Fore.WHITE + "Запустите модуль снова для продолжения\n")
    except Exception as e:
        print(Fore.RED + f"\n❌ Ошибка выполнения: {e}")
        logger.error(f"Ошибка выполнения: {e}")
        import traceback
        traceback.print_exc()


def load_and_prepare_tasks(runner):
    """Загружает аккаунты и задачи, показывает информацию"""
    # Загружаем аккаунты
    print(Fore.YELLOW + "📥 Загрузка аккаунтов...")
    if not runner.load_accounts():
        print(Fore.RED + "❌ Не удалось загрузить аккаунты")
        return False

    if not runner.accounts:
        print(Fore.RED + "❌ Нет аккаунтов для работы")
        print(Fore.YELLOW + "Добавьте аккаунты в data/twitter/twitters.csv")
        return False

    print(Fore.GREEN + f"✅ Загружено аккаунтов: {len(runner.accounts)}")

    # Загружаем задачи
    print(Fore.YELLOW + "📥 Загрузка задач...")
    if not runner.load_tasks():
        print(Fore.RED + "❌ Не удалось загрузить задачи")
        return False

    if not runner.tasks:
        print(Fore.RED + "❌ Нет задач для выполнения")
        print(Fore.YELLOW + "Добавьте задачи в data/twitter/twitter_task.csv")
        return False

    print(Fore.GREEN + f"✅ Загружено задач: {len(runner.tasks)}")

    # Показываем информацию о задачах
    print(Fore.CYAN + f"\n📋 Задачи для выполнения:")
    task_summary = {}
    for task in runner.tasks:
        task_type = task['type']
        if task_type not in task_summary:
            task_summary[task_type] = 0

        # Считаем операции
        if task_type in ['tweet', 'comment']:
            task_summary[task_type] += 1
        else:
            try:
                reps = int(task['value']) if task['value'] else 1
                task_summary[task_type] += max(1, reps)
            except:
                task_summary[task_type] += 1

    for task_type, count in task_summary.items():
        print(Fore.WHITE + f"  • {task_type.upper()}: {count} операций")

    # Подтверждение запуска
    total_ops = sum(task_summary.values())
    if not ui.confirm(f"Выполнить {len(runner.tasks)} задач "
                      f"({total_ops} операций) для "
                      f"{len(runner.accounts)} аккаунтов?", default=True):
        print(Fore.YELLOW + "Операция отменена")
        return False

    return True


if __name__ == "__main__":
    run_twitter_tasks()