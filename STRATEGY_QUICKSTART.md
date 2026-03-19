# Strategy Quick Start Guide

## Available Strategies

### 1️⃣ RSIOnly (BEST FOR ACCURACY)
```python
from strategy.rsi_only import RSIOnlyStrategy

config = {
    'rsi_period': 14,
    'rsi_oversold': 30,
    'rsi_overbought': 70,
}
strat = RSIOnlyStrategy(config)
```
- **Best return**: 10.31%
- **Win rate**: 90.9%
- **Trading frequency**: Low (11 trades/month)
- **Best for**: Conservative traders seeking high-confidence entries

---

### 2️⃣ MACD (BEST FOR ACTIVITY)
```python
from strategy.macd import MACDStrategy

config = {
    'macd_fast': 12,
    'macd_slow': 26,
    'macd_signal': 9,
}
strat = MACDStrategy(config)
```
- **Return**: 5.72%
- **Win rate**: 39.0%
- **Trading frequency**: High (82 trades/month)
- **Best for**: Active traders comfortable with more signals

---

### 3️⃣ ADXTrend (BEST FOR TREND TRADING)
```python
from strategy.adx_trend import ADXTrendStrategy

config = {
    'adx_period': 14,
    'adx_threshold': 25.0,
    'ma_period': 20,
}
strat = ADXTrendStrategy(config)
```
- **Return**: 5.64%
- **Win rate**: 44.4%
- **Trading frequency**: Medium (36 trades/month)
- **Best for**: Trend confirmation

---

### 4️⃣ MAcrossover (CLASSIC APPROACH)
```python
from strategy.ma_crossover import MAcrossoverStrategy

config = {
    'ma_fast': 20,
    'ma_slow': 50,
}
strat = MAcrossoverStrategy(config)
```
- **Return**: 2.54%
- **Win rate**: 50%
- **Trading frequency**: Medium
- **Best for**: Learning classic indicators

---

### 5️⃣ MultiSignal (COMPOSITE)
```python
from strategy.multi_signal import MultiSignalStrategy

config = {
    'rsi_period': 14,
    'rsi_oversold': 35,
    'rsi_overbought': 65,
    'ema_fast': 12,
    'ema_slow': 26,
    'momentum_threshold_pct': 2.0,
    'min_signal_score': 2,  # Require 2+ signals
}
strat = MultiSignalStrategy(config)
```
- **Return**: 3.68%
- **Best for**: Multi-signal confirmation

---

### 6️⃣ SimpleMomentum (SIMPLEST)
```python
from strategy.momentum_only import SimpleMomentumStrategy

config = {
    'momentum_threshold_pct': 1.5,
}
strat = SimpleMomentumStrategy(config)
```
- **Return**: 0.78%
- **Best for**: Experimentation only

---

### 7️⃣ BollingerBands (MEAN REVERSION)
```python
from strategy.bollinger_bands import BollingerBandsStrategy

config = {
    'bb_period': 20,
    'bb_std': 2.0,
}
strat = BollingerBandsStrategy(config)
```
- **Return**: -0.54% (negative)
- **Best for**: Not recommended in current settings

---

### 8️⃣ Stochastic (NOT RECOMMENDED)
```python
from strategy.stochastic import StochasticStrategy

config = {
    'k_period': 14,
    'd_period': 3,
    'stoch_oversold': 20.0,
    'stoch_overbought': 80.0,
}
strat = StochasticStrategy(config)
```
- **Return**: -11.84% (WORST)
- **Best for**: NOT RECOMMENDED

---

## How to Test a Strategy

### Option 1: Interactive Testing (Jupyter)
```bash
cd notebooks/
jupyter notebook backtest.ipynb
```

In Cell 7, uncomment and modify:
```python
from strategy.rsi_only import RSIOnlyStrategy

feeds = {pair: fetch_binance_feed(pair, days=DAYS) for pair in PAIRS}
cerebro = build_cerebro(
    feeds=feeds,
    strategy_class=RSIOnlyStrategy,
    strategy_config={'rsi_period': 14, 'rsi_oversold': 30, 'rsi_overbought': 70},
    fear_greed_map=fng,
)
results = cerebro.run()
cerebro.plot(style='candlestick')
extract_metrics(results[0])
```

### Option 2: Compare All Strategies
```bash
python notebooks/compare_strategies.py
```

Output:
```
STRATEGY COMPARISON - RANKED BY RETURN

Rank       Strategy Return %  Trades Win Rate %
   1        RSIOnly   10.31%      11      90.9%
   2           MACD    5.72%      82      39.0%
   3       ADXTrend    5.64%      36      44.4%
   ...
```

### Option 3: Optimize Top Strategies
```bash
python notebooks/optimize_top_strategies.py
```

Finds best parameters for:
- RSIOnly (grid search over period, oversold, overbought)
- MACD (grid search over fast, slow, signal)
- ADXTrend (grid search over period, threshold, ma_period)

