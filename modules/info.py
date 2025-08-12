from colorama import Fore, Style, init

init(autoreset=True)

# Словарь с гайдами и ссылками
GUIDES_DICT = {
    "🗂️ Check age discord": "https://youtu.be/7lRYBa0Educ",
    # "💲 Check Wallets Balances": "https://example.com/wallet-balance-guide",
    # "🧹 Drainers": "https://example.com/drainers-guide",
    # "🔄 Transfer Wallets to Wallets": "https://example.com/transfer-guide",
    # "🐦 Check Twitter Accounts": "https://example.com/twitter-guide",
    # "🪙 Generate Wallets": "https://example.com/generate-wallets-guide",
    # "🔑 Convert Mnemonic to Private Key": "https://example.com/mnemonic-guide",
    # "🔑 Convert Private Key to Wallet Address": "https://example.com/private-key-guide",
    # "💲 OKX": "https://example.com/okx-guide",
    # "💲 Binance": "",  # Пустая ссылка для примера
    # "🗂️ password generator": "https://example.com/password-generator-guide",
    # "🗂️ Check Proxy": "https://example.com/proxy-guide",
    # "🗂️ Last Transactions": "https://example.com/last-tx-guide",
    # "💧 Somnia": "https://example.com/somnia-faucet-guide",
    # "⛽ Check Gas Price": "https://example.com/gas-price-guide"
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
    print(Fore.MAGENTA + Style.BRIGHT + "\n📖 ИНФОРМАЦИОННАЯ СИСТЕМА ETHmachine")
    print(Fore.WHITE + "Выберите что хотите посмотреть:")
    print(Fore.YELLOW + "1. Показать все доступные гайды")
    print(Fore.YELLOW + "2. Найти гайд по названию функции")
    print(Fore.YELLOW + "3. Поиск по ключевому слову")
    
    choice = input(Fore.CYAN + "\nВведите номер (1-3): ").strip()
    
    if choice == "1":
        list_all_guides()
    elif choice == "2":
        feature_name = input(Fore.CYAN + "Введите точное название функции: ").strip()
        show_guide(feature_name)
    elif choice == "3":
        search_term = input(Fore.CYAN + "Введите ключевое слово для поиска: ").strip()
        search_guide(search_term)
    else:
        print(Fore.RED + "❌ Неверный выбор!")

if __name__ == "__main__":
    # Примеры использования
    show_guide("🗂️ Check age discord")
    print("\n")
    show_guide("💲 Binance")  # Пример с пустой ссылкой
    print("\n")
    show_guide("Несуществующая функция")  # Пример с отсутствующей функцией
