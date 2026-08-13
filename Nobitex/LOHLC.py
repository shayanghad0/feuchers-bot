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
SYMBOL = "BTCUSDT"   # fixed as requested

# Map user-friendly intervals to Nobitex resolution codes
INTERVAL_MAP = {
    '1m': '1', '5m': '5', '15m': '15', '30m': '30',
    '1h': '60', '3h': '180', '4h': '240', '6h': '360', '12h': '720',
    '1d': 'D', '2d': '2D', '3d': '3D',
    # also allow raw codes
    '1': '1', '5': '5', '15': '15', '30': '30',
    '60': '60', '180': '180', '240': '240', '360': '360', '720': '720',
    'D': 'D', '2D': '2D', '3D': '3D'
}

# Seconds per resolution (for countdown)
INTERVAL_SECONDS = {
    '1': 60, '5': 300, '15': 900, '30': 1800,
    '60': 3600, '180': 10800, '240': 14400, '360': 21600, '720': 43200,
    'D': 86400, '2D': 172800, '3D': 259200
}

KEEP_COUNT = 30
CHART_HEIGHT = 15

console = Console()


def get_current_price():
    """Fetch latest price from Nobitex stats."""
    url = "https://apiv2.nobitex.ir/market/stats"
    params = {"srcCurrency": "btc", "dstCurrency": "usdt"}
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if data.get('status') != 'ok':
            raise Exception("Stats API error")
        stats = data['stats']
        # The key is like "btc-usdt" but may be lowercase? The API returns "btc-usdt"?
        # Actually the example shows "btc-rls", so we'll construct it.
        key = f"{params['srcCurrency']}-{params['dstCurrency']}"
        if key not in stats:
            # Try alternative: "BTCUSDT" maybe? Let's search for any key containing 'btc' and 'usdt'
            for k in stats:
                if 'btc' in k and 'usdt' in k:
                    key = k
                    break
            else:
                raise Exception("No BTCUSDT stats found")
        return float(stats[key]['latest'])
    except Exception as e:
        console.print(f"[red]Error fetching price: {e}[/red]")
        return None


def fetch_completed_candles(resolution, limit):
    """Fetch completed candles using countback. Returns list in chronological order."""
    url = "https://apiv2.nobitex.ir/market/udf/history"
    now = int(time.time())
    params = {
        "symbol": SYMBOL,
        "resolution": resolution,
        "to": now,
        "countback": limit
    }
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if data.get('s') == 'error':
            raise Exception(f"API error: {data.get('errmsg', 'Unknown')}")
        if data.get('s') == 'no_data':
            return []
        t = data.get('t', [])
        o = data.get('o', [])
        h = data.get('h', [])
        l = data.get('l', [])
        c = data.get('c', [])
        v = data.get('v', [])
        candles = []
        for i in range(len(t)):
            dt = datetime.fromtimestamp(t[i], tz=timezone.utc)
            candles.append({
                'start_time': dt,
                'open': float(o[i]),
                'high': float(h[i]),
                'low': float(l[i]),
                'close': float(c[i]),
                'volume': float(v[i])
            })
        # The API returns oldest first? The doc says it returns in order of t array, which is ascending.
        # We'll keep as is (oldest first).
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
    min_price = min(c['low'] for c in candles)
    max_price = max(c['high'] for c in candles)
    avg_price = (min_price + max_price) / 2.0
    raw_range = max_price - min_price
    if raw_range / avg_price > 0.05:
        zoom_range = avg_price * 0.05
        min_price = avg_price - zoom_range / 2
        max_price = avg_price + zoom_range / 2
    else:
        margin = raw_range * 0.02
        min_price -= margin
        max_price += margin

    range_price = max_price - min_price
    if range_price == 0:
        range_price = 1

    price_per_row = range_price / height

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
    # Determine interval label for display
    if total < 3600:
        label = f"{int(total//60)}m"
    elif total < 86400:
        label = f"{int(total//3600)}h"
    else:
        label = f"{int(total//86400)}d"
    header_text = f"BTC/USDT [{label}] - last {len(candles)} candles"
    countdown_text = f"Next candle in: {int(remaining)}s [{bar}] {percent:.0f}%"

    chart_rows = render_candlestick_chart(candles, current_idx)
    chart_panel = Panel(
        "\n".join(chart_rows),
        title=header_text,
        subtitle=countdown_text,
        border_style="blue",
        box=box.ROUNDED
    )

    # Table: current candle
    c = candles[current_idx]
    color = "green" if c['close'] >= c['open'] else "red"
    table = Table(box=box.MINIMAL, show_header=True, header_style="bold")
    table.add_column("", style="dim")
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
    console.print("[bold green]Live OHLC for BTC/USDT from Nobitex[/bold green]")
    interval_input = input("Enter timeframe (e.g., 1m, 5m, 1h) [default: 1m]: ").strip() or '1m'
    if interval_input not in INTERVAL_MAP:
        console.print(f"[red]Unsupported. Using 1m. Supported: {', '.join(INTERVAL_MAP.keys())}[/red]")
        interval_input = '1m'

    api_interval = INTERVAL_MAP[interval_input]
    interval_sec = INTERVAL_SECONDS.get(api_interval)
    if interval_sec is None:
        console.print(f"[red]No seconds mapping for {api_interval}. Using 1m.[/red]")
        api_interval = '1'
        interval_sec = 60

    # Fetch initial candles
    completed = fetch_completed_candles(api_interval, KEEP_COUNT)
    if completed is None:
        return

    # Get current price
    current_price = get_current_price()
    if current_price is None:
        return

    # Determine if we need to start a new candle
    last = completed[-1]
    last_end = last['start_time'] + timedelta(seconds=interval_sec)
    now = datetime.now(timezone.utc)

    if now < last_end:
        # Still inside the last candle
        candles = completed[:]  # copy
        current_idx = len(candles) - 1
        update_candle(candles[current_idx], current_price)
    else:
        # New candle should begin
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
                    # New candle formed
                    new_open = candles[current_idx]['close']
                    new_candle = create_current_candle(next_start, new_open, new_price)
                    candles.append(new_candle)
                    if len(candles) > KEEP_COUNT:
                        candles = candles[1:]  # remove oldest
                    current_idx = len(candles) - 1

                layout = build_layout(candles, current_idx, interval_sec)
                live.update(layout)
                time.sleep(2)
        except KeyboardInterrupt:
            console.print("\n[bold yellow]Monitoring stopped.[/bold yellow]")


if __name__ == "__main__":
    main()