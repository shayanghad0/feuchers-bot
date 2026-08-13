# Feuchers Bot - Engulfing Candlestick Trading Bot

A trading bot for detecting engulfing candlestick patterns and executing trades on **Bybit** and **Nobitex** exchanges. Built with Python, this bot provides live signal detection, backtesting capabilities, and real-time price monitoring.

## Features

- **Engulfing Pattern Detection**: Identifies bullish and bearish engulfing candlestick patterns
- **Multi-Exchange Support**: Works with Bybit and Nobitex APIs
- **Live Monitoring**: Real-time price tracking and signal detection
- **Backtesting**: Test trading strategies with historical data
- **TP/SL Management**: Configurable take-profit and stop-loss levels
- **Visual Output**: Generates charts and trade logs

## Quick Start

### Prerequisites
- Python 3.7+
- Required packages: `requests`, `rich`, `matplotlib`, `urllib3`

```bash
pip install requests rich matplotlib urllib3
```

### Running the Bot

#### Signal Detection (Live)
```bash
# Bybit
python bot/bybit/find-signal.py

# Nobitex
python bot/Nobitex/find-signal.py
```

#### Backtesting
```bash
python bot/bybit/backtest.py
```

#### Price Monitoring
```bash
# Bybit
python Bybit/price.py

# Nobitex
python Nobitex/price.py
```

#### Fetch Historical Data
```bash
# Bybit OHLC data
python Bybit/OHLC.py

# Nobitex OHLC data
python Nobitex/OHLC.py
```

## Configuration

### Timeframes
All scripts accept the following timeframe inputs:
- `1m`, `5m`, `15m`, `30m`
- `1h`, `2h`, `4h`, `6h`, `12h`
- `1d`, `1w`, `1M`

Or raw API codes: `1`, `5`, `15`, `30`, `60`, `120`, `240`, `360`, `720`, `D`, `W`, `M`

### Trading Parameters
- **Take Profit (TP)**: 0.5% (Bybit live), 1.0% (backtest)
- **Stop Loss (SL)**: 0.25% (Bybit live), 0.5% (backtest)
- **Half TP**: 0.25% (Bybit live), 0.5% (backtest)

## Project Structure

```
feuchers bot/
├── bot/
│   ├── bybit/
│   │   ├── find-signal.py    # Live signal detection for Bybit
│   │   └── backtest.py       # Backtesting for Bybit
│   └── Nobitex/
│       └── find-signal.py    # Live signal detection for Nobitex
├── Bybit/
│   ├── OHLC.py              # Historical candle data fetcher
│   ├── LOHLC.py             # Live OHLC monitoring
│   └── price.py             # Live price monitoring
├── Nobitex/
│   ├── OHLC.py              # Historical candle data fetcher
│   ├── LOHLC.py             # Live OHLC monitoring
│   └── price.py             # Live price monitoring
├── assets/
│   └── docs/                # Documentation and images
├── README.md                # This file
├── AGENTS.md                # Development instructions
└── .gitignore
```

## Output Files

- `signals_output/`: Contains signal charts and trade logs from live detection
- `backtest_output/`: Contains backtest reports, equity curves, and trade logs

## API Endpoints

- **Bybit**: `api.bybit.com/v5/market/` (with fallback to `api.bytick.com`)
- **Nobitex**: `apiv2.nobitex.ir/market/`
- **Fallback**: Binance API (`api.binance.com`) for Bybit scripts

## Trading Logic

1. **Pattern Detection**: The bot identifies engulfing candlestick patterns
   - Bullish engulfing: Small bearish candle followed by larger bullish candle
   - Bearish engulfing: Small bullish candle followed by larger bearish candle

2. **Trade Execution**:
   - Bullish pattern → Long position
   - Bearish pattern → Short position
   - Entry price = Close of engulfing candle

3. **Risk Management**:
   - Take Profit: Configurable percentage above/below entry
   - Stop Loss: Configurable percentage below/above entry
   - Half TP: Partial take-profit at half the TP distance

4. **Position Management**:
   - Only one active trade at a time
   - Trades close on TP/SL hit or at end of monitoring

## Documentation

- See `assets/docs/` for additional documentation
- See `AGENTS.md` for development instructions

## License

This project is provided as-is for educational purposes.

---

**Note**: This bot is for educational and testing purposes only. Use at your own risk. Always test thoroughly with backtesting before using with real funds.
