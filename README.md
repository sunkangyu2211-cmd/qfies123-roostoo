# Roostoo Autonomous Trading Bot

An autonomous crypto trading bot for Roostoo's mock exchange, designed for the competitive hackathon. Combines momentum and mean-reversion signals with strict risk management to maximize risk-adjusted returns.

## Strategy Rationale

Crypto markets exhibit both trending behavior and mean-reversion patterns across different timeframes. This bot exploits both:

- **RSI mean-reversion**: Identifies oversold (<35) and overbought (>65) conditions on 1h candles. Crypto markets frequently overshoot and revert, making RSI a reliable entry/exit filter.
- **EMA crossover (12/26)**: Captures medium-term trend shifts. When the fast EMA crosses above the slow EMA, it confirms building momentum.
- **24h momentum**: Filters for coins already moving significantly (>2%), riding continuation while avoiding choppy markets.
- **Fear & Greed macro filter**: Suppresses BUY signals during extreme greed (>75) when reversals are likely, and allows BUYs during extreme fear (<25) when bargains emerge.

The composite scoring system requires at least 2 of 3 indicators to agree before acting, reducing false signals while maintaining responsiveness.

## Architecture

```
+------------------+     +------------------+     +------------------+
|   config.yaml    |     |   .env (secrets)  |     |  state/positions |
+--------+---------+     +--------+---------+     +--------+---------+
         |                         |                        |
         v                         v                        v
+--------+---------+     +--------+---------+     +--------+---------+
|     bot.py       |---->| api/client.py    |     | logger/trade_log |
|  (orchestrator)  |     | (Roostoo REST)   |     | (JSON logging)   |
+--------+---------+     +------------------+     +------------------+
         |
    +----+----+----+----+
    |         |         |
    v         v         v
+---+---+ +---+---+ +---+---+
| data/ | |strat/ | | risk/ |
| feeds | |multi  | |manager|
+---+---+ +---+---+ +---+---+
    |         |
    v         v
 Binance    ta lib
 (ccxt)   (RSI, EMA)
 F&G API
```

**Data flow per cycle:**
1. Sync server time
2. Fetch OHLCV (Binance) + Fear & Greed
3. Fetch Roostoo prices + balance
4. Log portfolio snapshot
5. Check kill switch -> skip if triggered
6. Check stop-losses -> exit positions
7. Generate signals -> risk check -> place orders
8. Cancel stale pending orders
9. Sleep until next cycle

## Quickstart

```bash
git clone <repo-url> && cd roostoo-bot
cp .env.example .env  # Edit with your API_KEY and SECRET_KEY
make install && make run
```

## Configuration Reference

| Parameter | Location | Default | Description |
|-----------|----------|---------|-------------|
| `exchange.base_url` | config.yaml | `https://mock-api.roostoo.com` | API base URL |
| `exchange.poll_interval_seconds` | config.yaml | `900` | Seconds between trading cycles |
| `exchange.stale_order_minutes` | config.yaml | `30` | Cancel limit orders older than this |
| `trading.pairs` | config.yaml | `[BTC/USD, ETH/USD, SOL/USD]` | Trading pairs |
| `trading.max_position_pct` | config.yaml | `0.20` | Max portfolio % per coin |
| `trading.stop_loss_pct` | config.yaml | `0.05` | Exit if position drops this % |
| `trading.kill_switch_drawdown` | config.yaml | `0.15` | Pause all trading at this drawdown |
| `trading.kill_switch_pause_minutes` | config.yaml | `240` | Cooldown after kill switch (minutes) |
| `trading.min_trade_usd` | config.yaml | `10.0` | Minimum order notional |
| `trading.limit_offset_pct` | config.yaml | `0.002` | Limit order offset from market |
| `strategy.rsi_period` | config.yaml | `14` | RSI lookback period |
| `strategy.rsi_oversold` | config.yaml | `35` | RSI oversold threshold |
| `strategy.rsi_overbought` | config.yaml | `65` | RSI overbought threshold |
| `strategy.ema_fast` | config.yaml | `12` | Fast EMA period |
| `strategy.ema_slow` | config.yaml | `26` | Slow EMA period |
| `strategy.momentum_threshold_pct` | config.yaml | `2.0` | 24h change threshold (%) |
| `strategy.min_signal_score` | config.yaml | `2` | Min score to trigger trade |
| `data.ohlcv_interval` | config.yaml | `1h` | Candle interval |
| `data.ohlcv_limit` | config.yaml | `100` | Number of candles to fetch |
| `data.cache_ttl_seconds` | config.yaml | `300` | OHLCV cache lifetime |
| `logging.log_file` | config.yaml | `logs/trades.jsonl` | Trade log path |
| `logging.log_level` | config.yaml | `INFO` | Logging verbosity |
| `DRY_RUN` | env var | `false` | Skip order placement if `true` |
| `API_KEY` | env var | — | Roostoo API key |
| `SECRET_KEY` | env var | — | Roostoo secret key |

## Viewing Metrics

```bash
make metrics
```

Outputs a formatted table with:
- Total return
- Sharpe ratio (annualized)
- Sortino ratio (annualized)
- Calmar ratio (annualized return / max drawdown)
- Max drawdown

## Debugging Guide

**Bot won't start:**
- Verify `.env` has `API_KEY` and `SECRET_KEY` set
- Check `config.yaml` syntax with `python -c "import yaml; yaml.safe_load(open('config.yaml'))"`

