import sys
from pathlib import Path
from questionary import Choice, select
from colorama import Fore

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

def get_network_rpc_selection():
    """
    Функция для выбора сети и возврата RPC URLs
    
    Returns:
        tuple: (rpc_urls_list, network_type, clean_network) или (None, None, None) если отменено
    """
    # Импортируем из нового централизованного модуля
    from config.networks import get_mainnet_networks, get_testnet_networks
    
    mainnet_rpc_urls = get_mainnet_networks()
    testnet_rpc_urls = get_testnet_networks()
    
    network_type = select(
        "Select network type:",
        choices=[
            Choice('🌐 Mainnet', 'mainnet'),
            Choice('🔧 Testnet', 'testnet'),
            Choice('🌍 Проверить ВСЕ Mainnet сети', 'all_mainnet'),
            Choice('🔧 Проверить ВСЕ Testnet сети', 'all_testnet'),
            Choice('🌎 Проверить АБСОЛЮТНО ВСЕ сети', 'all_networks'),
            Choice('🔙 Back', 'back')
        ],
        qmark='🛠️',
        pointer='👉'
    ).ask()

    if network_type == 'back':
        return None, None, None
    
    if network_type == 'all_mainnet':
        return 'ALL_NETWORKS', mainnet_rpc_urls, 'All Mainnet Networks'
    
    if network_type == 'all_testnet':
        return 'ALL_NETWORKS', testnet_rpc_urls, 'All Testnet Networks'
    
    if network_type == 'all_networks':
        all_networks = {}
        all_networks.update(mainnet_rpc_urls)
        all_networks.update(testnet_rpc_urls)
        return 'ALL_NETWORKS', all_networks, 'All Networks'

    if network_type in ['mainnet', 'testnet']:
        network_choices = list(mainnet_rpc_urls.keys()) if network_type == 'mainnet' else list(testnet_rpc_urls.keys())
        network = select(
            "Which network do you want to use?",
            choices=[Choice(n, n) for n in network_choices] + [Choice('🔙 Back', 'back')],
            qmark='🛠️',
            pointer='👉'
        ).ask()

        if network == 'back':
            return None, None, None

        rpc_urls = mainnet_rpc_urls if network_type == 'mainnet' else testnet_rpc_urls
        selected_rpc_urls = rpc_urls[network]
        
        clean_network = network.replace('🚀 ', '')
        
        return selected_rpc_urls, network_type, clean_network
    
    return None, None, None

def get_token_selection_for_network(clean_network):
    """
    Функция для выбора токена для указанной сети
    
    Args:
        clean_network: Название сети без эмодзи
        
    Returns:
        tuple: (token_symbol, token_address) или ('ALL_TOKENS', network_tokens_dict) или (None, None) если отменено
    """
    try:
        import config.token_address_erc20 as token_addresses
        
        network_var_name = clean_network.lower().replace(' ', '_').replace('(', '').replace(')', '').replace('native_token_mon', '')
        
        possible_names = [
            network_var_name,
            network_var_name.replace('testnet', '').strip('_'),
            network_var_name.replace('_testnet', ''),
            network_var_name.replace('mainnet', '').strip('_'),
            network_var_name.replace('_mainnet', ''),
        ]
        
        network_tokens = None
        found_var_name = None
        
        for name in possible_names:
            if hasattr(token_addresses, name):
                network_tokens = getattr(token_addresses, name)
                found_var_name = name
                break
        
        if not network_tokens:
            print(Fore.RED + f"\n❌ Токены для сети '{clean_network}' не найдены!")
            print(Fore.YELLOW + f"💡 Добавьте словарь токенов в config/token_address_erc20.py")
            print(Fore.CYAN + f"   Пример: {network_var_name} = {{'usdc': '0x...', 'usdt': '0x...'}}")
            return None, None
        
        if not isinstance(network_tokens, dict) or not network_tokens:
            print(Fore.RED + f"\n❌ Словарь токенов для сети '{clean_network}' пуст или неверного формата!")
            print(Fore.YELLOW + f"💡 Добавьте токены в config/token_address_erc20.py -> {found_var_name}")
            return None, None
        
        token_choices = []
        
        token_choices.append(Choice('🔍 Проверить ВСЕ токены сразу', 'ALL_TOKENS'))
        
        for symbol, address in network_tokens.items():
            display_text = f'🪙 {symbol.upper()} ({address[:10]}...{address[-6:]})'
            token_choices.append(Choice(display_text, symbol))
        
        token_choices.append(Choice('🔙 Back', 'back'))
        
        selected_token = select(
            f"Select token for {clean_network}:",
            choices=token_choices,
            qmark='🛠️',
            pointer='👉'
        ).ask()
        
        if selected_token == 'back':
            return None, None
        
        if selected_token == 'ALL_TOKENS':
            return 'ALL_TOKENS', network_tokens
        
        token_address = network_tokens[selected_token]
        return selected_token, token_address
        
    except ImportError:
        print(Fore.RED + "\n❌ Не удалось импортировать config.token_address_erc20")
        print(Fore.YELLOW + "💡 Убедитесь, что файл config/token_address_erc20.py существует")
        return None, None
    except Exception as e:
        print(Fore.RED + f"\n❌ Ошибка при получении токенов: {e}")
        return None, None
