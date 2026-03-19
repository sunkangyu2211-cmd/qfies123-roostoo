"""
Quick parameter optimization - tests fewer parameters but runs much faster.

Good for identifying promising directions before doing full grid search.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import yaml

from backtest.bt_strategy import build_cerebro, extract_metrics
from backtest.data_feed import fetch_binance_feed, fetch_fear_greed
from strategy import RSIOnlyStrategy

# Configuration
config_path = Path(__file__).parent.parent / 'config.yaml'
with open(config_path) as f:
    config = yaml.safe_load(f)

PAIRS = config['trading']['pairs']
DAYS = 30
INITIAL_CASH = 50_000.0

print("="*80)
print("QUICK PARAMETER OPTIMIZATION FOR RSI (BEST STRATEGY)")
print("="*80)

# Fetch data once
print("\nFetching data...")
raw_feeds = {}
for pair in PAIRS:
    raw_feeds[pair] = fetch_binance_feed(pair, days=DAYS)
fng = fetch_fear_greed(days=DAYS)
print(f"Data loaded: {len(raw_feeds)} pairs")

# Test promising RSI parameter ranges
print("\nTesting RSI oversold values (best one only):\n")

oversold_values = [20, 25, 30, 35, 40]
best_oversold = None
best_return = -999
best_config = None

for oversold in oversold_values:
    print(f"  Testing RSI oversold={oversold:2d}...", end=' ', flush=True)

    feeds = {pair: fetch_binance_feed(pair, days=DAYS) for pair in PAIRS}

    cerebro = build_cerebro(
        feeds=feeds,
        strategy_class=RSIOnlyStrategy,
        strategy_config={
            'rsi_period': 14,
            'rsi_oversold': oversold,
            'rsi_overbought': 100 - oversold,  # Mirror
        },
        fear_greed_map=fng,
        cash=INITIAL_CASH,
        commission=0.0005,
        stop_loss_pct=0.05,
        max_position_pct=0.20,
        kill_switch_drawdown=0.15,
    )

    results = cerebro.run()
    metrics = extract_metrics(results[0])
    ret = metrics['total_return'] * 100

    print(f"Return: {ret:6.2f}%")

    if ret > best_return:
        best_return = ret
        best_oversold = oversold
        best_config = {
            'rsi_period': 14,
            'rsi_oversold': oversold,
            'rsi_overbought': 100 - oversold,
        }

print(f"\n✓ Best oversold value: {best_oversold} with {best_return:.2f}% return")
print(f"  Recommended config: {best_config}")

# Now test period with best oversold
print(f"\nTesting RSI periods (with oversold={best_oversold}):\n")

periods = [10, 12, 14, 16, 20]
best_period = None
best_return_p = -999

for period in periods:
    print(f"  Testing RSI period={period:2d}...  ", end=' ', flush=True)

    feeds = {pair: fetch_binance_feed(pair, days=DAYS) for pair in PAIRS}

    cerebro = build_cerebro(
        feeds=feeds,
        strategy_class=RSIOnlyStrategy,
        strategy_config={
            'rsi_period': period,
            'rsi_oversold': best_oversold,
            'rsi_overbought': 100 - best_oversold,
        },
        fear_greed_map=fng,
        cash=INITIAL_CASH,
        commission=0.0005,
        stop_loss_pct=0.05,
        max_position_pct=0.20,
        kill_switch_drawdown=0.15,
    )

    results = cerebro.run()
    metrics = extract_metrics(results[0])
    ret = metrics['total_return'] * 100

    print(f"Return: {ret:6.2f}%")

    if ret > best_return_p:
        best_return_p = ret
        best_period = period

print(f"\n✓ Best period: {best_period} with {best_return_p:.2f}% return")

# Final optimized config
final_config = {
    'rsi_period': best_period,
    'rsi_oversold': best_oversold,
    'rsi_overbought': 100 - best_oversold,
}

print("\n" + "="*80)
print("OPTIMIZED RSI CONFIGURATION")
print("="*80)
print(f"Period:     {final_config['rsi_period']}")
print(f"Oversold:   {final_config['rsi_oversold']}")
print(f"Overbought: {final_config['rsi_overbought']}")
print(f"Return:     {best_return_p:.2f}%")

print(f"\nUse this in config.yaml or pass to RSIOnlyStrategy:")
print(f"""
config = {{
    'rsi_period': {final_config['rsi_period']},
    'rsi_oversold': {final_config['rsi_oversold']},
    'rsi_overbought': {final_config['rsi_overbought']},
}}
""")

# Save results
results_dir = Path(__file__).parent.parent / 'results'
results_dir.mkdir(exist_ok=True)

results_df = pd.DataFrame({
    'Parameter': ['Period', 'Oversold', 'Overbought', 'Return %'],
    'Value': [final_config['rsi_period'], final_config['rsi_oversold'], final_config['rsi_overbought'], f"{best_return_p:.2f}"],
})

results_df.to_csv(results_dir / 'rsi_quick_optimization.csv', index=False)
print(f"\nResults saved to {results_dir}/rsi_quick_optimization.csv")
