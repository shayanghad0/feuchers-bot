import requests
import json
import time
from datetime import datetime

# Map user-friendly intervals to Nobitex resolution codes
INTERVAL_MAP = {
    "1m": "1", "5m": "5", "15m": "15", "30m": "30",
    "1h": "60", "3h": "180", "4h": "240", "6h": "360", "12h": "720",
    "1d": "D", "2d": "2D", "3d": "3D",
    # Allow direct codes as well
    "1": "1", "5": "5", "15": "15", "30": "30",
    "60": "60", "180": "180", "240": "240", "360": "360", "720": "720",
    "D": "D", "2D": "2D", "3D": "3D"
}

# Map resolution to seconds for time range calculation
RESOLUTION_SECONDS = {
    "1": 60, "5": 300, "15": 900, "30": 1800,
    "60": 3600, "180": 10800, "240": 14400, "360": 21600, "720": 43200,
    "D": 86400, "2D": 172800, "3D": 259200
}

def get_ohlc(interval: str, limit: int):
    """
    Fetch BTC/USDT OHLCV data from Nobitex public API.

    Args:
        interval (str): Timeframe (user-friendly, e.g., '1m', '1h', or API code like '1', '60').
        limit (int): Number of candles (max 500 per page, but this function handles pagination).

    Returns:
        list: List of OHLCV dicts with keys: timestamp, open, high, low, close, volume.
              Timestamp is ISO-8601 string.
    """
    api_interval = INTERVAL_MAP.get(interval)
    if api_interval is None:
        raise ValueError(f"Unknown interval: '{interval}'. "
                         f"Supported: {list(INTERVAL_MAP.keys())}")

    seconds_per = RESOLUTION_SECONDS.get(api_interval)
    if seconds_per is None:
        raise ValueError(f"Invalid resolution: {api_interval}")

    # Calculate a time range wide enough to have at least `limit` candles
    # Multiply by 2 to be safe (in case of gaps)
    approx_seconds = seconds_per * limit * 2
    to_timestamp = int(time.time())
    from_timestamp = to_timestamp - approx_seconds

    base_url = "https://apiv2.nobitex.ir/market/udf/history"
    page = 1
    all_candles = []  # will store tuples (timestamp, open, high, low, close, volume)

    while True:
        params = {
            "symbol": "BTCUSDT",
            "resolution": api_interval,
            "from": from_timestamp,
            "to": to_timestamp,
            "page": page
        }
        try:
            resp = requests.get(base_url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            print(f"Request error: {e}")
            return None

        status = data.get("s")
        if status == "error":
            raise Exception(f"API error: {data.get('errmsg', 'Unknown error')}")
        elif status == "no_data":
            break  # no more data

        t = data.get("t", [])
        o = data.get("o", [])
        h = data.get("h", [])
        l = data.get("l", [])
        c = data.get("c", [])
        v = data.get("v", [])

        if not t:
            break

        # Combine into list of tuples
        for i in range(len(t)):
            all_candles.append((
                int(t[i]),          # Unix timestamp (seconds)
                float(o[i]),
                float(h[i]),
                float(l[i]),
                float(c[i]),
                float(v[i])
            ))

        # If we have enough candles or this page had fewer than 500, we are done
        if len(all_candles) >= limit or len(t) < 500:
            break

        page += 1

    # If we have more than needed, keep only the most recent ones
    if len(all_candles) > limit:
        all_candles = all_candles[-limit:]

    # Convert to list of dicts with ISO timestamp
    ohlc_list = []
    for ts, open_price, high_price, low_price, close_price, vol in all_candles:
        dt = datetime.fromtimestamp(ts)
        ohlc_list.append({
            "timestamp": dt.isoformat(),
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": vol
        })

    return ohlc_list

def main():
    print("Nobitex BTC/USDT OHLC Data Fetcher")
    print("Supported timeframes: 1m, 5m, 15m, 30m, 1h, 3h, 4h, 6h, 12h, 1d, 2d, 3d")
    print("(You can also enter the raw API codes: 1, 5, 15, 30, 60, 180, 240, 360, 720, D, 2D, 3D)")

    interval = input("Enter timeframe: ").strip()

    try:
        limit = int(input("Enter number of candles: ").strip())
        if limit < 1:
            print("Limit must be at least 1. Using 1.")
            limit = 1
        # No upper limit enforced; pagination handles it
    except ValueError:
        print("Invalid number. Using default 100.")
        limit = 100

    print(f"\nFetching {limit} candles for interval '{interval}'...")
    data = get_ohlc(interval, limit)

    if data is None:
        print("Failed to retrieve data. Exiting.")
        return

    if not data:
        print("No data returned.")
        return

    # Save to JSON file
    filename = f"btc_ohlc_{interval}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Data saved to {filename}")
    print(f"Number of candles fetched: {len(data)}")
    print(f"First entry: {data[0]}")
    print(f"Last entry: {data[-1]}")

if __name__ == "__main__":
    main()