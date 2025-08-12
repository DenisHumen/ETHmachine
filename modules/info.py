from colorama import Fore, Style, init
from questionary import Choice, select

init(autoreset=True)

# Словарь с гайдами и ссылками
GUIDES_DICT = {
    "🗂️ Check age discord": "https://youtu.be/7lRYBa0Educ",
    "💲 Check Wallets Balances": "",
    "🧹 Drainers": "",
    "🔄 Transfer Wallets to Wallets": "",
    "🐦 Check Twitter Accounts": "",
    "🪙 Generate Wallets": "",
    "🔑 Convert Mnemonic to Private Key": "",
    "🔑 Convert Private Key to Wallet Address": "",
    "💲 OKX": "",
    "💲 Binance": "",
    "💲 Bitget": "",
    "🗂️ password generator": "",
    "🗂️ Check Proxy": "",
    "🗂️ Last Transactions": "",
    "💧 Somnia": "",
    "⛽ Check Gas Price": "",
    "💲 Check Token Balances": "",
    "🚰 Faucets": "",
    "💲 SOL": "",
    "💲 ETH": "",
}

def show_guide(feature_name):
    """
    Показывает гайд для указанной функции
    
    Args:
        feature_name (str): Название функции для поиска гайда
    """
    print(Fore.CYAN + "=" * 60)
    print(Fore.CYAN + f"📖 ГАЙД ДЛЯ: {Style.BRIGHT}{feature_name}")
    print(Fore.CYAN + "=" * 60)
    
    # Ищем точное совпадение
    guide_url = GUIDES_DICT.get(feature_name)
    
    if guide_url and guide_url.strip():
        print(Fore.GREEN + "✅ Гайд найден!")
        print(Fore.YELLOW + f"🔗 Ссылка: {Style.BRIGHT}{guide_url}")
        print(Fore.WHITE + "\n📝 Описание:")
        print(Fore.WHITE + f"   Подробная инструкция по использованию функции '{feature_name}'")
        print(Fore.BLUE + "\n💡 Совет: Скопируйте ссылку и откройте в браузере")
    else:
        print(Fore.RED + "❌ Гайд еще не написан")
        print(Fore.YELLOW + f"📝 Функция: {feature_name}")
        print(Fore.WHITE + "⏳ Гайд находится в разработке и будет добавлен в ближайшее время")
        print(Fore.BLUE + "\n💬 Есть вопросы? Обращайтесь в Telegram: https://t.me/DenisHumen")
    
    print(Fore.CYAN + "=" * 60)

def list_all_guides():
    """
    Показывает список всех доступных гайдов
    """
    print(Fore.MAGENTA + "=" * 70)
    print(Fore.MAGENTA + f"📚 СПИСОК ВСЕХ ГАЙДОВ")
    print(Fore.MAGENTA + "=" * 70)
    
    available_guides = []
    unavailable_guides = []
    
    for feature, url in GUIDES_DICT.items():
        if url and url.strip():
            available_guides.append((feature, url))
        else:
            unavailable_guides.append(feature)
    
    if available_guides:
        print(Fore.GREEN + f"✅ ДОСТУПНЫЕ ГАЙДЫ ({len(available_guides)}):")
        for i, (feature, url) in enumerate(available_guides, 1):
            print(Fore.WHITE + f"   {i:2d}. {feature}")
            print(Fore.YELLOW + f"       🔗 {url}")
    
    if unavailable_guides:
        print(Fore.RED + f"\n❌ ГАЙДЫ В РАЗРАБОТКЕ ({len(unavailable_guides)}):")
        for i, feature in enumerate(unavailable_guides, 1):
            print(Fore.WHITE + f"   {i:2d}. {feature}")
    
    print(Fore.MAGENTA + "=" * 70)

def search_guide(search_term):
    """
    Ищет гайды по ключевому слову
    
    Args:
        search_term (str): Термин для поиска
    """
    search_term = search_term.lower()
    found_guides = []
    
    for feature, url in GUIDES_DICT.items():
        if search_term in feature.lower():
            found_guides.append((feature, url))
    
    print(Fore.CYAN + "=" * 60)
    print(Fore.CYAN + f"🔍 ПОИСК ПО ЗАПРОСУ: {Style.BRIGHT}'{search_term}'")
    print(Fore.CYAN + "=" * 60)
    
    if found_guides:
        print(Fore.GREEN + f"✅ Найдено {len(found_guides)} совпадений:")
        for i, (feature, url) in enumerate(found_guides, 1):
            status = "✅ Доступен" if url and url.strip() else "❌ В разработке"
            color = Fore.GREEN if url and url.strip() else Fore.RED
            print(color + f"   {i}. {feature} - {status}")
            if url and url.strip():
                print(Fore.YELLOW + f"      🔗 {url}")
    else:
        print(Fore.RED + "❌ Ничего не найдено")
        print(Fore.YELLOW + "💡 Попробуйте другой поисковый запрос")
    
    print(Fore.CYAN + "=" * 60)

def info():
    """
    Основная функция информации - показывает меню выбора
    """
    while True:
        print(Fore.MAGENTA + Style.BRIGHT + "\n📖 ИНФОРМАЦИОННАЯ СИСТЕМА ETHmachine")
        
        action = select(
            "Выберите что хотите посмотреть:",
            choices=[
                Choice('📚 Показать все доступные гайды', 'list_all'),
                Choice('🔎 Поиск по ключевому слову', 'search'),
                Choice('🔙 Назад', 'back')
            ],
            qmark='📖',
            pointer='👉'
        ).ask()
        
        if action == 'list_all':
            list_all_guides()
            input(Fore.CYAN + "\nНажмите Enter для продолжения...")
        elif action == 'search':
            search_term = input(Fore.CYAN + "Введите ключевое слово для поиска: ").strip()
            search_guide(search_term)
            input(Fore.CYAN + "\nНажмите Enter для продолжения...")
        elif action == 'back':
            break

if __name__ == "__main__":
    # Примеры использования
    info()
