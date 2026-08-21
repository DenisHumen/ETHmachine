import sys
from pathlib import Path

from colorama import Fore

from modules.ui import ui
from modules.ui.menu_model import BACK_KEY

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

def get_network_rpc_selection():
    """
    Функция для выбора сети и возврата RPC URLs

    Returns:
        tuple: (rpc_urls_list, network_type, clean_network) или (None, None, None) если отменено
    """
    # Импортируем из нового централизованного модуля
    from config.networks import get_mainnet_networks, get_testnet_networks, get_network_display_name

    mainnet_rpc_urls = get_mainnet_networks()
    testnet_rpc_urls = get_testnet_networks()

    network_type = ui.choose("Какой тип сети?", [
        ("🌐 Mainnet — выбрать одну сеть", "mainnet"),
        ("🔧 Testnet — выбрать одну сеть", "testnet"),
        ("🌐 Все mainnet-сети", "all_mainnet"),
        ("🔧 Все testnet-сети", "all_testnet"),
        ("⭕ Абсолютно все сети", "all_networks"),
    ])

    if network_type in (None, BACK_KEY):
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
        network = ui.choose("В какой сети работаем?", [
            (get_network_display_name(n), n) for n in network_choices
        ])

        if network in (None, BACK_KEY):
            return None, None, None

        rpc_urls = mainnet_rpc_urls if network_type == 'mainnet' else testnet_rpc_urls
        selected_rpc_urls = rpc_urls[network]

        clean_network = network.replace('🚀 ', '')

        return selected_rpc_urls, network_type, clean_network

    return None, None, None

