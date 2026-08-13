import requests
import time
import json
import os
import base64
from datetime import datetime, timedelta, timezone
from rich.console import Console
from rich.table import Table
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

TP_PERCENT = 0.5
SL_PERCENT = 0.25
HALF_TP_PERCENT = TP_PERCENT / 2

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

OUTPUT_DIR = "backtest_output"
TRADE_LOG_PATH = os.path.join(OUTPUT_DIR, "trade_log_backtest.json")
EQUITY_LOG_PATH = os.path.join(OUTPUT_DIR, "equity_curve.json")
EQUITY_PNG_PATH = os.path.join(OUTPUT_DIR, "equity_curve.png")
REPORT_HTML_PATH = os.path.join(OUTPUT_DIR, "backtest_report.html")

console = Console()

# ------------------------------------------------------------------
# HTTP session
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

def _fetch_bybit_candles_chunk(interval_code, limit, end_time_ms=None):
    """
    Fetch a single chunk of up to 1000 candles from Bybit.
    end_time_ms: optional end timestamp in milliseconds (exclusive).
    Returns list of candles (oldest-first) or None on error.
    """
    for host in BYBIT_HOSTS:
        try:
            params = {"category": "spot", "symbol": "BTCUSDT", "interval": interval_code, "limit": limit}
            if end_time_ms is not None:
                params["end"] = int(end_time_ms)
            resp = session.get(
                f"{host}/v5/market/kline",
                params=params,
                timeout=TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
            if data['retCode'] != 0:
                raise Exception(f"API error: {data['retMsg']}")
            raw = data['result']['list'][::-1]  # reverse to oldest-first
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

def _fetch_binance_candles_chunk(interval_label, limit, end_time_ms=None):
    """
    Fetch a single chunk of up to 1000 candles from Binance.
    end_time_ms: optional end timestamp in milliseconds (exclusive).
    Returns list of candles (oldest-first) or None on error.
    """
    try:
        params = {"symbol": "BTCUSDT", "interval": interval_label, "limit": limit}
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)
        resp = session.get(
            f"{BINANCE_HOST}/api/v3/klines",
            params=params,
            timeout=TIMEOUT
        )
        resp.raise_for_status()
        raw = resp.json()  # oldest-first
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
        console.print(f"[red]Binance chunk error: {e}[/red]")
        return None

def fetch_many_candles(interval_code, interval_label, limit, source):
    """
    Fetch up to `limit` candles using pagination.
    source: 'bybit' or 'binance'
    Returns list of candles (oldest-first) or None.
    """
    candles = []
    remaining = limit
    end_time_ms = None  # most recent first
    chunk_size = min(1000, remaining)

    while remaining > 0:
        if source == 'bybit':
            chunk = _fetch_bybit_candles_chunk(interval_code, chunk_size, end_time_ms)
        else:  # binance
            chunk = _fetch_binance_candles_chunk(interval_label, chunk_size, end_time_ms)

        if not chunk:
            break

        candles.extend(chunk)  # chunk is oldest-first
        if len(chunk) < chunk_size:
            # No more data available
            break

        # Get the start_time of the oldest candle in this chunk (first element)
        oldest = chunk[0]
        # Set end_time to 1 ms before that to avoid overlap
        end_time_ms = int(oldest['start_time'].timestamp() * 1000) - 1
        remaining -= len(chunk)
        chunk_size = min(1000, remaining)

    # Sort by start_time to ensure chronological order (should already be sorted, but just in case)
    candles.sort(key=lambda c: c['start_time'])
    return candles[:limit] if candles else None

def fetch_completed_candles(interval_code, limit, interval_label=None):
    """
    Fetches candles using the active source (Bybit or Binance) with pagination.
    """
    if ACTIVE_SOURCE["name"] == "binance":
        return fetch_many_candles(interval_code, interval_label, limit, 'binance')
    if ACTIVE_SOURCE["name"] == "bybit":
        candles = fetch_many_candles(interval_code, interval_label, limit, 'bybit')
        if candles is not None:
            return candles
        console.print("[yellow]Bybit stopped responding, switching to Binance...[/yellow]")
        ACTIVE_SOURCE["name"] = "binance"
        return fetch_many_candles(interval_code, interval_label, limit, 'binance')

    # First try Bybit, then Binance
    candles = fetch_many_candles(interval_code, interval_label, limit, 'bybit')
    if candles is not None:
        ACTIVE_SOURCE["name"] = "bybit"
        return candles
    console.print("[yellow]Bybit unreachable. Falling back to Binance...[/yellow]")
    candles = fetch_many_candles(interval_code, interval_label, limit, 'binance')
    if candles is not None:
        ACTIVE_SOURCE["name"] = "binance"
    return candles