**No trades being placed:**
- Check if `DRY_RUN=true` in environment
- Review signal scores in logs: `grep '"type": "signal"' logs/trades.jsonl | tail -5`
- Kill switch may be active: `grep 'kill_switch' logs/trades.jsonl | tail -1`
- Verify balance: signals require sufficient free balance

**Orders rejected by API:**
- Check precision: quantity and price must match `exchangeInfo` rules
- Verify notional: `quantity * price` must exceed `MiniOrder`
- Check clock drift in logs (>60s will cause rejections)

**View recent activity:**
```bash
tail -20 logs/trades.jsonl | python -m json.tool
```

**Run in debug mode:**
```bash
LOG_LEVEL=DEBUG make run
```

## Performance Summary

| Metric | Value |
|--------|-------|
| Start Value | $50,000.00 |
| End Value | — |
| Total Return | — |
| Sharpe Ratio | — |
| Sortino Ratio | — |
| Calmar Ratio | — |
| Max Drawdown | — |
| Total Trades | — |
| Win Rate | — |

*Updated after each competition run with `make metrics`.*

## Creating a Custom Strategy

All strategies extend `BaseStrategy` from `strategy/base.py` and implement a single method: `generate_signal(market_data) -> Signal`.

### Step 1: Create your strategy file

Add a new file in `strategy/`, e.g. `strategy/my_strategy.py`:

```python
import logging
from typing import Any

from .base import BaseStrategy, Signal

logger = logging.getLogger(__name__)


class MyStrategy(BaseStrategy):
    def __init__(self, config: dict[str, Any]) -> None:
        # Read your custom params from config.yaml's strategy section
        self.my_threshold = config.get("my_threshold", 0.5)

    def generate_signal(self, market_data: dict[str, Any]) -> Signal:
        pair = market_data["pair"]
        ohlcv = market_data.get("ohlcv")          # pd.DataFrame (OHLCV candles)
        change_24h = market_data.get("change_24h", 0.0)  # 24h % change
        fear_greed = market_data.get("fear_greed")  # int 0-100 or None

        # --- Your logic here ---
        action = "HOLD"
        confidence = 0.0
        reason = "No signal"

        return Signal(pair=pair, action=action, confidence=confidence, reason=reason)
```

The `Signal` dataclass has four fields:
- `pair` — trading pair, e.g. `"BTC/USD"`
- `action` — one of `"BUY"`, `"SELL"`, `"HOLD"`
- `confidence` — float from 0.0 to 1.0 (scales position size for BUY orders)
- `reason` — human-readable string logged to the audit trail

### Step 2: Wire it into the bot

In `bot.py`, swap the strategy import and instantiation:

```python
# Replace this:
from strategy.multi_signal import MultiSignalStrategy
# With this:
from strategy.my_strategy import MyStrategy
```

Then in `TradingBot.__init__`, change:

```python
self.strategy = MyStrategy(self.config["strategy"])
```

### Step 3: Add config parameters

Add any custom parameters under the `strategy:` section of `config.yaml`:

```yaml
strategy:
  my_threshold: 0.5
  # ... your params here
```

### Step 4: Add tests

Create `tests/test_my_strategy.py` following the pattern in `tests/test_strategy.py`. Each test builds a `market_data` dict and asserts the returned `Signal`:

```python
from strategy.my_strategy import MyStrategy

def test_basic_signal():
    strategy = MyStrategy({"my_threshold": 0.5})
    market_data = {"pair": "BTC/USD", "ohlcv": None, "change_24h": 3.0, "fear_greed": 50}
    signal = strategy.generate_signal(market_data)
    assert signal.action in ("BUY", "SELL", "HOLD")
    assert 0.0 <= signal.confidence <= 1.0
```

### How the strategy fits into the pipeline

```
bot._run_cycle()
    │
    ├── Fetch OHLCV, Fear & Greed, Roostoo prices
    ├── Build market_data dict per pair
    ├── strategy.generate_signal(market_data)  ◄── YOUR CODE
    ├── risk_manager.check_can_trade()          (blocks unsafe trades)
    ├── risk_manager.size_position()            (uses signal.confidence)
    └── client.place_order()                    (executes on Roostoo)
```

The risk manager and order execution are strategy-agnostic — any `Signal` your strategy returns flows through the same risk checks and order pipeline.

## Testing

```bash
make test    # Run all unit tests
make lint    # Format with black + check with flake8
```

## Project Structure

```
roostoo-bot/
├── api/client.py          # Roostoo REST API wrapper (7 endpoints)
├── strategy/base.py       # Abstract strategy interface + Signal dataclass
├── strategy/multi_signal.py # RSI + EMA + momentum composite strategy
├── risk/manager.py        # Position limits, stop-loss, kill switch
├── data/feeds.py          # Binance OHLCV, Fear & Greed, Roostoo ticker
├── logger/trade_log.py    # Structured JSONL logging + log rotation
├── metrics/calculator.py  # Sortino, Sharpe, Calmar, max drawdown
├── bot.py                 # Main orchestration loop
├── config.yaml            # All tunable parameters
├── tests/                 # Unit tests for client, strategy, risk
├── state/positions.json   # Persisted entry prices (survives restarts)
└── logs/trades.jsonl      # Full audit trail
```
