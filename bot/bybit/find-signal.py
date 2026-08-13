import requests
import time
import json
import os
from datetime import datetime, timedelta, timezone
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich import box
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

# --- Configuration ---
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
TIMEOUT = 15
RETRY_ATTEMPTS = 3
BACKOFF_FACTOR = 1.5

# Trading parameters (you can change these)
TP_PERCENT = 0.5          # full take-profit in %
SL_PERCENT = 0.25          # stop-loss in %
HALF_TP_PERCENT = TP_PERCENT / 2  # half of TP (0.5% by default)

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

OUTPUT_DIR = "signals_output"
JSON_LOG_PATH = os.path.join(OUTPUT_DIR, "engulfing_signals.json")
TRADE_LOG_PATH = os.path.join(OUTPUT_DIR, "trade_log.json")

console = Console()

# ------------------------------------------------------------------
# HTTP session (unchanged)
# ------------------------------------------------------------------
def create_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=RETRY_ATTEMPTS,
        backoff_factor=BACKOFF_FACTOR,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": USER_AGENT})
    return session

session = create_session()

BYBIT_HOSTS = ["https://api.bybit.com", "https://api.bytick.com"]
BINANCE_HOST = "https://api.binance.com"
ACTIVE_SOURCE = {"name": None}

def _fetch_bybit_price():
    for host in BYBIT_HOSTS:
        try:
            resp = session.get(
                f"{host}/v5/market/tickers",
                params={"category": "spot", "symbol": "BTCUSDT"},
                timeout=TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
            return float(data['result']['list'][0]['lastPrice'])
        except Exception:
            continue
    return None

def _fetch_binance_price():
    try:
        resp = session.get(
            f"{BINANCE_HOST}/api/v3/ticker/price",
            params={"symbol": "BTCUSDT"},
            timeout=TIMEOUT
        )
        resp.raise_for_status()
        return float(resp.json()['price'])
    except Exception as e:
        console.print(f"[red]Error fetching price from Binance: {e}[/red]")
        return None

def get_current_price():
    if ACTIVE_SOURCE["name"] == "binance":
        return _fetch_binance_price()
    if ACTIVE_SOURCE["name"] == "bybit":
        price = _fetch_bybit_price()
        if price is not None:
            return price
        console.print("[yellow]Bybit stopped responding, switching to Binance...[/yellow]")
        ACTIVE_SOURCE["name"] = "binance"
        return _fetch_binance_price()
    price = _fetch_bybit_price()
    if price is not None:
        ACTIVE_SOURCE["name"] = "bybit"
        return price
    console.print("[yellow]Bybit unreachable. Falling back to Binance...[/yellow]")
    price = _fetch_binance_price()
    if price is not None:
        ACTIVE_SOURCE["name"] = "binance"
    return price

def _fetch_bybit_candles(interval_code, limit):
    for host in BYBIT_HOSTS:
        try:
            resp = session.get(
                f"{host}/v5/market/kline",
                params={"category": "spot", "symbol": "BTCUSDT", "interval": interval_code, "limit": limit},
                timeout=TIMEOUT
            )
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
        except Exception:
            continue
    return None

def _fetch_binance_candles(interval_label, limit):
    try:
        resp = session.get(
            f"{BINANCE_HOST}/api/v3/klines",
            params={"symbol": "BTCUSDT", "interval": interval_label, "limit": limit},
            timeout=TIMEOUT
        )
        resp.raise_for_status()
        raw = resp.json()
        candles = []
        for c in raw:
            dt = datetime.fromtimestamp(c[0] / 1000.0, tz=timezone.utc)
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
        console.print(f"[red]Error fetching candles from Binance: {e}[/red]")
        return None

def fetch_completed_candles(interval_code, limit, interval_label=None):
    if ACTIVE_SOURCE["name"] == "binance":
        return _fetch_binance_candles(interval_label, limit)
    if ACTIVE_SOURCE["name"] == "bybit":
        candles = _fetch_bybit_candles(interval_code, limit)
        if candles is not None:
            return candles
        console.print("[yellow]Bybit stopped responding, switching to Binance...[/yellow]")
        ACTIVE_SOURCE["name"] = "binance"
        return _fetch_binance_candles(interval_label, limit)
    candles = _fetch_bybit_candles(interval_code, limit)
    if candles is not None:
        ACTIVE_SOURCE["name"] = "bybit"
        return candles
    console.print("[yellow]Bybit unreachable. Falling back to Binance...[/yellow]")
    candles = _fetch_binance_candles(interval_label, limit)
    if candles is not None:
        ACTIVE_SOURCE["name"] = "binance"
    return candles

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

# ------------------------------------------------------------------
# Engulfing detection
# ------------------------------------------------------------------
def check_engulfing(prev, curr):
    prev_open, prev_close = prev['open'], prev['close']
    curr_open, curr_close = curr['open'], curr['close']
    prev_bullish = prev_close > prev_open
    curr_bullish = curr_close > curr_open
    if prev_open == prev_close or curr_open == curr_close:
        return None
    prev_top, prev_bottom = max(prev_open, prev_close), min(prev_open, prev_close)
    curr_top, curr_bottom = max(curr_open, curr_close), min(curr_open, curr_close)
    engulfs = curr_top >= prev_top and curr_bottom <= prev_bottom
    if not engulfs:
        return None
    if prev_bullish and not curr_bullish:
        return "bearish"
    if (not prev_bullish) and curr_bullish:
        return "bullish"
    return None

# ------------------------------------------------------------------
# Trade management (updated to use TP_PERCENT, SL_PERCENT, HALF_TP_PERCENT)
# ------------------------------------------------------------------
def create_trade(signal_record, entry_price, side, interval_label, signal_candle_time):
    """
    Create a trade dict.
    side: 'long' or 'short'
    """
    if side == 'long':
        tp_price = entry_price * (1 + TP_PERCENT / 100.0)
        sl_price = entry_price * (1 - SL_PERCENT / 100.0)
        half_tp_price = entry_price * (1 + HALF_TP_PERCENT / 100.0)
    else:  # short
        tp_price = entry_price * (1 - TP_PERCENT / 100.0)
        sl_price = entry_price * (1 + SL_PERCENT / 100.0)
        half_tp_price = entry_price * (1 - HALF_TP_PERCENT / 100.0)

    trade = {
        'signal_timestamp': signal_record['timestamp_utc'],
        'signal_candle_time': signal_candle_time.isoformat(),
        'entry_time': datetime.now(timezone.utc).isoformat(),
        'entry_price': entry_price,
        'side': side,
        'tp_price': tp_price,
        'sl_price': sl_price,
        'half_tp_price': half_tp_price,
        'half_tp_hit': False,
        'full_tp_hit': False,
        'status': 'open',          # 'open', 'tp', 'sl'
        'close_time': None,
        'close_price': None,
        'pnl_percent': None,
        'interval': interval_label,
        'signal_idx': None,
    }
    return trade

def check_trade_hit(trade, candle, current_price=None):
    """
    Check if the given candle (OHLC) has touched TP/SL/half-TP.
    Updates trade flags and returns:
      - 'tp' if full TP hit
      - 'sl' if SL hit
      - 'half' if half-TP hit (and not already hit)
      - None if nothing new
    """
    high = candle['high']
    low = candle['low']
    side = trade['side']
    result = None

    if side == 'long':
        if high >= trade['tp_price'] and not trade['full_tp_hit']:
            trade['full_tp_hit'] = True
            trade['status'] = 'tp'
            trade['close_price'] = trade['tp_price']
            trade['close_time'] = datetime.now(timezone.utc).isoformat()
            trade['pnl_percent'] = TP_PERCENT
            result = 'tp'
        elif high >= trade['half_tp_price'] and not trade['half_tp_hit']:
            trade['half_tp_hit'] = True
            result = 'half'
        elif low <= trade['sl_price'] and trade['status'] == 'open':
            trade['status'] = 'sl'
            trade['close_price'] = trade['sl_price']
            trade['close_time'] = datetime.now(timezone.utc).isoformat()
            trade['pnl_percent'] = -SL_PERCENT
            result = 'sl'
    else:  # short
        if low <= trade['tp_price'] and not trade['full_tp_hit']:
            trade['full_tp_hit'] = True
            trade['status'] = 'tp'
            trade['close_price'] = trade['tp_price']
            trade['close_time'] = datetime.now(timezone.utc).isoformat()
            trade['pnl_percent'] = TP_PERCENT
            result = 'tp'
        elif low <= trade['half_tp_price'] and not trade['half_tp_hit']:
            trade['half_tp_hit'] = True
            result = 'half'
        elif high >= trade['sl_price'] and trade['status'] == 'open':
            trade['status'] = 'sl'
            trade['close_price'] = trade['sl_price']
            trade['close_time'] = datetime.now(timezone.utc).isoformat()
            trade['pnl_percent'] = -SL_PERCENT
            result = 'sl'

    return result

def export_trade_png(trade, candles, event_type):
    """Plot chart from signal candle to current, mark event."""
    signal_time = datetime.fromisoformat(trade['signal_candle_time'])
    start_idx = None
    for i, c in enumerate(candles):
        if c['start_time'] == signal_time:
            start_idx = i
            break
    if start_idx is None:
        start_idx = 0

    plot_candles = candles[start_idx:]

    fig, ax = plt.subplots(figsize=(12, 6))

    up_color = "#26a69a"
    down_color = "#ef5350"
    entry_color = "blue"
    tp_color = "green"
    sl_color = "red"
    half_color = "orange"

    for i, c in enumerate(plot_candles):
        is_bull = c['close'] >= c['open']
        color = up_color if is_bull else down_color
        ax.plot([i, i], [c['low'], c['high']], color=color, linewidth=1)
        body_bottom = min(c['open'], c['close'])
        body_height = abs(c['close'] - c['open']) or (c['high'] - c['low']) * 0.02
        rect = Rectangle(
            (i - 0.3, body_bottom), 0.6, body_height,
            facecolor=color, edgecolor=color, linewidth=0.5
        )
        ax.add_patch(rect)

    ax.axhline(y=trade['entry_price'], color=entry_color, linestyle='--', linewidth=1, label='Entry')
    ax.axhline(y=trade['tp_price'], color=tp_color, linestyle='--', linewidth=1, label='TP 1%')
    ax.axhline(y=trade['sl_price'], color=sl_color, linestyle='--', linewidth=1, label='SL 0.5%')
    ax.axhline(y=trade['half_tp_price'], color=half_color, linestyle=':', linewidth=1, label='Half TP 0.5%')

    event_label = {
        'half': 'Half TP Hit',
        'tp': 'Full TP Hit',
        'sl': 'Stop Loss Hit'
    }[event_type]
    last_idx = len(plot_candles) - 1
    last_candle = plot_candles[-1]
    y_pos = last_candle['high'] + (last_candle['high'] - last_candle['low']) * 0.5
    ax.annotate(
        event_label,
        xy=(last_idx, last_candle['close']),
        xytext=(last_idx - 3, y_pos),
        arrowprops=dict(arrowstyle="->", color='black', lw=1.5),
        fontsize=10, fontweight='bold', color='black'
    )

    ax.set_title(f"Trade: {trade['side'].upper()} at {trade['entry_price']:.2f}  |  Event: {event_label}")
    ax.set_ylabel("Price")
    ax.set_xticks([])
    ax.legend(loc='upper left')
    fig.tight_layout()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    png_name = f"trade_{trade['side']}_{event_type}_{timestamp}.png"
    png_path = os.path.join(OUTPUT_DIR, png_name)
    fig.savefig(png_path, dpi=150)
    plt.close(fig)
    return png_path

def update_trade_log(trade):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    existing = []
    if os.path.exists(TRADE_LOG_PATH):
        try:
            with open(TRADE_LOG_PATH, "r") as f:
                existing = json.load(f)
        except Exception:
            existing = []
    key = trade['signal_timestamp'] + trade['entry_time']
    existing = [r for r in existing if (r.get('signal_timestamp','')+r.get('entry_time','')) != key]
    existing.append(trade)
    with open(TRADE_LOG_PATH, "w") as f:
        json.dump(existing, f, indent=2)

# ------------------------------------------------------------------
# Signal export
# ------------------------------------------------------------------
def export_signal(symbol, interval_label, prev_candle, curr_candle, pattern, context_candles):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    record = {
        "timestamp_utc": timestamp,
        "symbol": symbol,
        "interval": interval_label,
        "pattern": f"{pattern}_engulfing",
        "prev_candle": {
            "start_time": prev_candle['start_time'].isoformat(),
            "open": prev_candle['open'],
            "high": prev_candle['high'],
            "low": prev_candle['low'],
            "close": prev_candle['close'],
        },
        "curr_candle": {
            "start_time": curr_candle['start_time'].isoformat(),
            "open": curr_candle['open'],
            "high": curr_candle['high'],
            "low": curr_candle['low'],
            "close": curr_candle['close'],
        },
    }
    existing = []
    if os.path.exists(JSON_LOG_PATH):
        try:
            with open(JSON_LOG_PATH, "r") as f:
                existing = json.load(f)
        except Exception:
            existing = []
    existing.append(record)
    with open(JSON_LOG_PATH, "w") as f:
        json.dump(existing, f, indent=2)

    safe_ts = curr_candle['start_time'].strftime("%Y%m%d_%H%M%S")
    png_path = os.path.join(OUTPUT_DIR, f"{pattern}_engulfing_{safe_ts}.png")
    plot_engulfing_chart(context_candles, prev_candle, curr_candle, pattern, symbol, interval_label, png_path)
    return record, png_path

def plot_engulfing_chart(candles, prev_candle, curr_candle, pattern, symbol, interval_label, save_path):
    fig, ax = plt.subplots(figsize=(12, 6))
    up_color = "#26a69a"
    down_color = "#ef5350"
    highlight_color = "#ffd54f"
    for i, c in enumerate(candles):
        is_bull = c['close'] >= c['open']
        color = up_color if is_bull else down_color
        is_highlighted = (c is prev_candle) or (c is curr_candle)
        ax.plot([i, i], [c['low'], c['high']], color=color, linewidth=1)
        body_bottom = min(c['open'], c['close'])
        body_height = abs(c['close'] - c['open']) or (c['high'] - c['low']) * 0.02
        rect = Rectangle(
            (i - 0.3, body_bottom), 0.6, body_height,
            facecolor=color,
            edgecolor=highlight_color if is_highlighted else color,
            linewidth=2.5 if is_highlighted else 0.5,
            zorder=3
        )
        ax.add_patch(rect)
    ax.set_xlim(-1, len(candles))
    ax.set_title(f"{symbol} [{interval_label}] - {pattern.upper()} ENGULFING SIGNAL", fontsize=13, fontweight="bold")
    ax.set_ylabel("Price")
    ax.set_xticks([])
    arrow_color = "green" if pattern == "bullish" else "red"
    idx_curr = candles.index(curr_candle)
    ax.annotate(
        f"{pattern.upper()} ENGULFING",
        xy=(idx_curr, curr_candle['close']),
        xytext=(idx_curr - 5, curr_candle['close'] + (curr_candle['high'] - curr_candle['low']) * 3),
        arrowprops=dict(arrowstyle="->", color=arrow_color, lw=2),
        fontsize=10, fontweight="bold", color=arrow_color
    )
    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)