# ------------------------------------------------------------------
# The rest of the code (engulfing, trade management, backtest, reports)
# remains exactly the same as previously provided.
# For brevity, I'll include it here but it's unchanged.
# ------------------------------------------------------------------

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

def create_trade(signal_record, entry_price, side, interval_label, signal_candle_time):
    if side == 'long':
        tp_price = entry_price * (1 + TP_PERCENT / 100.0)
        sl_price = entry_price * (1 - SL_PERCENT / 100.0)
        half_tp_price = entry_price * (1 + HALF_TP_PERCENT / 100.0)
    else:
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
        'half_tp_revisited': False,
        'entry_revisited_after_half_tp': False,
        'full_tp_hit': False,
        'status': 'open',          # 'open', 'tp', 'sl', 'break_even', 'half_revisited'
        'close_time': None,
        'close_price': None,
        'pnl_percent': None,
        'pnl_dollar': None,
        'interval': interval_label,
        'signal_idx': None,
        'capital_before': None,
        'capital_after': None,
    }
    return trade

def check_trade_hit(trade, candle):
    """
    Check if the given candle (OHLC) has touched TP/SL/half-TP.
    Updates trade flags and returns:
      - 'tp' if full TP hit
      - 'sl' if SL hit
      - 'half' if half-TP hit (and not already hit)
      - 'half_revisited' if price revisits half_tp after initial hit
      - 'break_even' if price returns to entry after hitting half_tp
      - None if nothing new
    """
    high = candle['high']
    low = candle['low']
    side = trade['side']
    result = None

    if side == 'long':
        # Check if half_tp was hit and price revisits it (failed breakout)
        if (
            trade['half_tp_hit'] and not trade['half_tp_revisited'] and
            high >= trade['half_tp_price']
        ):
            trade['half_tp_revisited'] = True
            trade['status'] = 'half_revisited'
            trade['close_price'] = trade['half_tp_price']
            trade['close_time'] = candle['start_time'].isoformat()
            trade['pnl_percent'] = HALF_TP_PERCENT
            result = 'half_revisited'

        # Check if price returns to entry after hitting half_tp (break-even protection)
        elif (
            trade['half_tp_hit'] and not trade['entry_revisited_after_half_tp'] and
            low <= trade['entry_price']
        ):
            trade['entry_revisited_after_half_tp'] = True
            trade['status'] = 'break_even'
            trade['close_price'] = trade['entry_price']
            trade['close_time'] = candle['start_time'].isoformat()
            trade['pnl_percent'] = 0.0
            result = 'break_even'

        # Existing logic for full TP, half TP, and SL
        elif high >= trade['tp_price'] and not trade['full_tp_hit']:
            trade['full_tp_hit'] = True
            trade['status'] = 'tp'
            trade['close_price'] = trade['tp_price']
            trade['close_time'] = candle['start_time'].isoformat()
            trade['pnl_percent'] = TP_PERCENT
            result = 'tp'
        elif high >= trade['half_tp_price'] and not trade['half_tp_hit']:
            trade['half_tp_hit'] = True
            result = 'half'
        elif low <= trade['sl_price'] and trade['status'] == 'open':
            trade['status'] = 'sl'
            trade['close_price'] = trade['sl_price']
            trade['close_time'] = candle['start_time'].isoformat()
            trade['pnl_percent'] = -SL_PERCENT
            result = 'sl'
    else:  # short
        # Check if half_tp was hit and price revisits it (failed breakout)
        if (
            trade['half_tp_hit'] and not trade['half_tp_revisited'] and
            low <= trade['half_tp_price']
        ):
            trade['half_tp_revisited'] = True
            trade['status'] = 'half_revisited'
            trade['close_price'] = trade['half_tp_price']
            trade['close_time'] = candle['start_time'].isoformat()
            trade['pnl_percent'] = HALF_TP_PERCENT
            result = 'half_revisited'

        # Check if price returns to entry after hitting half_tp (break-even protection)
        elif (
            trade['half_tp_hit'] and not trade['entry_revisited_after_half_tp'] and
            high >= trade['entry_price']
        ):
            trade['entry_revisited_after_half_tp'] = True
            trade['status'] = 'break_even'
            trade['close_price'] = trade['entry_price']
            trade['close_time'] = candle['start_time'].isoformat()
            trade['pnl_percent'] = 0.0
            result = 'break_even'

        # Existing logic for full TP, half TP, and SL
        elif low <= trade['tp_price'] and not trade['full_tp_hit']:
            trade['full_tp_hit'] = True
            trade['status'] = 'tp'
            trade['close_price'] = trade['tp_price']
            trade['close_time'] = candle['start_time'].isoformat()
            trade['pnl_percent'] = TP_PERCENT
            result = 'tp'
        elif low <= trade['half_tp_price'] and not trade['half_tp_hit']:
            trade['half_tp_hit'] = True
            result = 'half'
        elif high >= trade['sl_price'] and trade['status'] == 'open':
            trade['status'] = 'sl'
            trade['close_price'] = trade['sl_price']
            trade['close_time'] = candle['start_time'].isoformat()
            trade['pnl_percent'] = -SL_PERCENT
            result = 'sl'
    return result