---

## Comparison Matrix

| Strategy | Return | Win % | Trades | DD | Recommendation |
|----------|--------|-------|--------|-----|-----------------|
| **RSIOnly** | **10.31%** | **90.9%** | 11 | 3.59% | ⭐⭐⭐ BEST |
| **MACD** | 5.72% | 39.0% | 82 | 4.78% | ⭐⭐ Good |
| **ADXTrend** | 5.64% | 44.4% | 36 | 6.08% | ⭐⭐ Good |
| MultiSignal | 3.68% | 25.0% | 4 | 2.57% | ⭐ Fair |
| MAcrossover | 2.54% | 50.0% | 28 | 4.65% | ⭐ Fair |
| SimpleMomentum | 0.78% | 40.4% | 47 | 12.63% | ❌ Avoid |
| BollingerBands | -0.54% | 64.0% | 25 | 11.28% | ❌ Avoid |
| **Stochastic** | **-11.84%** | 60.7% | 61 | 14.84% | ❌ **AVOID** |

---

## Strategy Selection Guide

### If you want...

**Highest Returns**
→ Use `RSIOnly` with optimized parameters

**Most Signals**
→ Use `MACD` (82 trades) with proper risk management

**Trend Following**
→ Use `ADXTrend` for trend confirmation

**Classic Approach**
→ Use `MAcrossover` for learning/testing

**Multi-Signal Confirmation**
→ Tune `MultiSignal` with lower min_signal_score

**Conservative**
→ Use `RSIOnly` with tight stops

**Aggressive**
→ Use `MACD` with position sizing

---

## Parameter Tuning Tips

### RSI Tuning
```python
# Conservative (fewer trades, higher win rate)
config = {'rsi_period': 14, 'rsi_oversold': 25, 'rsi_overbought': 75}

# Aggressive (more trades, lower win rate)
config = {'rsi_period': 14, 'rsi_oversold': 35, 'rsi_overbought': 65}
```

### MACD Tuning
```python
# Conservative (longer periods)
config = {'macd_fast': 10, 'macd_slow': 28, 'macd_signal': 11}

# Aggressive (shorter periods)
config = {'macd_fast': 12, 'macd_slow': 26, 'macd_signal': 9}
```

### ADX Tuning
```python
# Conservative (higher threshold)
config = {'adx_period': 14, 'adx_threshold': 30.0, 'ma_period': 20}

# Aggressive (lower threshold)
config = {'adx_period': 14, 'adx_threshold': 20.0, 'ma_period': 20}
```

---

## Common Mistakes

❌ **Overfitting to one backtest period**
- Always test on multiple time periods
- Check results with different DAYS values

❌ **Ignoring drawdown**
- A 20% return with 50% drawdown is worse than 5% return with 5% drawdown
- Always check Max DD alongside returns

❌ **Trading too frequently**
- More trades = more slippage, more commissions
- Higher quality signals beat higher quantity signals
- RSIOnly proves this: 11 trades → 10.31%, MACD: 82 trades → 5.72%

❌ **Optimizing without walk-forward validation**
- Grid search finds past optimal params, not future ones
- Always test optimized params on unseen data

❌ **Using negative-return strategies**
- Stochastic (-11.84%) and BollingerBands (-0.54%) consistently lose
- Stick to proven winners

---

## Files Generated

After running tests:
- `results/strategy_comparison.csv` - Full results
- `results/rsi_optimization.csv` - RSI parameter sweep
- `results/macd_optimization.csv` - MACD parameter sweep
- `results/adx_optimization.csv` - ADX parameter sweep
- `results/backtest_chart.png` - Latest backtest chart
- `results/trades.csv` - Trade log

---

## Getting Better Results

1. **Extend backtest period** (currently 30 days)
   ```python
   DAYS = 90  # or 180, 365
   ```

2. **Optimize parameters** for your specific assets
   ```bash
   python notebooks/optimize_top_strategies.py
   ```

3. **Ensemble strategies** (combine multiple)
   ```python
   # TODO: Create ensemble that votes with RSI + MACD
   ```

4. **Add more assets** to the pairs list
   ```yaml
   trading:
     pairs:
       - BTC/USD
       - ETH/USD
       - SOL/USD
       - ADA/USD  # Add more
       - XRP/USD
   ```

5. **Adjust risk parameters** in config.yaml
   ```yaml
   trading:
     stop_loss_pct: 0.05      # 5% stop loss
     max_position_pct: 0.20   # Risk 20% per trade
     kill_switch_drawdown: 0.15  # Kill if 15% down
   ```

---

## Questions?

See `STRATEGY_ANALYSIS.md` for detailed analysis of each strategy.

Run `python notebooks/compare_strategies.py` to generate fresh results.

Check `notebooks/backtest.ipynb` for interactive testing.