# ------------------------------------------------------------------
# Terminal rendering
# ------------------------------------------------------------------
TV_UP = "#26a69a"
TV_DOWN = "#ef5350"
TV_GRID = "#363a45"
TV_AXIS = "#787b86"
TV_PRICE_LINE = "#f0b90b"

TABLE_PANEL_HEIGHT = 6
SIGNAL_PANEL_HEIGHT = 5
TRADE_PANEL_HEIGHT = 4
CHART_PANEL_CHROME = 4

def _nice_step(range_price, target_lines=6):
    if range_price <= 0:
        return 1.0
    raw_step = range_price / target_lines
    magnitude = 10 ** (len(str(int(raw_step))) - 1) if raw_step >= 1 else 10 ** -(len(f"{raw_step:.10f}".split('.')[1]) - len(f"{raw_step:.10f}".split('.')[1].lstrip('0')) + 1)
    for mult in (1, 2, 2.5, 5, 10):
        step = mult * magnitude
        if step >= raw_step:
            return step
    return 10 * magnitude

def _price_row_for(price, max_price, range_price, height):
    row = (max_price - price) / range_price * height
    return max(0, min(height - 1, int(row)))

def render_candlestick_chart(candles, current_idx, height):
    if not candles:
        return ["No data"], ""
    height = max(6, height)
    raw_min = min(c['low'] for c in candles)
    raw_max = max(c['high'] for c in candles)
    avg = (raw_min + raw_max) / 2.0
    if avg and (raw_max - raw_min) / avg > 0.05:
        half_range = avg * 0.025
        min_price = avg - half_range
        max_price = avg + half_range
    else:
        margin = (raw_max - raw_min) * 0.02 or 1
        min_price = raw_min - margin
        max_price = raw_max + margin
    range_price = max_price - min_price
    if range_price == 0:
        range_price = 1

    candle_data = []
    for c in candles:
        open_, close_ = c['open'], c['close']
        candle_data.append({
            'high': c['high'],
            'low': c['low'],
            'body_top': max(open_, close_),
            'body_bottom': min(open_, close_),
            'color': TV_UP if close_ >= open_ else TV_DOWN,
        })

    step = _nice_step(range_price, target_lines=6)
    first_tick = (min_price // step + 1) * step
    grid_prices = []
    p = first_tick
    while p <= max_price:
        grid_prices.append(round(p, 8))
        p += step

    label_rows = {}
    for gp in grid_prices:
        row = _price_row_for(gp, max_price, range_price, height)
        label_rows[row] = gp

    last_price = candles[current_idx]['close']
    price_row = _price_row_for(last_price, max_price, range_price, height)

    rows_chars = []
    for row in range(height):
        price_level = max_price - row * (range_price / height)
        row_chars = []
        for cd in candle_data:
            if cd['low'] <= price_level <= cd['high']:
                if cd['body_bottom'] <= price_level <= cd['body_top']:
                    row_chars.append(("█", cd['color']))
                else:
                    row_chars.append(("│", cd['color']))
            else:
                if row == price_row:
                    row_chars.append(("╌", TV_PRICE_LINE))
                elif row in label_rows:
                    row_chars.append(("·", TV_GRID))
                else:
                    row_chars.append((" ", None))
        rows_chars.append(row_chars)

    max_label_len = max(len(f"{max_price:,.2f}"), len(f"{min_price:,.2f}")) + 1

    chart_lines = []
    for idx, row_chars in enumerate(rows_chars):
        parts = []
        for ch, color in row_chars:
            if color is None:
                parts.append(" ")
            else:
                parts.append(f"[{color}]{ch}[/{color}]")
        line = " ".join(parts)
        if idx == price_row:
            label = f"{last_price:,.2f}"
            tag = f"[black on {TV_PRICE_LINE}] {label:>{max_label_len}} [/black on {TV_PRICE_LINE}]"
            line = f"{line} {tag}"
        elif idx in label_rows:
            label = f"{label_rows[idx]:,.2f}"
            line = f"{line}  [{TV_AXIS}]{label:>{max_label_len}}[/{TV_AXIS}]"
        else:
            line = f"{line}  {' ' * max_label_len}"
        chart_lines.append(line)

    total_width = len(candles) * 2 - 1
    tick_row = [" "] * total_width
    label_row = [" "] * total_width
    step = max(1, len(candles) // 6)
    tick_positions = sorted(set(list(range(0, len(candles), step)) + [len(candles) - 1]))
    for i in tick_positions:
        pos = i * 2
        tick_row[pos] = "╵"
        label = candles[i]['start_time'].astimezone().strftime("%H:%M")
        start = pos - len(label) // 2
        start = max(0, min(total_width - len(label), start))
        for j, ch in enumerate(label):
            k = start + j
            if 0 <= k < total_width:
                label_row[k] = ch
    tick_line = f"[{TV_AXIS}]{''.join(tick_row)}[/{TV_AXIS}]"
    time_line = f"[{TV_AXIS}]{''.join(label_row)}[/{TV_AXIS}]"

    return chart_lines, tick_line, time_line

def build_layout(candles, current_idx, interval_sec, last_signal_text, active_trade, console_height=40):
    now = datetime.now(timezone.utc)
    current_candle = candles[current_idx]
    elapsed = (now - current_candle['start_time']).total_seconds()
    total = interval_sec
    remaining = max(0, total - elapsed)
    percent = min(100, (elapsed / total) * 100) if total > 0 else 0
    bar_len = 20
    filled = int(bar_len * percent / 100)
    bar = '█' * filled + '░' * (bar_len - filled)
    header_text = f"BTC/USDT · {interval_sec // 60}m · {len(candles)} candles"
    countdown_text = f"Next candle in {int(remaining)}s [{bar}] {percent:.0f}%"

    chart_height = console_height - TABLE_PANEL_HEIGHT - SIGNAL_PANEL_HEIGHT - TRADE_PANEL_HEIGHT - CHART_PANEL_CHROME
    chart_lines, tick_line, time_line = render_candlestick_chart(candles, current_idx, chart_height)
    chart_body = "\n".join(chart_lines) + "\n" + tick_line + "\n" + time_line
    chart_panel = Panel(
        chart_body,
        title=f"[bold]{header_text}[/bold]",
        subtitle=countdown_text,
        border_style=TV_GRID,
        box=box.SQUARE,
        padding=(0, 1),
    )

    c = candles[current_idx]
    color = TV_UP if c['close'] >= c['open'] else TV_DOWN
    table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style=f"bold {TV_AXIS}", padding=(0, 1))
    table.add_column("", style="dim", width=3)
    table.add_column("Open", justify="right")
    table.add_column("High", justify="right")
    table.add_column("Low", justify="right")
    table.add_column("Close", justify="right")
    table.add_column("Volume", justify="right")
    table.add_row(
        ">>",
        f"[{color}]{c['open']:,.2f}[/{color}]",
        f"[{color}]{c['high']:,.2f}[/{color}]",
        f"[{color}]{c['low']:,.2f}[/{color}]",
        f"[{color}]{c['close']:,.2f}[/{color}]",
        f"{c['volume']:,.2f}"
    )

    # Trade info panel
    trade_info = "No active trade"
    if active_trade and active_trade['status'] == 'open':
        side = active_trade['side'].upper()
        entry = active_trade['entry_price']
        tp = active_trade['tp_price']
        sl = active_trade['sl_price']
        half = active_trade['half_tp_price']
        pnl = (c['close'] - entry) / entry * 100 if side == 'LONG' else (entry - c['close']) / entry * 100
        pnl_str = f"{pnl:+.2f}%"
        color_pnl = "green" if pnl >= 0 else "red"
        trade_info = f"Side: {side} | Entry: {entry:.2f} | TP: {tp:.2f} | SL: {sl:.2f} | Half: {half:.2f} | PnL: [{color_pnl}]{pnl_str}[/{color_pnl}]"
        if active_trade['half_tp_hit']:
            trade_info += " [yellow]Half TP hit![/yellow]"
    elif active_trade and active_trade['status'] in ('tp', 'sl'):
        side = active_trade['side'].upper()
        entry = active_trade['entry_price']
        status = active_trade['status'].upper()
        pnl = active_trade['pnl_percent']
        pnl_str = f"{pnl:+.2f}%"
        color_pnl = "green" if pnl >= 0 else "red"
        trade_info = f"Trade closed: {side} | Entry: {entry:.2f} | Status: {status} | PnL: [{color_pnl}]{pnl_str}[/{color_pnl}]"
    trade_panel = Panel(trade_info, title="Trade Status", border_style=TV_PRICE_LINE if active_trade else TV_GRID, box=box.SQUARE)

    signal_panel = Panel(
        last_signal_text or "No engulfing signal yet.",
        title="Last Signal",
        border_style=TV_PRICE_LINE if last_signal_text else TV_GRID,
        box=box.SQUARE,
    )

    layout = Layout()
    layout.split(
        Layout(chart_panel, ratio=1),
        Layout(table, size=TABLE_PANEL_HEIGHT),
        Layout(trade_panel, size=TRADE_PANEL_HEIGHT),
        Layout(signal_panel, size=SIGNAL_PANEL_HEIGHT),
    )
    return layout

# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
def main():
    console.print("[bold green]Live OHLC + Engulfing Signal Finder with TP/SL (BTC/USDT)[/bold green]")
    interval_input = input("Enter timeframe (e.g., 1m, 5m, 1h) [default: 1m]: ").strip() or '1m'
    if interval_input not in INTERVAL_MAP:
        console.print(f"[red]Unsupported. Using 1m. Supported: {', '.join(INTERVAL_MAP.keys())}[/red]")
        interval_input = '1m'

    interval_api = INTERVAL_MAP[interval_input]
    interval_sec = INTERVAL_SECONDS[interval_input]
    symbol = "BTCUSDT"

    completed = None
    for attempt in range(3):
        console.print(f"Fetching initial data... attempt {attempt + 1}/3")
        completed = fetch_completed_candles(interval_api, KEEP_COUNT, interval_input)
        if completed is not None:
            break
        time.sleep(2)
    if completed is None:
        console.print("[red]Failed to fetch initial data. Exiting.[/red]")
        return

    current_price = None
    for attempt in range(3):
        current_price = get_current_price()
        if current_price is not None:
            break
        time.sleep(2)
    if current_price is None:
        console.print("[red]Failed to fetch current price. Exiting.[/red]")
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

    last_signal_text = None
    if len(completed) >= 2:
        pattern = check_engulfing(completed[-2], completed[-1])
        if pattern:
            record, png_path = export_signal(symbol, interval_input, completed[-2], completed[-1], pattern, completed)
            last_signal_text = f"[{pattern.upper()}] {record['timestamp_utc']} -> {png_path}"
            console.print(f"[bold yellow]Startup {pattern} engulfing signal found -> {png_path}[/bold yellow]")

    active_trade = None

    console.print(f"Monitoring started (interval: {interval_input}, keeping {KEEP_COUNT} candles). Press Ctrl+C to stop.")

    with Live(refresh_per_second=0.5, screen=True) as live:
        try:
            while True:
                console_height = live.console.size.height
                new_price = get_current_price()
                if new_price is None:
                    time.sleep(2)
                    continue

                update_candle(candles[current_idx], new_price)

                now = datetime.now(timezone.utc)
                current_start = candles[current_idx]['start_time']
                next_start = current_start + timedelta(seconds=interval_sec)

                if now >= next_start:
                    if current_idx - 1 >= 0:
                        prev_candle = candles[current_idx - 1]
                        curr_candle = candles[current_idx]
                        pattern = check_engulfing(prev_candle, curr_candle)
                        if pattern:
                            if active_trade is None or active_trade['status'] != 'open':
                                record, png_path = export_signal(
                                    symbol, interval_input, prev_candle, curr_candle, pattern, candles
                                )
                                last_signal_text = f"[{pattern.upper()}] {record['timestamp_utc']} -> {png_path}"
                                console.print(
                                    f"[bold yellow]{pattern.upper()} ENGULFING signal detected! "
                                    f"Saved chart to {png_path} and logged to {JSON_LOG_PATH}[/bold yellow]"
                                )

                                side = 'long' if pattern == 'bullish' else 'short'
                                entry_price = curr_candle['close']
                                trade = create_trade(record, entry_price, side, interval_input, curr_candle['start_time'])
                                trade['signal_idx'] = current_idx
                                active_trade = trade
                                update_trade_log(trade)
                                console.print(f"[bold cyan]Trade opened: {side.upper()} at {entry_price:.2f}[/bold cyan]")

                    new_open = candles[current_idx]['close']
                    new_candle = create_current_candle(next_start, new_open, new_price)
                    candles.append(new_candle)
                    if len(candles) > KEEP_COUNT:
                        candles = candles[1:]
                    current_idx = len(candles) - 1

                if active_trade is not None and active_trade['status'] == 'open':
                    current_candle = candles[current_idx]
                    result = check_trade_hit(active_trade, current_candle)
                    if result == 'half':
                        png_path = export_trade_png(active_trade, candles, 'half')
                        console.print(f"[bold yellow]Half TP hit! PNG saved: {png_path}[/bold yellow]")
                        update_trade_log(active_trade)
                    elif result == 'tp':
                        png_path = export_trade_png(active_trade, candles, 'tp')
                        console.print(f"[bold green]Full TP hit! Trade closed. PNG: {png_path}[/bold green]")
                        update_trade_log(active_trade)
                    elif result == 'sl':
                        png_path = export_trade_png(active_trade, candles, 'sl')
                        console.print(f"[bold red]Stop Loss hit! Trade closed. PNG: {png_path}[/bold red]")
                        update_trade_log(active_trade)

                layout = build_layout(candles, current_idx, interval_sec, last_signal_text, active_trade, console_height)
                live.update(layout)
                time.sleep(2)

        except KeyboardInterrupt:
            console.print("\n[bold yellow]Monitoring stopped.[/bold yellow]")

if __name__ == "__main__":
    main()