def update_trade_log(trade_log):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    existing = []
    if os.path.exists(TRADE_LOG_PATH):
        try:
            with open(TRADE_LOG_PATH, "r") as f:
                existing = json.load(f)
        except Exception:
            existing = []
    key = trade_log['signal_timestamp'] + str(trade_log['entry_price'])
    existing = [r for r in existing if (r.get('signal_timestamp','')+str(r.get('entry_price',''))) != key]
    existing.append(trade_log)
    with open(TRADE_LOG_PATH, "w") as f:
        json.dump(existing, f, indent=2)

def plot_equity_curve(equity_curve, output_path):
    if not equity_curve:
        return
    times = [datetime.fromisoformat(p['time']) for p in equity_curve]
    capitals = [p['capital'] for p in equity_curve]
    prices = [p['price'] for p in equity_curve]
    fig, ax1 = plt.subplots(figsize=(12, 6))
    ax1.plot(times, capitals, color='blue', linewidth=2, label='Capital')
    ax1.set_xlabel('Time')
    ax1.set_ylabel('Capital ($)', color='blue')
    ax1.tick_params(axis='y', labelcolor='blue')
    ax1.grid(True, alpha=0.3)
    ax2 = ax1.twinx()
    ax2.plot(times, prices, color='gray', linewidth=1, linestyle='--', label='BTC Price')
    ax2.set_ylabel('BTC Price ($)', color='gray')
    ax2.tick_params(axis='y', labelcolor='gray')
    fig.suptitle('Equity Curve vs BTC Price')
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

