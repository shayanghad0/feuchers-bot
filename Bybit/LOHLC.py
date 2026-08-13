import requests
import time
from datetime import datetime, timedelta, timezone
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich import box

# --- Configuration ---
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
TIMEOUT = 10

INTERVAL_MAP = {
    '1m': '1', '3m': '3', '5m': '5', '15m': '15', '30m': '30',
    '1h': '60', '2h': '120', '4h': '240', '6h': '360', '12h': '720',
    '1d': 'D', '1w': 'W', '1M': 'M'
}
INTERVAL_SECONDS = {
    '1m': 60, '3m': 180, '5m': 300, '15m': 900, '30m': 1800,
    '1h': 3600, '2h': 7200, '4h': 14400, '6h': 21600, '12h': 43200,
    '1d': 86400, '1w': 604800, '1M': 2592000
}
KEEP_COUNT = 30
CHART_HEIGHT = 15

console = Console()

def get_current_price():
    url = "https://api.bybit.com/v5/market/tickers"
    params = {"category": "spot", "symbol": "BTCUSDT"}
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return float(data['result']['list'][0]['lastPrice'])
    except Exception as e:
        console.print(f"[red]Error fetching price: {e}[/red]")
        return None

def fetch_completed_candles(interval_code, limit):
    url = "https://api.bybit.com/v5/market/kline"
    params = {"category": "spot", "symbol": "BTCUSDT", "interval": interval_code, "limit": limit}
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if data['retCode'] != 0:
            raise Exception(f"API error: {data['retMsg']}")
        raw = data['result']['list'][::-1]
        candles = []
        for c in raw:
            ts = int(c[0]) / 1000.0
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            candles.append({
                'start_time': dt,
                'open': float(c[1]),
                'high': float(c[2]),
                'low': float(c[3]),
                'close': float(c[4]),
                'volume': float(c[5])
            })
        return candles
    except Exception as e:
        console.print(f"[red]Error fetching candles: {e}[/red]")
        return None

def create_current_candle(start_time, open_price, current_price):
    return {
        'start_time': start_time,
        'open': open_price,
        'high': current_price,
        'low': current_price,
        'close': current_price,
        'volume': 0.0
    }

def update_candle(candle, price):
    if price > candle['high']:
        candle['high'] = price
    if price < candle['low']:
        candle['low'] = price
    candle['close'] = price

def render_candlestick_chart(candles, current_idx, height=CHART_HEIGHT):
    if not candles:
        return ["No data"]

    # ---- Improved scaling ----
    # Get raw min/max from all candles
    min_price = min(c['low'] for c in candles)
    max_price = max(c['high'] for c in candles)
    avg_price = (min_price + max_price) / 2.0
    raw_range = max_price - min_price
    # If range is too wide (>5% of average), cap it to ±2.5% for better readability
    if raw_range / avg_price > 0.05:
        # Use a zoomed range around the average
        zoom_range = avg_price * 0.05  # 5% total (2.5% each side)
        min_price = avg_price - zoom_range / 2
        max_price = avg_price + zoom_range / 2
    else:
        # Add a small margin (2% of range) to avoid edge clipping
        margin = raw_range * 0.02
        min_price -= margin
        max_price += margin

    range_price = max_price - min_price
    if range_price == 0:
        range_price = 1

    price_per_row = range_price / height

    # Pre‑compute candle properties
    candle_data = []
    for c in candles:
        open_ = c['open']
        close_ = c['close']
        body_top = max(open_, close_)
        body_bottom = min(open_, close_)
        color = "green" if close_ >= open_ else "red"
        candle_data.append({
            'high': c['high'],
            'low': c['low'],
            'body_top': body_top,
            'body_bottom': body_bottom,
            'color': color
        })

    rows_chars = []
    for row in range(height):
        price_level = max_price - row * price_per_row
        row_chars = []
        for cd in candle_data:
            if cd['low'] <= price_level <= cd['high']:
                if cd['body_bottom'] <= price_level <= cd['body_top']:
                    row_chars.append(("█", cd['color']))
                else:
                    row_chars.append(("│", cd['color']))
            else:
                row_chars.append((" ", "white"))
        rows_chars.append(row_chars)

    colored_rows = []
    for row_chars in rows_chars:
        parts = []
        for ch, color in row_chars:
            if ch == " ":
                parts.append(" ")
            else:
                parts.append(f"[{color}]{ch}[/{color}]")
        colored_rows.append(" ".join(parts))
    return colored_rows

