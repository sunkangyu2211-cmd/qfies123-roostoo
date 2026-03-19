"""
Strategy comparison and ranking script.

Tests all available strategies on the same data and produces a comprehensive
comparison table with metrics to identify top performers.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import warnings
warnings.filterwarnings('ignore')

import backtrader as bt
import pandas as pd
import yaml

from backtest.bt_strategy import build_cerebro, extract_metrics
from backtest.data_feed import fetch_binance_feed, fetch_fear_greed
from strategy import (
    MultiSignalStrategy,
    SimpleMomentumStrategy,
    RSIOnlyStrategy,
    MAcrossoverStrategy,
    BollingerBandsStrategy,
    MACDStrategy,
    ADXTrendStrategy,
    StochasticStrategy,
)

# Configuration
config_path = Path(__file__).parent.parent / 'config.yaml'
with open(config_path) as f:
    config = yaml.safe_load(f)

PAIRS = config['trading']['pairs']
DAYS = 30
INITIAL_CASH = 50_000.0

print(f"Pairs: {PAIRS}")
print(f"Backtest Period: {DAYS} days")
print(f"Initial Capital: ${INITIAL_CASH:,.2f}\n")

# ===== Strategy Definitions =====
STRATEGIES = {
    'MultiSignal': {
        'class': MultiSignalStrategy,
        'config': {
            'rsi_period': 14,
            'rsi_oversold': 35,
            'rsi_overbought': 65,
            'ema_fast': 12,
            'ema_slow': 26,
            'momentum_threshold_pct': 2.0,
            'min_signal_score': 2,
        },
        'description': 'RSI + EMA crossover + Momentum + F&G filter'
    },
    'SimpleMomentum': {
        'class': SimpleMomentumStrategy,
        'config': {
            'momentum_threshold_pct': 1.5,
        },
        'description': 'Pure 24h momentum'
    },
    'RSIOnly': {
        'class': RSIOnlyStrategy,
        'config': {
            'rsi_period': 14,
            'rsi_oversold': 30,
            'rsi_overbought': 70,
        },
        'description': 'RSI oversold/overbought'
    },
    'MAcrossover': {
        'class': MAcrossoverStrategy,
        'config': {
            'ma_fast': 20,
            'ma_slow': 50,
        },
        'description': 'MA(20/50) golden/death cross'
    },
    'BollingerBands': {
        'class': BollingerBandsStrategy,
        'config': {
            'bb_period': 20,
            'bb_std': 2.0,
        },
        'description': 'Bollinger Bands mean reversion'
    },
    'MACD': {
        'class': MACDStrategy,
        'config': {
            'macd_fast': 12,
            'macd_slow': 26,
            'macd_signal': 9,
        },
        'description': 'MACD line/signal crossover'
    },
    'ADXTrend': {
        'class': ADXTrendStrategy,
        'config': {
            'adx_period': 14,
            'adx_threshold': 25.0,
            'ma_period': 20,
        },
        'description': 'ADX trend confirmation + MA'
    },
    'Stochastic': {
        'class': StochasticStrategy,
        'config': {
            'k_period': 14,
            'd_period': 3,
            'stoch_oversold': 20.0,
            'stoch_overbought': 80.0,
        },
        'description': 'Stochastic oscillator'
    },
}

# ===== Fetch Data Once =====
print("Fetching data...")
raw_feeds = {}
for pair in PAIRS:
    raw_feeds[pair] = fetch_binance_feed(pair, days=DAYS)

fng = fetch_fear_greed(days=DAYS)
print(f"Data loaded: {len(raw_feeds)} pairs, F&G entries: {len(fng)}\n")

# ===== Backtest All Strategies =====
print("Running backtests...\n")
results_list = []

for strat_name, strat_info in STRATEGIES.items():
    print(f"Testing {strat_name}...", end=' ', flush=True)

    # Re-create feeds (backtrader consumes them)
    feeds = {}
    for pair in PAIRS:
        feeds[pair] = fetch_binance_feed(pair, days=DAYS)

    cerebro = build_cerebro(
        feeds=feeds,
        strategy_class=strat_info['class'],
        strategy_config=strat_info['config'],
        fear_greed_map=fng,
        cash=INITIAL_CASH,
        commission=0.0005,
        stop_loss_pct=0.05,
        max_position_pct=0.20,
        kill_switch_drawdown=0.15,
    )

    results = cerebro.run()
    strat = results[0]
    final_value = cerebro.broker.getvalue()
    metrics = extract_metrics(strat)

    result_row = {
        'Strategy': strat_name,
        'Description': strat_info['description'],
        'Final Value': final_value,
        'Return %': metrics['total_return'] * 100,
        'Trades': metrics['total_trades'],
        'Win Rate %': metrics['win_rate'] * 100 if metrics['win_rate'] else 0,
        'Sharpe': metrics['sharpe'] or 0,
        'Max DD %': metrics['max_drawdown'] * 100,
        'Avg P&L': metrics['avg_pnl'] or 0,
        'SQN': metrics['sqn'] or 0,
    }

    results_list.append(result_row)
    print(f"Done. Return: {result_row['Return %']:.2f}%")

# ===== Create Results DataFrame and Rank =====
df_results = pd.DataFrame(results_list)

# Sort by return (best first)
df_results_ranked = df_results.sort_values('Return %', ascending=False).reset_index(drop=True)
df_results_ranked.insert(0, 'Rank', range(1, len(df_results_ranked) + 1))

# ===== Display Results =====
print("\n" + "="*120)
print("STRATEGY COMPARISON - RANKED BY RETURN")
print("="*120)

pd.set_option('display.max_columns', None)
pd.set_option('display.width', None)
pd.set_option('display.max_colwidth', None)

display_df = df_results_ranked[['Rank', 'Strategy', 'Return %', 'Trades', 'Win Rate %', 'Max DD %', 'Sharpe', 'Avg P&L']].copy()
display_df['Return %'] = display_df['Return %'].apply(lambda x: f"{x:7.2f}%")
display_df['Win Rate %'] = display_df['Win Rate %'].apply(lambda x: f"{x:6.1f}%")
display_df['Max DD %'] = display_df['Max DD %'].apply(lambda x: f"{x:6.2f}%")
display_df['Sharpe'] = display_df['Sharpe'].apply(lambda x: f"{x:7.2f}" if x != 0 else "N/A")
display_df['Avg P&L'] = display_df['Avg P&L'].apply(lambda x: f"${x:9.2f}")

print(display_df.to_string(index=False))

# ===== Summary Statistics =====
print("\n" + "="*120)
print("SUMMARY")
print("="*120)

best_strat = df_results_ranked.iloc[0]
worst_strat = df_results_ranked.iloc[-1]

print(f"Best Strategy:  {best_strat['Strategy']:15s} | Return: {best_strat['Return %']:7.2f}% | DD: {best_strat['Max DD %']:6.2f}%")
print(f"Worst Strategy: {worst_strat['Strategy']:15s} | Return: {worst_strat['Return %']:7.2f}% | DD: {worst_strat['Max DD %']:6.2f}%")

avg_return = df_results['Return %'].mean()
print(f"\nAverage Return: {avg_return:7.2f}%")
print(f"Positive Return Strategies: {(df_results['Return %'] > 0).sum()} / {len(df_results)}")

# ===== Save Results =====
results_dir = Path(__file__).parent.parent / 'results'
results_dir.mkdir(exist_ok=True)

full_results_path = results_dir / 'strategy_comparison.csv'
df_results_ranked.to_csv(full_results_path, index=False)
print(f"\nResults saved to {full_results_path}")

print("\nTop 3 strategies to optimize further:")
for idx, row in df_results_ranked.head(3).iterrows():
    print(f"  {idx+1}. {row['Strategy']:15s} - {row['Return %']:7.2f}% return, {row['Trades']:2d} trades")