def generate_html_report(summary, trades, equity_curve, output_path):
    if not trades:
        html = "<h1>No trades executed.</h1>"
        with open(output_path, 'w') as f:
            f.write(html)
        return
    table_rows = ""
    for t in trades:
        side = t['side'].upper()
        entry = t['entry_price']
        exit_price = t.get('close_price', 'N/A')
        pnl_pct = t.get('pnl_percent', 0)
        pnl_dollar = t.get('pnl_dollar', 0)
        status = t['status']
        half_hit = "Yes" if t.get('half_tp_hit', False) else "No"
        full_hit = "Yes" if t.get('full_tp_hit', False) else "No"
        entry_time = t.get('entry_time', '')
        exit_time = t.get('close_time', '')
        color = "green" if pnl_pct > 0 else "red" if pnl_pct < 0 else "gray"
        table_rows += f"""
        <tr>
            <td>{entry_time}</td>
            <td>{exit_time}</td>
            <td>{side}</td>
            <td>{entry:.2f}</td>
            <td>{exit_price}</td>
            <td style="color:{color};">{pnl_pct:+.2f}%</td>
            <td style="color:{color};">{pnl_dollar:+.2f}</td>
            <td>{status}</td>
            <td>{half_hit}</td>
            <td>{full_hit}</td>
        </tr>
        """
    chart_base64 = ""
    if os.path.exists(EQUITY_PNG_PATH):
        with open(EQUITY_PNG_PATH, "rb") as img_file:
            chart_base64 = base64.b64encode(img_file.read()).decode('utf-8')
    wins = summary.get('wins', 0)
    losses = summary.get('losses', 0)
    total_trades = summary.get('total_trades', 0)
    win_rate = summary.get('win_rate', 0)
    total_pnl_pct = summary.get('total_pnl_pct', 0)
    total_pnl_dollar = summary.get('total_pnl_dollar', 0)
    avg_pnl_pct = summary.get('avg_pnl_pct', 0)
    avg_pnl_dollar = summary.get('avg_pnl_dollar', 0)
    half_hits = summary.get('half_hits', 0)
    half_revisited_hits = summary.get('half_revisited_hits', 0)
    break_even_hits = summary.get('break_even_hits', 0)
    initial_capital = summary.get('initial_capital', 0)
    final_capital = summary.get('final_capital', 0)
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Backtest Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            h1, h2 {{ color: #333; }}
            .summary {{ display: flex; flex-wrap: wrap; gap: 20px; margin-bottom: 30px; }}
            .stat {{ background: #f5f5f5; padding: 15px; border-radius: 8px; flex: 1 1 200px; }}
            .stat-label {{ font-weight: bold; display: block; color: #555; }}
            .stat-value {{ font-size: 24px; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: right; }}
            th {{ background-color: #f2f2f2; }}
            .chart {{ margin: 20px 0; }}
            img {{ max-width: 100%; height: auto; }}
        </style>
    </head>
    <body>
        <h1>Backtest Report</h1>
        <div class="summary">
            <div class="stat"><span class="stat-label">Initial Capital</span><span class="stat-value">${initial_capital:.2f}</span></div>
            <div class="stat"><span class="stat-label">Final Capital</span><span class="stat-value">${final_capital:.2f}</span></div>
            <div class="stat"><span class="stat-label">Total PnL</span><span class="stat-value">{total_pnl_pct:+.2f}% (${total_pnl_dollar:+.2f})</span></div>
            <div class="stat"><span class="stat-label">Total Trades</span><span class="stat-value">{total_trades}</span></div>
            <div class="stat"><span class="stat-label">Win Rate</span><span class="stat-value">{win_rate:.2f}%</span></div>
            <div class="stat"><span class="stat-label">Avg PnL</span><span class="stat-value">{avg_pnl_pct:+.2f}% (${avg_pnl_dollar:+.2f})</span></div>
            <div class="stat"><span class="stat-label">Half-TP Hits</span><span class="stat-value">{half_hits}</span></div>
            <div class="stat"><span class="stat-label">Half-TP Revisited Hits</span><span class="stat-value">{half_revisited_hits}</span></div>
            <div class="stat"><span class="stat-label">Break-Even Hits</span><span class="stat-value">{break_even_hits}</span></div>
        </div>
        <h2>Equity Curve</h2>
        <div class="chart">
            <img src="data:image/png;base64,{chart_base64}" alt="Equity Curve" />
        </div>
        <h2>Trade Details</h2>
        <table>
            <thead>
                <tr>
                    <th>Entry Time</th>
                    <th>Exit Time</th>
                    <th>Side</th>
                    <th>Entry Price</th>
                    <th>Exit Price</th>
                    <th>PnL %</th>
                    <th>PnL $</th>
                    <th>Status</th>
                    <th>Half TP</th>
                    <th>Full TP</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
        <p><em>Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</em></p>
    </body>
    </html>
    """
    with open(output_path, 'w') as f:
        f.write(html)

def run_backtest(interval_label, num_candles, initial_capital, leverage, position_fraction):
    interval_api = INTERVAL_MAP[interval_label]
    symbol = "BTCUSDT"

    console.print(f"[bold]Fetching {num_candles} candles for {interval_label}...[/bold]")
    candles = None
    for attempt in range(3):
        candles = fetch_completed_candles(interval_api, num_candles, interval_label)
        if candles is not None and len(candles) >= 2:
            break
        time.sleep(2)
    if candles is None or len(candles) < 2:
        console.print("[red]Failed to fetch enough candles. Exiting.[/red]")
        return

    console.print(f"[green]Fetched {len(candles)} candles.[/green]")

    active_trade = None
    trades = []
    capital = initial_capital
    equity_curve = []

    for i in range(1, len(candles)):
        prev_candle = candles[i-1]
        curr_candle = candles[i]

        if active_trade is not None and active_trade['status'] == 'open':
            result = check_trade_hit(active_trade, curr_candle)
            if result in ('half', 'tp', 'sl', 'half_revisited', 'break_even'):
                if result == 'half':
                    pass
                elif result in ('tp', 'sl', 'half_revisited', 'break_even'):
                    pnl_percent = active_trade['pnl_percent']
                    notional = capital * position_fraction * leverage
                    dollar_pnl = notional * (pnl_percent / 100.0)
                    active_trade['pnl_dollar'] = dollar_pnl
                    active_trade['capital_before'] = capital
                    capital += dollar_pnl
                    active_trade['capital_after'] = capital
                    trades.append(active_trade)
                    update_trade_log(active_trade)
                    active_trade = None

        if active_trade is None:
            pattern = check_engulfing(prev_candle, curr_candle)
            if pattern:
                side = 'long' if pattern == 'bullish' else 'short'
                entry_price = curr_candle['close']
                signal_record = {
                    'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                    'symbol': symbol,
                    'interval': interval_label,
                    'pattern': f"{pattern}_engulfing",
                    'prev_candle': {k: v for k, v in prev_candle.items() if k != 'volume'},
                    'curr_candle': {k: v for k, v in curr_candle.items() if k != 'volume'},
                }
                trade = create_trade(signal_record, entry_price, side, interval_label, curr_candle['start_time'])
                trade['entry_time'] = curr_candle['start_time'].isoformat()
                trade['capital_before'] = capital
                active_trade = trade

        equity_curve.append({
            'time': curr_candle['start_time'].isoformat(),
            'capital': capital,
            'price': curr_candle['close']
        })

    # Close any open trade at end
    if active_trade is not None and active_trade['status'] == 'open':
        last_candle = candles[-1]
        close_price = last_candle['close']
        if active_trade['side'] == 'long':
            pnl_percent = (close_price - active_trade['entry_price']) / active_trade['entry_price'] * 100
        else:
            pnl_percent = (active_trade['entry_price'] - close_price) / active_trade['entry_price'] * 100
        active_trade['status'] = 'close_at_end'
        active_trade['close_price'] = close_price
        active_trade['close_time'] = last_candle['start_time'].isoformat()
        active_trade['pnl_percent'] = pnl_percent
        notional = capital * position_fraction * leverage
        dollar_pnl = notional * (pnl_percent / 100.0)
        active_trade['pnl_dollar'] = dollar_pnl
        active_trade['capital_before'] = capital
        capital += dollar_pnl
        active_trade['capital_after'] = capital
        trades.append(active_trade)
        update_trade_log(active_trade)
        console.print(f"[yellow]Trade still open at end – closed at {close_price:.2f} with PnL {pnl_percent:.2f}% ({dollar_pnl:+.2f}$)[/yellow]")

    # Save equity curve
    with open(EQUITY_LOG_PATH, "w") as f:
        json.dump(equity_curve, f, indent=2)

    # --- Summary ---
    console.print("\n[bold]===== BACKTEST SUMMARY =====[/bold]")
    console.print(f"Period: {candles[0]['start_time']} to {candles[-1]['start_time']}")
    console.print(f"Total candles: {len(candles)}")
    console.print(f"Total trades: {len(trades)}")

    summary = {
        'total_trades': len(trades),
        'initial_capital': initial_capital,
        'final_capital': capital,
        'total_pnl_dollar': capital - initial_capital,
        'total_pnl_pct': (capital - initial_capital) / initial_capital * 100 if initial_capital else 0,
    }

    if len(trades) > 0:
        wins = sum(1 for t in trades if t['pnl_percent'] > 0)
        losses = sum(1 for t in trades if t['pnl_percent'] < 0)
        win_rate = (wins / len(trades)) * 100
        avg_pnl_pct = sum(t['pnl_percent'] for t in trades) / len(trades)
        avg_pnl_dollar = sum(t.get('pnl_dollar', 0) for t in trades) / len(trades)
        half_hits = sum(1 for t in trades if t.get('half_tp_hit', False))
        half_revisited_hits = sum(1 for t in trades if t.get('status') == 'half_revisited')
        break_even_hits = sum(1 for t in trades if t.get('status') == 'break_even')
        summary.update({
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'avg_pnl_pct': avg_pnl_pct,
            'avg_pnl_dollar': avg_pnl_dollar,
            'half_hits': half_hits,
            'half_revisited_hits': half_revisited_hits,
            'break_even_hits': break_even_hits
        })
        console.print(f"Wins: {wins} | Losses: {losses} | Win Rate: {win_rate:.2f}%")
        console.print(f"Initial capital: ${initial_capital:.2f}")
        console.print(f"Final capital: ${capital:.2f}")
        console.print(f"Total PnL: ${capital - initial_capital:+.2f} ({summary['total_pnl_pct']:+.2f}%)")
        console.print(f"Average trade PnL (without leverage): {avg_pnl_pct:+.2f}%")
        console.print(f"Average trade PnL (with leverage & sizing): ${avg_pnl_dollar:+.2f}")
        console.print(f"Half-TP hits: {half_hits}")
        console.print(f"Half-TP revisited hits: {half_revisited_hits}")
        console.print(f"Break-even hits: {break_even_hits}")
    else:
        console.print("No trades executed.")
        summary['wins'] = 0
        summary['losses'] = 0
        summary['win_rate'] = 0
        summary['avg_pnl_pct'] = 0
        summary['avg_pnl_dollar'] = 0
        summary['half_hits'] = 0
        summary['half_revisited_hits'] = 0
        summary['break_even_hits'] = 0

    # Export PNG and HTML
    if len(equity_curve) > 1:
        plot_equity_curve(equity_curve, EQUITY_PNG_PATH)
        console.print(f"[green]Equity curve saved to {EQUITY_PNG_PATH}[/green]")
    else:
        console.print("[yellow]Not enough equity data points for chart.[/yellow]")

    generate_html_report(summary, trades, equity_curve, REPORT_HTML_PATH)
    console.print(f"[green]HTML report saved to {REPORT_HTML_PATH}[/green]")

    console.print(f"\nDetailed trade log saved to: {TRADE_LOG_PATH}")
    console.print(f"Equity curve JSON saved to: {EQUITY_LOG_PATH}")

def main():
    console.print("[bold green]BTC/USDT Engulfing Backtester with Leverage & Position Sizing[/bold green]")
    interval_input = input("Enter timeframe (e.g., 1m, 5m, 1h) [default: 1m]: ").strip() or '1m'
    if interval_input not in INTERVAL_MAP:
        console.print(f"[red]Unsupported. Using 1m. Supported: {', '.join(INTERVAL_MAP.keys())}[/red]")
        interval_input = '1m'

    try:
        num_candles = int(input("Enter number of candles to backtest [default: 500]: ").strip() or '500')
        if num_candles < 2:
            console.print("[red]Number of candles must be at least 2.[/red]")
            return
    except ValueError:
        console.print("[red]Invalid number, using 500.[/red]")
        num_candles = 500

    try:
        initial_capital = float(input("Enter starting capital (USD) [default: 1000]: ").strip() or '1000')
        if initial_capital <= 0:
            console.print("[red]Capital must be positive. Using 1000.[/red]")
            initial_capital = 1000
    except ValueError:
        initial_capital = 1000

    try:
        leverage = float(input("Enter leverage (e.g., 10 for 10x) [default: 1]: ").strip() or '1')
        if leverage < 1:
            console.print("[red]Leverage must be at least 1. Using 1.[/red]")
            leverage = 1
    except ValueError:
        leverage = 1

    try:
        position_fraction = float(input("Enter position size as % of capital per trade (e.g., 5 for 5%) [default: 10]: ").strip() or '10')
        position_fraction = position_fraction / 100.0
        if position_fraction <= 0 or position_fraction > 1:
            console.print("[red]Position fraction must be between 0 and 100. Using 10%.[/red]")
            position_fraction = 0.10
    except ValueError:
        position_fraction = 0.10

    run_backtest(interval_input, num_candles, initial_capital, leverage, position_fraction)

if __name__ == "__main__":
    main()