def build_layout(candles, current_idx, interval_sec):
    now = datetime.now(timezone.utc)
    current_candle = candles[current_idx]
    elapsed = (now - current_candle['start_time']).total_seconds()
    total = interval_sec
    remaining = max(0, total - elapsed)
    percent = min(100, (elapsed / total) * 100) if total > 0 else 0
    bar_len = 20
    filled = int(bar_len * percent / 100)
    bar = '█' * filled + '░' * (bar_len - filled)
    header_text = f"BTC/USDT [{interval_sec//60}m] - last {len(candles)} candles"
    countdown_text = f"Next candle in: {int(remaining)}s [{bar}] {percent:.0f}%"

    chart_rows = render_candlestick_chart(candles, current_idx)
    chart_panel = Panel(
        "\n".join(chart_rows),
        title=header_text,
        subtitle=countdown_text,
        border_style="blue",
        box=box.ROUNDED
    )

    # Table: only the current candle
    c = candles[current_idx]
    color = "green" if c['close'] >= c['open'] else "red"
    table = Table(box=box.MINIMAL, show_header=True, header_style="bold")
    table.add_column("", style="dim")        # marker
    table.add_column("Open", justify="right")
    table.add_column("High", justify="right")
    table.add_column("Low", justify="right")
    table.add_column("Close", justify="right")
    table.add_column("Volume", justify="right")
    table.add_row(
        ">>",
        f"[{color}]{c['open']:.2f}[/{color}]",
        f"[{color}]{c['high']:.2f}[/{color}]",
        f"[{color}]{c['low']:.2f}[/{color}]",
        f"[{color}]{c['close']:.2f}[/{color}]",
        f"{c['volume']:.2f}"
    )

    layout = Layout()
    layout.split(
        Layout(chart_panel, ratio=3),
        Layout(table, ratio=1)
    )
    return layout

def main():
    console.print("[bold green]Live OHLC for BTC/USDT from Bybit[/bold green]")
    interval_input = input("Enter timeframe (e.g., 1m, 5m, 1h) [default: 1m]: ").strip() or '1m'
    if interval_input not in INTERVAL_MAP:
        console.print(f"[red]Unsupported. Using 1m. Supported: {', '.join(INTERVAL_MAP.keys())}[/red]")
        interval_input = '1m'

    interval_api = INTERVAL_MAP[interval_input]
    interval_sec = INTERVAL_SECONDS[interval_input]

    completed = fetch_completed_candles(interval_api, KEEP_COUNT)
    if completed is None:
        return

    current_price = get_current_price()
    if current_price is None:
        return

    last = completed[-1]
    last_end = last['start_time'] + timedelta(seconds=interval_sec)
    now = datetime.now(timezone.utc)

    if now < last_end:
        candles = completed[:]
        current_idx = len(candles) - 1
        update_candle(candles[current_idx], current_price)
    else:
        candles = completed[:]
        new_start = last_end
        new_open = last['close']
        new_candle = create_current_candle(new_start, new_open, current_price)
        candles.append(new_candle)
        if len(candles) > KEEP_COUNT:
            candles = candles[-KEEP_COUNT:]
        current_idx = len(candles) - 1

    console.print(f"Monitoring started (interval: {interval_input}, keeping {KEEP_COUNT} candles). Press Ctrl+C to stop.")

    with Live(refresh_per_second=0.5, screen=True) as live:
        try:
            while True:
                new_price = get_current_price()
                if new_price is None:
                    time.sleep(2)
                    continue

                update_candle(candles[current_idx], new_price)

                now = datetime.now(timezone.utc)
                current_start = candles[current_idx]['start_time']
                next_start = current_start + timedelta(seconds=interval_sec)
                if now >= next_start:
                    new_open = candles[current_idx]['close']
                    new_candle = create_current_candle(next_start, new_open, new_price)
                    candles.append(new_candle)
                    if len(candles) > KEEP_COUNT:
                        candles = candles[1:]
                    current_idx = len(candles) - 1

                layout = build_layout(candles, current_idx, interval_sec)
                live.update(layout)
                time.sleep(2)
        except KeyboardInterrupt:
            console.print("\n[bold yellow]Monitoring stopped.[/bold yellow]")

if __name__ == "__main__":
    main()