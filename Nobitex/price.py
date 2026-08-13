import requests
import time
import sys

# Initially empty – will be filled by user input if not provided
coin = "BTC"
currency = "USDT"

def get_user_input():
    """Prompt the user for coin and currency symbols."""
    global coin, currency
    if not coin:
        coin = input("Enter coin symbol (e.g., BTC): ").strip().upper()
        while not coin:
            coin = input("Coin symbol cannot be empty. Please enter coin: ").strip().upper()
    if not currency:
        currency = input("Enter currency symbol (e.g., USDT or IRT): ").strip().upper()
        while not currency:
            currency = input("Currency symbol cannot be empty. Please enter currency: ").strip().upper()

# Ask for input before building the URL
get_user_input()

URL = f"https://apiv2.nobitex.ir/v3/orderbook/{coin}{currency}"

def get_last_trade_price():
    """
    Fetch the orderbook and return the last trade price as a float.
    Raises an exception on failure.
    """
    try:
        response = requests.get(URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "ok":
            raise ValueError("API returned status not 'ok'")
        price_str = data.get("lastTradePrice")
        if price_str is None:
            raise ValueError("'lastTradePrice' not found in response")
        return float(price_str)
    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
        raise
    except (KeyError, ValueError, TypeError) as e:
        print(f"Data parsing error: {e}")
        raise

def main():
    previous_price = None
    print(f"Starting price monitor for {coin}/{currency} (Ctrl+C to stop)...")
    while True:
        try:
            current_price = get_last_trade_price()
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

            formatted_price = f"{current_price:,.2f}"

            if previous_price is None:
                print(f"[{timestamp}] First price: {formatted_price} {currency}")
            else:
                diff = current_price - previous_price
                sign = "+" if diff > 0 else ""
                formatted_diff = f"{sign}{diff:,.2f}"
                print(f"[{timestamp}] Price: {formatted_price} {currency}  |  Change: {formatted_diff} {currency}")

            previous_price = current_price
        except Exception as e:
            print(f"Error occurred: {e}. Retrying in 5 seconds...")

        time.sleep(5)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user.")
        sys.exit(0)