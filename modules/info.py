from colorama import Fore, Style, init
from questionary import Choice, select

init(autoreset=True)

GUIDES_DICT = {
    "🗂️ Check age discord": "https://youtu.be/7lRYBa0Educ",
    "🏦 CEX >>💲 OKX >> 💲 Withdraw from OKX": "https://youtu.be/iVE2fJgTACQ",
    "🏦 CEX >>💲 OKX >> 💲 Subaccount collector OKX": "",
    
    "🔄 Auto Backup": "",
    "🔍 Check Proxy": "",
    "⛽ Get Gas Price": "",
    "🔔 Notifications": "",
    "🔑 Password Generator": "",
    
    "🏦 CEX >>💲 Binance >> 👥 SubAccount": "",
    "🏦 CEX >>💲 Binance >> 💲 Withdraw from Binance": "",
    "🏦 CEX >>💲 Bitget >> 👥 SubAccount": "",
    "🏦 CEX >>💲 Bitget >> 💲 Withdraw from Bitget": "",
    "🏦 CEX >>💲 OKX >> 📈 Spot Trade": "",
    
    "⚡ ETH >> 🔪 Collectors": "",
    "⚡ ETH >> 💰 Get Balances": "",
    "⚡ ETH >> 🪙 Get Token Balance": "",
    "⚡ ETH >> 📋 Last Transaction": "",
    "⚡ ETH >> 🔐 Mnemonic to Private Key": "",
    "⚡ ETH >> ✨ Nice Address Generator": "",
    "⚡ ETH >> 🗝️ Private Key to Wallet Address": "",
    "⚡ ETH >> 👝 Wallet Generator": "",
    "⚡ ETH >> 🌐 RPC Return Module": "",
    "⚡ ETH >> 💸 Transfer ERC20 Tokens": "",
    "⚡ ETH >> 💱 Transfer Wallets to Wallets": "https://youtu.be/zZV_FoEUPiw",
    
    "☀️ SOL >> 🔐 Mnemonic to Private Key": "",
    "☀️ SOL >> ✨ Nice Address Generator": "",
    "☀️ SOL >> 👝 Wallet Generator": "",
    
    "🗂️ Discord >> 📅 Check Age": "",
    
    "📧 Email >> 📬 IMAP Checker": "",
    
    "🐙 GitHub >> 🔄 Check Version": "",
    
    "🌐 Proxy >> ✅ Proxy Check": "",
    
    "🔗 Relay >> 🌉 Relay Link": "",
    
    "🐦 Twitter >> ✅ Check": "",

    "📊 Project Stats >> Neura": "https://youtu.be/SsuiGb8Rz0Q",
}

MODULES_IN_DEVELOPMENT = {
    "☀️ SOL >> 🪙 Get Balances": "В разработке",
    "☀️ SOL >> 🪙 Get Token Balances": "В разработке",
    
    "📊 Project Stats": "Модуль отключен в main.py, папка stats_modules пуста",
}

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
    
    if MODULES_IN_DEVELOPMENT:
        print(Fore.CYAN + f"\n🚧 МОДУЛИ В РАЗРАБОТКЕ ({len(MODULES_IN_DEVELOPMENT)}):")
        for i, (feature, reason) in enumerate(MODULES_IN_DEVELOPMENT.items(), 1):
            print(Fore.WHITE + f"   {i:2d}. {feature}")
            print(Fore.YELLOW + f"       📝 {reason}")
    
    print(Fore.MAGENTA + "=" * 70)

def search_guide(search_term):
    """
    Ищет гайды по ключевому слову
    
    Args:
        search_term (str): Термин для поиска
    """
    search_term = search_term.lower()
    found_guides = []
    found_dev_modules = []
    
    for feature, url in GUIDES_DICT.items():
        if search_term in feature.lower():
            found_guides.append((feature, url))
    
    for feature, reason in MODULES_IN_DEVELOPMENT.items():
        if search_term in feature.lower():
            found_dev_modules.append((feature, reason))
    
    print(Fore.CYAN + "=" * 60)
    print(Fore.CYAN + f"🔍 ПОИСК ПО ЗАПРОСУ: {Style.BRIGHT}'{search_term}'")
    print(Fore.CYAN + "=" * 60)
    
    total_found = len(found_guides) + len(found_dev_modules)
    
    if total_found > 0:
        print(Fore.GREEN + f"✅ Найдено {total_found} совпадений:")
        
        for i, (feature, url) in enumerate(found_guides, 1):
            status = "✅ Доступен" if url and url.strip() else "❌ В разработке"
            color = Fore.GREEN if url and url.strip() else Fore.RED
            print(color + f"   {i}. {feature} - {status}")
            if url and url.strip():
                print(Fore.YELLOW + f"      🔗 {url}")
        
        start_num = len(found_guides) + 1
        for i, (feature, reason) in enumerate(found_dev_modules, start_num):
            print(Fore.CYAN + f"   {i}. {feature} - 🚧 Модуль в разработке")
            print(Fore.YELLOW + f"      📝 {reason}")
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
