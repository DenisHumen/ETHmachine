# check_balance_eth

### Donation ``` TRC20 - TRWzXZE16bgJg3eHa9n8q4ioZjMgKHwF9a ```
<img src="usdt.jpg" alt="Donation" width="150"/>

This repository contains scripts to check Ethereum wallet balances using different methods and APIs. Below is a description of each script and how to run them.

## General Usage

1. Ensure you have Python installed on your system.
2. Install the required dependencies using:
   ```sh
   pip install -r requirements.txt
   ```
3. Prepare a file named `walletss.txt` containing the wallet addresses you want to check, one per line.

## Scripts

### sum_eth.py

This script sums up the balances from a file and prints the total balance.

#### Usage

1. Ensure you have a file named `wallet_balances.txt` with the balances.
2. Run the script:
   ```sh
   python sum_eth.py
   ```

### sepolia.py

This script fetches wallet balances from the Sepolia testnet using the Infura API and writes them to a file.

#### Usage

1. Run the script:
   ```sh
   python sepolia.py
   ```

### L1.py

This script fetches wallet balances from the Ethereum mainnet using the Web3 library and writes them to a file.

#### Usage

1. Run the script:
   ```sh
   python L1.py
   ```

### base.py

This script fetches wallet balances from the Base network using the Web3 library and writes them to a file.

#### Usage

1. Run the script:
   ```sh
   python base.py
   ```