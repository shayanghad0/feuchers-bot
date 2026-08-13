import requests
import time
import sys
from datetime import datetime

# Initially empty – will be filled by user input
coin = ""

def get_user_input():
    """Prompt the user for the coin symbol (e.g., BTC, ETH)."""
    global coin
    if not coin:
        coin = input("Enter coin symbol (e.g., BTC): ").strip().upper()
        while not coin:
            coin = input("Coin symbol cannot be empty. Please enter coin: ").strip().upper()

# Ask for input before monitoring starts
get_user_input()

# Fixed quote currency
QUOTE_CURRENCY = "USDT"

def get_price():
    """Fetch spot price from Bybit public API (no API key required)."""
    url = "https://api.bybit.com/v5/market/tickers"
    params = {
        "category": "spot",
        "symbol": f"{coin}{QUOTE_CURRENCY}"   # e.g., BTCUSDT
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        price_str = data['result']['list'][0]['lastPrice']
        return float(price_str)
    except (requests.RequestException, KeyError, ValueError, IndexError) as e:
        print(f"[{datetime.now()}] Error fetching price: {e}")
        return None

def main():
    last_price = None
    print(f"Starting price monitor for {coin}/{QUOTE_CURRENCY} (checks every 5 seconds). Press Ctrl+C to stop.")
    while True:
        current_price = get_price()
        if current_price is not None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if last_price is None:
                print(f"[{timestamp}] {coin}/{QUOTE_CURRENCY} = {current_price:.2f} (initial)")
            else:
                diff = current_price - last_price
                diff_percent = (diff / last_price) * 100
                print(f"[{timestamp}] {coin}/{QUOTE_CURRENCY} = {current_price:.2f} "
                      f"(change: {diff:+.2f} | {diff_percent:+.4f}%)")
            last_price = current_price
        else:
            print(f"[{datetime.now()}] Skipping update due to error.")
        time.sleep(5)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user.")
        sys.exit(0)