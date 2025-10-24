"""
Модуль выполнения задач Twitter
Интеграция с существующим Twitter Task модулем
"""

import os
import csv
import asyncio
from datetime import datetime
from pathlib import Path
from loguru import logger
from colorama import Fore
import questionary
from questionary import Choice

# Добавляем путь к корневой директории проекта
import sys
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.join(current_dir, '..', '..')
sys.path.append(project_root)

# Импортируем настройки из config
from config.config import (
    TWITTER_TASK_SSL_VERIFICATION,
    TWITTER_TASK_DELAY_BETWEEN_TASKS,
    TWITTER_TASK_DELAY_BETWEEN_ACCOUNTS
)

# Импортируем Twitter класс из существующего модуля
from .tiwtter_task import Twitter

class Config:
    """Конфигурация для Twitter модуля"""
    SSL_VERIFICATION = TWITTER_TASK_SSL_VERIFICATION
    DELAY_BETWEEN_TASKS = TWITTER_TASK_DELAY_BETWEEN_TASKS
    DELAY_BETWEEN_ACCOUNTS = TWITTER_TASK_DELAY_BETWEEN_ACCOUNTS


class TwitterTaskRunner:
    """Класс для выполнения Twitter задач"""
    
    def __init__(self):
        self.config = Config()
        self.accounts = []
        self.tasks = []
        self.results = []
    
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
                result = await twitter_client.comment(tweet_id, comment_text)
                return result, "Комментарий опубликован" if result else "Ошибка публикации комментария"
            
            else:
                return False, f"Неизвестный тип задачи: {task_type}"
                
        except Exception as e:
            return False, f"Ошибка выполнения задачи: {e}"
    
    async def run_all_tasks(self):
        """
        Выполняет задачи распределяя их по аккаунтам.
        Каждая задача выполняется уникальным аккаунтом (с учетом повторений).
        """
        if not self.accounts:
            logger.error("Нет загруженных аккаунтов")
            return
        
        if not self.tasks:
            logger.error("Нет загруженных задач")
            return
        
        # Подсчитываем общее количество операций
        total_operations = 0
        for task in self.tasks:
            if task['type'] in ['tweet', 'comment']:
                total_operations += 1
            else:
                try:
                    repetitions = int(task['value']) if task['value'] else 1
                    total_operations += max(1, repetitions)
                except (ValueError, TypeError):
                    total_operations += 1
        
        print(Fore.CYAN + f"\n📊 Планирование выполнения:")
        print(Fore.WHITE + f"  • Всего задач: {len(self.tasks)}")
        print(Fore.WHITE + f"  • Всего операций: {total_operations}")
        print(Fore.WHITE + f"  • Доступно аккаунтов: {len(self.accounts)}")
        
        if total_operations > len(self.accounts):
            print(Fore.YELLOW + f"  ⚠️  Операций больше чем аккаунтов - некоторые аккаунты будут использованы повторно")
        
        logger.info(f"Начало выполнения {len(self.tasks)} задач ({total_operations} операций)")
        
        all_results = []
        account_index = 0  # Индекс текущего аккаунта
        
        # Проходим по каждой задаче
        for task_num, task in enumerate(self.tasks, 1):
            task_type = task['type']
            task_link = task['link']
            task_value = task['value']
            
            # Определяем количество повторений
            if task_type in ['tweet', 'comment']:
                repetitions = 1
            else:
                try:
                    repetitions = int(task_value) if task_value else 1
                    repetitions = max(1, repetitions)
                except (ValueError, TypeError):
                    repetitions = 1
            
            print(Fore.CYAN + f"\n{'='*70}")
            print(Fore.CYAN + f"📋 ЗАДАЧА {task_num}/{len(self.tasks)}: {task_type.upper()}")
            print(Fore.WHITE + f"   Ссылка: {task_link or 'Н/Д'}")
            if task_value:
                print(Fore.WHITE + f"   Значение: {task_value}")
            print(Fore.WHITE + f"   Повторений: {repetitions}")
            print(Fore.CYAN + f"{'='*70}\n")
            
            # Выполняем задачу нужное количество раз
            for rep in range(repetitions):
                # Проверяем что есть аккаунты
                if account_index >= len(self.accounts):
                    account_index = 0  # Начинаем сначала если аккаунты закончились
                
                account = self.accounts[account_index]
                account_display_index = account_index + 1
                
                print(Fore.GREEN + f"┌─ Повтор {rep + 1}/{repetitions}")
                print(Fore.GREEN + f"└─ Аккаунт: {account['nickname']} (#{account_display_index})")
                
                # Выполняем задачу для этого аккаунта
                result = await self.execute_task_for_account(
                    account, 
                    task, 
                    account_display_index,
                    rep + 1,
                    repetitions
                )
                
                all_results.append(result)
                
                # Переходим к следующему аккаунту
                account_index += 1
                
                # Задержка между операциями (кроме последней)
                if not (task_num == len(self.tasks) and rep == repetitions - 1):
                    await asyncio.sleep(self.config.DELAY_BETWEEN_TASKS)
        
        self.results = all_results
        
        print(Fore.CYAN + f"\n{'='*70}")
        logger.success(f"✅ Все задачи завершены! Выполнено {len(all_results)} операций")
        print(Fore.CYAN + f"{'='*70}\n")
        
        return all_results
    
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
        """Сохраняет результаты в файл с датой и временем"""
        if not self.results:
            logger.warning("Нет результатов для сохранения")
            return
        
        # Создаем папку для результатов если её нет
        results_dir = Path('result/twitter')
        results_dir.mkdir(parents=True, exist_ok=True)
        
        # Генерируем имя файла с датой и временем
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        results_file = results_dir / f'twitter_tasks_results_{timestamp}.csv'
        
        try:
            with open(results_file, 'w', encoding='utf-8', newline='') as f:
                if self.results:
                    fieldnames = self.results[0].keys()
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(self.results)
            
            logger.success(f"Результаты сохранены в: {results_file}")
            
            # Показываем статистику
            success_count = sum(1 for r in self.results if r['status'] == 'success')
            failed_count = len(self.results) - success_count
            
            # Группируем по типам задач
            task_stats = {}
            for r in self.results:
                task_type = r['task_type']
                if task_type not in task_stats:
                    task_stats[task_type] = {'success': 0, 'failed': 0}
                if r['status'] == 'success':
                    task_stats[task_type]['success'] += 1
                else:
                    task_stats[task_type]['failed'] += 1
            
            print(Fore.CYAN + f"\n{'='*70}")
            print(Fore.CYAN + f"📊 ИТОГОВАЯ СТАТИСТИКА")
            print(Fore.CYAN + f"{'='*70}")
            print(Fore.WHITE + f"\n  Всего операций: {len(self.results)}")
            print(Fore.GREEN + f"  ✅ Успешно: {success_count}")
            if failed_count > 0:
                print(Fore.RED + f"  ❌ Ошибки: {failed_count}")
            
            print(Fore.CYAN + f"\n  По типам задач:")
            for task_type, stats in task_stats.items():
                total = stats['success'] + stats['failed']
                print(Fore.WHITE + f"    • {task_type.upper():10} - {stats['success']}/{total} успешно")
            
            print(Fore.CYAN + f"\n  📁 Результаты: {results_file.name}")
            print(Fore.CYAN + f"{'='*70}\n")
            
        except Exception as e:
            logger.error(f"Ошибка сохранения результатов: {e}")


