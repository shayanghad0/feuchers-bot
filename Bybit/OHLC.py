import requests
import json
from datetime import datetime

# Map user-friendly intervals to Bybit API interval codes
INTERVAL_MAP = {
    "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
    "1h": "60", "2h": "120", "4h": "240", "6h": "360", "12h": "720",
    "1d": "D", "1w": "W", "1M": "M",
    # Also accept raw numeric codes directly
    "1": "1", "3": "3", "5": "5", "15": "15", "30": "30",
    "60": "60", "120": "120", "240": "240", "360": "360", "720": "720",
    "D": "D", "W": "W", "M": "M"
}

def get_ohlc(interval: str, limit: int):
    """
    Fetch BTC/USDT candlestick data from Bybit public API.

    Args:
        interval (str): Timeframe (user-friendly, e.g., '1m', '1h', or API code like '1', '60').
        limit (int): Number of candles (max 1000).

    Returns:
        list: List of OHLCV dicts with keys: timestamp, open, high, low, close, volume.
    """
    # Map the interval to the correct API code
    api_interval = INTERVAL_MAP.get(interval)
    if api_interval is None:
        raise ValueError(f"Unknown interval: '{interval}'. "
                         f"Supported: {list(INTERVAL_MAP.keys())}")

    url = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "spot",
        "symbol": "BTCUSDT",
        "interval": api_interval,
        "limit": limit
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data['retCode'] != 0:
            raise Exception(f"API error: {data['retMsg']}")

        candles = data['result']['list']
        ohlc_list = []
        for candle in candles:
            ts_ms = int(candle[0])
            dt = datetime.fromtimestamp(ts_ms / 1000.0)
            ohlc_list.append({
                "timestamp": dt.isoformat(),
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5])
            })
        return ohlc_list
    except (requests.RequestException, KeyError, ValueError, IndexError) as e:
        print(f"Error fetching OHLC data: {e}")
        return None

def main():
    print("Bybit BTC/USDT OHLC Data Fetcher")
    print("Supported timeframes: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d, 1w, 1M")
    print("(You can also enter the raw API codes: 1, 3, 5, 15, 30, 60, 120, 240, 360, 720, D, W, M)")

    interval = input("Enter timeframe: ").strip()

    try:
        limit = int(input("Enter number of candles (max 1000): ").strip())
        if limit < 1 or limit > 1000:
            print("Limit must be between 1 and 1000. Using 100.")
            limit = 100
    except ValueError:
        print("Invalid number. Using default 100.")
        limit = 100

    print(f"\nFetching {limit} candles for interval '{interval}'...")
    data = get_ohlc(interval, limit)

    if data is None:
        print("Failed to retrieve data. Exiting.")
        return

    # Save to JSON file
    filename = f"btc_ohlc_{interval}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"Data saved to {filename}")
    print(f"First entry: {data[0]}")
    print(f"Last entry: {data[-1]}")

if __name__ == "__main__":
    main()