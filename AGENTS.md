# AGENTS.md

## Repo Structure
- **Purpose**: Trading bot for detecting engulfing candlestick patterns and executing trades on Bybit and Nobitex exchanges.
- **Main directories**:
  - `bot/`: Signal detection and backtesting scripts
  - `Bybit/`: Bybit-specific data fetchers (OHLC, price)
  - `Nobitex/`: Nobitex-specific data fetchers (OHLC, price)
  - `assets/`: Documentation and images

## Key Scripts
- **Signal detection**: `bot/bybit/find-signal.py`, `bot/Nobitex/find-signal.py` - Live monitoring with engulfing pattern detection
- **Backtesting**: `bot/bybit/backtest.py` - Backtest engulfing strategy with TP/SL
- **Data fetchers**: `Bybit/OHLC.py`, `Nobitex/OHLC.py` - Historical candle data
- **Price monitors**: `Bybit/price.py`, `Nobitex/price.py` - Live price tracking

## Architecture Notes
- **Pattern**: Engulfing candlestick detection (bullish/bearish) with configurable TP/SL percentages
- **TP/SL defaults**: TP=0.5%, SL=0.25%, Half-TP=0.25% (Bybit); TP=1.0%, SL=0.5%, Half-TP=0.5% (backtest)
- **Data sources**: Bybit API (`api.bybit.com/v5/market/`), Nobitex API (`apiv2.nobitex.ir/market/`)
- **Fallback**: Bybit scripts fall back to Binance API if Bybit is unreachable

## Execution Commands
```bash
# Run signal detection (Bybit)
python bot/bybit/find-signal.py

# Run signal detection (Nobitex)
python bot/Nobitex/find-signal.py

# Run backtest (Bybit)
python bot/bybit/backtest.py

# Fetch OHLC data (Bybit)
python Bybit/OHLC.py

# Fetch OHLC data (Nobitex)
python Nobitex/OHLC.py

# Monitor price (Bybit)
python Bybit/price.py

# Monitor price (Nobitex)
python Nobitex/price.py
```

## Input Conventions
- All scripts accept timeframe input: `1m`, `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `12h`, `1d`, `1w`, `1M`
- Also accept raw API codes: `1`, `5`, `15`, `30`, `60`, `120`, `240`, `360`, `720`, `D`, `W`, `M`
- Default timeframe: `1m`

## Output Directories
- `signals_output/`: Generated signal charts and trade logs from `find-signal.py`
- `backtest_output/`: Backtest reports, equity curves, and trade logs from `backtest.py`

## Dependencies
- `requests` - HTTP requests
- `rich` - Terminal rendering
- `matplotlib` - Chart generation
- `urllib3` - Retry logic

## Quirks
- Nobitex uses `BTCUSDT` symbol for API but displays as `BTC/IRT` in some scripts
- Bybit scripts use dual endpoints: `api.bybit.com` and `api.bytick.com` with fallback
- Price monitoring scripts require user input for coin/currency symbols
- All live scripts use `Live` from `rich` for terminal updates (refresh every 0.5-2 seconds)
- Candle count kept in memory: 30 candles default for live monitoring

## Data Format
Candles are stored as dicts with keys:
- `start_time`: datetime object (UTC)
- `open`, `high`, `low`, `close`: float prices
- `volume`: float

## Trade Logic
- Engulfing pattern triggers trade: bullish → long, bearish → short
- Entry price = close of engulfing candle
- Trade status: `open`, `tp`, `sl`, `close_at_end`
- PnL calculated with leverage and position sizing in backtest