def run_twitter_tasks():
    """Главная функция для запуска Twitter задач"""
    print(Fore.CYAN + "\n🐦 Twitter Task Runner")
    print("=" * 50)
    
    runner = TwitterTaskRunner()
    
    # Загружаем аккаунты
    print(Fore.YELLOW + "📥 Загрузка аккаунтов...")
    if not runner.load_accounts():
        print(Fore.RED + "❌ Не удалось загрузить аккаунты")
        return
    
    if not runner.accounts:
        print(Fore.RED + "❌ Нет аккаунтов для работы")
        print(Fore.YELLOW + "Добавьте аккаунты в data/twitter/twitters.csv")
        return
    
    print(Fore.GREEN + f"✅ Загружено аккаунтов: {len(runner.accounts)}")
    
    # Загружаем задачи
    print(Fore.YELLOW + "📥 Загрузка задач...")
    if not runner.load_tasks():
        print(Fore.RED + "❌ Не удалось загрузить задачи")
        return
    
    if not runner.tasks:
        print(Fore.RED + "❌ Нет задач для выполнения")
        print(Fore.YELLOW + "Добавьте задачи в data/twitter/twitter_task.csv")
        return
    
    print(Fore.GREEN + f"✅ Загружено задач: {len(runner.tasks)}")
    
    # Показываем информацию о задачах
    print(Fore.CYAN + f"\n📋 Задачи для выполнения:")
    for i, task in enumerate(runner.tasks, 1):
        print(Fore.WHITE + f"  {i}. {task['type'].upper()} - {task['link']}")
        if task['value']:
            print(Fore.WHITE + f"     Значение: {task['value']}")
    
    # Подтверждение запуска
    confirm = questionary.confirm(
        f"Выполнить {len(runner.tasks)} задач для {len(runner.accounts)} аккаунтов?",
        default=False
    ).ask()
    
    if not confirm:
        print(Fore.YELLOW + "Операция отменена")
        return
    
    # Запускаем задачи
    print(Fore.GREEN + "\n🚀 Запуск выполнения задач...")
    try:
        asyncio.run(runner.run_all_tasks())
        
        # Сохраняем результаты
        runner.save_results()
        
    except KeyboardInterrupt:
        print(Fore.YELLOW + "\n⚠️ Выполнение прервано пользователем")
        if runner.results:
            runner.save_results()
    except Exception as e:
        print(Fore.RED + f"\n❌ Критическая ошибка: {e}")
        if runner.results:
            runner.save_results()


if __name__ == "__main__":
    run_twitter_tasks()