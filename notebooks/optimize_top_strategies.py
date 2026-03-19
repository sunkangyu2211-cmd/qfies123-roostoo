"""
Parameter optimization for top-performing strategies.

Performs grid search over key parameters for the top 3 strategies
to identify optimal configurations.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import yaml
from itertools import product

from backtest.bt_strategy import build_cerebro, extract_metrics
from backtest.data_feed import fetch_binance_feed, fetch_fear_greed
from strategy import RSIOnlyStrategy, MACDStrategy, ADXTrendStrategy

# Configuration
config_path = Path(__file__).parent.parent / 'config.yaml'
with open(config_path) as f:
    config = yaml.safe_load(f)

PAIRS = config['trading']['pairs']
DAYS = 30
INITIAL_CASH = 50_000.0

print("="*120)
print("PARAMETER OPTIMIZATION FOR TOP STRATEGIES")
print("="*120)

# Fetch data once
print("\nFetching data...")
raw_feeds = {}
for pair in PAIRS:
    raw_feeds[pair] = fetch_binance_feed(pair, days=DAYS)
fng = fetch_fear_greed(days=DAYS)
print(f"Data loaded: {len(raw_feeds)} pairs")

# ===== STRATEGY 1: RSI OPTIMIZATION =====
print("\n" + "="*120)
print("1. RSI OPTIMIZATION (Current Best: 10.31%)")
print("="*120)

rsi_params = {
    'rsi_period': [10, 14, 20],
    'rsi_oversold': [20, 25, 30, 35],
    'rsi_overbought': [65, 70, 75, 80],
}

rsi_results = []
total_rsi_tests = len(rsi_params['rsi_period']) * len(rsi_params['rsi_oversold']) * len(rsi_params['rsi_overbought'])
test_num = 0

for period, oversold, overbought in product(
    rsi_params['rsi_period'],
    rsi_params['rsi_oversold'],
    rsi_params['rsi_overbought']
):
    test_num += 1
    print(f"  Testing RSI({period}, {oversold}, {overbought}) ... [{test_num}/{total_rsi_tests}]", end=' ', flush=True)

    feeds = {pair: fetch_binance_feed(pair, days=DAYS) for pair in PAIRS}

    cerebro = build_cerebro(
        feeds=feeds,
        strategy_class=RSIOnlyStrategy,
        strategy_config={
            'rsi_period': period,
            'rsi_oversold': oversold,
            'rsi_overbought': overbought,
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
    final_value = cerebro.broker.getvalue()

    rsi_results.append({
        'Period': period,
        'Oversold': oversold,
        'Overbought': overbought,
        'Return %': metrics['total_return'] * 100,
        'Trades': metrics['total_trades'],
        'Win Rate %': (metrics['win_rate'] * 100) if metrics['win_rate'] else 0,
        'Max DD %': metrics['max_drawdown'] * 100,
    })

    print(f"Return: {metrics['total_return']*100:.2f}%")

df_rsi = pd.DataFrame(rsi_results).sort_values('Return %', ascending=False)
print("\nTop 5 RSI configurations:")
print(df_rsi.head().to_string(index=False))

# ===== STRATEGY 2: MACD OPTIMIZATION =====
print("\n" + "="*120)
print("2. MACD OPTIMIZATION (Current: 5.72%)")
print("="*120)

macd_params = {
    'macd_fast': [10, 12, 15],
    'macd_slow': [24, 26, 28],
    'macd_signal': [7, 9, 11],
}

macd_results = []
total_macd_tests = len(macd_params['macd_fast']) * len(macd_params['macd_slow']) * len(macd_params['macd_signal'])
test_num = 0

for fast, slow, signal in product(
    macd_params['macd_fast'],
    macd_params['macd_slow'],
    macd_params['macd_signal']
):
    if fast >= slow:
        continue

    test_num += 1
    print(f"  Testing MACD({fast}, {slow}, {signal}) ... [{test_num}/{total_macd_tests}]", end=' ', flush=True)

    feeds = {pair: fetch_binance_feed(pair, days=DAYS) for pair in PAIRS}

    cerebro = build_cerebro(
        feeds=feeds,
        strategy_class=MACDStrategy,
        strategy_config={
            'macd_fast': fast,
            'macd_slow': slow,
            'macd_signal': signal,
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

    macd_results.append({
        'Fast': fast,
        'Slow': slow,
        'Signal': signal,
        'Return %': metrics['total_return'] * 100,
        'Trades': metrics['total_trades'],
        'Win Rate %': (metrics['win_rate'] * 100) if metrics['win_rate'] else 0,
        'Max DD %': metrics['max_drawdown'] * 100,
    })

    print(f"Return: {metrics['total_return']*100:.2f}%")

df_macd = pd.DataFrame(macd_results).sort_values('Return %', ascending=False)
print("\nTop 5 MACD configurations:")
print(df_macd.head().to_string(index=False))

# ===== STRATEGY 3: ADX OPTIMIZATION =====
print("\n" + "="*120)
print("3. ADX OPTIMIZATION (Current: 5.64%)")
print("="*120)

adx_params = {
    'adx_period': [12, 14, 16],
    'adx_threshold': [20.0, 25.0, 30.0],
    'ma_period': [15, 20, 25],
}

adx_results = []
total_adx_tests = len(adx_params['adx_period']) * len(adx_params['adx_threshold']) * len(adx_params['ma_period'])
test_num = 0

for period, threshold, ma_period in product(
    adx_params['adx_period'],
    adx_params['adx_threshold'],
    adx_params['ma_period']
):
    test_num += 1
    print(f"  Testing ADX({period}, {threshold}, {ma_period}) ... [{test_num}/{total_adx_tests}]", end=' ', flush=True)

    feeds = {pair: fetch_binance_feed(pair, days=DAYS) for pair in PAIRS}

    cerebro = build_cerebro(
        feeds=feeds,
        strategy_class=ADXTrendStrategy,
        strategy_config={
            'adx_period': period,
            'adx_threshold': threshold,
            'ma_period': ma_period,
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

    adx_results.append({
        'Period': period,
        'Threshold': threshold,
        'MA Period': ma_period,
        'Return %': metrics['total_return'] * 100,
        'Trades': metrics['total_trades'],
        'Win Rate %': (metrics['win_rate'] * 100) if metrics['win_rate'] else 0,
        'Max DD %': metrics['max_drawdown'] * 100,
    })

    print(f"Return: {metrics['total_return']*100:.2f}%")

df_adx = pd.DataFrame(adx_results).sort_values('Return %', ascending=False)
print("\nTop 5 ADX configurations:")
print(df_adx.head().to_string(index=False))

# ===== Save all optimization results =====
results_dir = Path(__file__).parent.parent / 'results'
results_dir.mkdir(exist_ok=True)

df_rsi.to_csv(results_dir / 'rsi_optimization.csv', index=False)
df_macd.to_csv(results_dir / 'macd_optimization.csv', index=False)
df_adx.to_csv(results_dir / 'adx_optimization.csv', index=False)

print("\n" + "="*120)
print("SUMMARY")
print("="*120)
print(f"RSI Best:   {df_rsi.iloc[0]['Return %']:.2f}%  (Period={df_rsi.iloc[0]['Period']}, OS={df_rsi.iloc[0]['Oversold']}, OB={df_rsi.iloc[0]['Overbought']})")
print(f"MACD Best:  {df_macd.iloc[0]['Return %']:.2f}%  (Fast={df_macd.iloc[0]['Fast']}, Slow={df_macd.iloc[0]['Slow']}, Signal={df_macd.iloc[0]['Signal']})")
print(f"ADX Best:   {df_adx.iloc[0]['Return %']:.2f}%  (Period={df_adx.iloc[0]['Period']}, Threshold={df_adx.iloc[0]['Threshold']}, MA={df_adx.iloc[0]['MA Period']})")
print(f"\nResults saved to {results_dir}/")
