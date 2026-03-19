"""Backtrader strategy adapter for Roostoo strategies.

Bridges backtrader's bar-by-bar ``next()`` callback with our
``BaseStrategy.generate_signal(market_data)`` interface, so any
strategy that works with the live bot also works in backtrader.
"""

import logging
from typing import Any, Optional

import backtrader as bt
import pandas as pd

from strategy.multi_signal import MultiSignalStrategy

logger = logging.getLogger(__name__)


class RoostooStrategy(bt.Strategy):
    """Backtrader adapter wrapping a Roostoo BaseStrategy subclass.

    Params:
        strategy_class: The strategy class to instantiate (default:
            MultiSignalStrategy).
        strategy_config: Dict passed to strategy_class.__init__.
        limit_offset: Limit order offset from market (default 0.002).
        stop_loss_pct: Stop-loss threshold (default 0.05).
        max_position_pct: Max portfolio fraction per asset (default 0.20).
        kill_switch_drawdown: Kill switch drawdown threshold (default 0.15).
        kill_switch_bars: Cooldown in bars after kill switch (default 4).
        min_trade_usd: Minimum trade notional (default 10.0).
        fear_greed_map: Dict mapping date strings to F&G values.
    """

    params = (
        ("strategy_class", MultiSignalStrategy),
        ("strategy_config", {}),
        ("limit_offset", 0.002),
        ("stop_loss_pct", 0.05),
        ("max_position_pct", 0.20),
        ("kill_switch_drawdown", 0.15),
        ("kill_switch_bars", 4),
        ("min_trade_usd", 10.0),
        ("fear_greed_map", {}),
    )

    def __init__(self) -> None:
        config = dict(self.p.strategy_config)
        self.roostoo_strategy = self.p.strategy_class(config)

        self.entry_prices: dict[str, float] = {}
        self.peak_value: float = 0.0
        self.kill_switch_until: int = 0
        self.bar_count: int = 0
        self.trade_log: list[dict[str, Any]] = []

        # Track indicators per data feed for plotting
        self.indicators: dict[str, dict[str, Any]] = {}
        for data in self.datas:
            name = data._name
            rsi_period = config.get("rsi_period", 14)
            ema_fast = config.get("ema_fast", 12)
            ema_slow = config.get("ema_slow", 26)
            self.indicators[name] = {
                "rsi": bt.indicators.RSI(data.close, period=rsi_period),
                "ema_fast": bt.indicators.EMA(data.close, period=ema_fast),
                "ema_slow": bt.indicators.EMA(data.close, period=ema_slow),
            }

    def next(self) -> None:
        self.bar_count += 1
        portfolio_value = self.broker.getvalue()
        self.peak_value = max(self.peak_value, portfolio_value)

        # Kill switch check
        if self.bar_count < self.kill_switch_until:
            return

        if self.peak_value > 0:
            drawdown = (self.peak_value - portfolio_value) / self.peak_value
            if drawdown >= self.p.kill_switch_drawdown:
                self.kill_switch_until = self.bar_count + self.p.kill_switch_bars
                logger.warning(
                    "KILL SWITCH: %.1f%% drawdown. Pausing %d bars.",
                    drawdown * 100,
                    self.p.kill_switch_bars,
                )
                return

        # Stop-loss check
        for data in self.datas:
            pair = data._name
            if pair not in self.entry_prices:
                continue
            pos = self.getposition(data).size
            if pos <= 0:
                self.entry_prices.pop(pair, None)
                continue
            entry = self.entry_prices[pair]
            current = data.close[0]
            loss_pct = (entry - current) / entry
            if loss_pct >= self.p.stop_loss_pct:
                logger.info(
                    "Stop-loss %s: %.1f%% drop from $%.2f",
                    pair,
                    loss_pct * 100,
                    entry,
                )
                self.close(data=data)
                self.entry_prices.pop(pair, None)

        # Generate signals for each pair
        for data in self.datas:
            pair = data._name
            market_data = self._build_market_data(data, pair)
            signal = self.roostoo_strategy.generate_signal(market_data)

            if signal.action == "HOLD":
                continue

            price = data.close[0]

            if signal.action == "BUY":
                if not self._can_buy(data, portfolio_value, price):
                    continue
                qty = self._size_buy(portfolio_value, signal.confidence, price)
                if qty * price < self.p.min_trade_usd:
                    continue
                limit_price = price * (1 - self.p.limit_offset)
                self.buy(
                    data=data,
                    size=qty,
                    exectype=bt.Order.Limit,
                    price=limit_price,
                )

            elif signal.action == "SELL":
                pos = self.getposition(data).size
                if pos <= 0:
                    continue
                if pos * price < self.p.min_trade_usd:
                    continue
                limit_price = price * (1 + self.p.limit_offset)
                self.sell(
                    data=data,
                    size=pos,
                    exectype=bt.Order.Limit,
                    price=limit_price,
                )

    def _build_market_data(
        self, data: bt.AbstractDataBase, pair: str
    ) -> dict[str, Any]:
        """Build the market_data dict our strategy expects."""
        # Build OHLCV DataFrame from backtrader buffers
        size = min(len(data), 100)
        rows = []
        for j in range(-size + 1, 1):
            rows.append(
                {
                    "timestamp": int(bt.num2date(data.datetime[j]).timestamp() * 1000),
                    "open": data.open[j],
                    "high": data.high[j],
                    "low": data.low[j],
                    "close": data.close[j],
                    "volume": data.volume[j],
                }
            )
        ohlcv = pd.DataFrame(rows)

        # 24h change
        change_24h = 0.0
        if len(data) >= 24:
            close_now = data.close[0]
            close_24ago = data.close[-24]
            if close_24ago > 0:
                change_24h = (close_now - close_24ago) / close_24ago * 100

        # Fear & Greed lookup
        current_dt = bt.num2date(data.datetime[0])
        date_key = current_dt.strftime("%Y-%m-%d")
        fear_greed = self.p.fear_greed_map.get(date_key)

        # Synthetic prices dict for all pairs
        prices: dict[str, dict[str, float]] = {}
        for d in self.datas:
            p_name = d._name
            p_close = d.close[0]
            p_change = 0.0
            if len(d) >= 24 and d.close[-24] > 0:
                p_change = (d.close[0] - d.close[-24]) / d.close[-24]
            prices[p_name] = {
                "bid": p_close * 0.999,
                "ask": p_close * 1.001,
                "last": p_close,
                "change": p_change,
            }

        return {
            "pair": pair,
            "ohlcv": ohlcv,
            "change_24h": change_24h,
            "fear_greed": fear_greed,
            "prices": prices,
        }

    def _can_buy(
        self,
        data: bt.AbstractDataBase,
        portfolio_value: float,
        price: float,
    ) -> bool:
        """Check if we can buy more of this asset."""
        pos = self.getposition(data).size
        position_value = pos * price
        max_value = portfolio_value * self.p.max_position_pct
        return position_value < max_value

    def _size_buy(
        self,
        portfolio_value: float,
        confidence: float,
        price: float,
    ) -> float:
        """Calculate buy quantity scaled by confidence."""
        max_usd = portfolio_value * self.p.max_position_pct
        target_usd = max_usd * confidence
        target_usd = max(target_usd, self.p.min_trade_usd)
        return target_usd / price

    def notify_order(self, order: bt.Order) -> None:
        if order.status in [order.Completed]:
            pair = order.data._name
            if order.isbuy():
                self.entry_prices[pair] = order.executed.price
                logger.info(
                    "BUY  %s  qty=%.6f  @ $%.2f  comm=$%.2f",
                    pair,
                    order.executed.size,
                    order.executed.price,
                    order.executed.comm,
                )
            else:
                self.entry_prices.pop(pair, None)
                logger.info(
                    "SELL %s  qty=%.6f  @ $%.2f  comm=$%.2f",
                    pair,
                    order.executed.size,
                    order.executed.price,
                    order.executed.comm,
                )

    def notify_trade(self, trade: bt.Trade) -> None:
        if trade.isclosed:
            self.trade_log.append(
                {
                    "pair": trade.data._name,
                    "pnl": trade.pnl,
                    "pnlcomm": trade.pnlcomm,
                    "baropen": trade.baropen,
                    "barclose": trade.barclose,
                }
            )
            logger.info(
                "CLOSED %s  P&L: $%.2f (net $%.2f)",
                trade.data._name,
                trade.pnl,
                trade.pnlcomm,
            )


def build_cerebro(
    feeds: dict[str, bt.feeds.PandasData],
    strategy_class: type = MultiSignalStrategy,
    strategy_config: Optional[dict] = None,
    fear_greed_map: Optional[dict] = None,
    cash: float = 50_000.0,
    commission: float = 0.0005,
    **strategy_overrides: Any,
) -> bt.Cerebro:
    """Build a fully configured Cerebro instance.

    Args:
        feeds: Dict mapping pair name to backtrader data feed.
        strategy_class: The Roostoo strategy class to use.
        strategy_config: Config dict for the strategy.
        fear_greed_map: Historical Fear & Greed data.
        cash: Starting capital.
        commission: Commission rate per trade.
        **strategy_overrides: Override RoostooStrategy params
            (e.g. stop_loss_pct=0.03).

    Returns:
        Configured Cerebro ready to run.
    """
    if strategy_config is None:
        strategy_config = {}
    if fear_greed_map is None:
        fear_greed_map = {}

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=commission)

    for pair_name, feed in feeds.items():
        cerebro.adddata(feed, name=pair_name)

    cerebro.addstrategy(
        RoostooStrategy,
        strategy_class=strategy_class,
        strategy_config=strategy_config,
        fear_greed_map=fear_greed_map,
        **strategy_overrides,
    )

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.SQN, _name="sqn")

    return cerebro


def extract_metrics(strat: RoostooStrategy) -> dict[str, Any]:
    """Extract metrics from a completed strategy's analyzers.

    Args:
        strat: The strategy instance returned by cerebro.run()[0].

    Returns:
        Dict of metric name to value.
    """
    sharpe_data = strat.analyzers.sharpe.get_analysis()
    dd_data = strat.analyzers.drawdown.get_analysis()
    trades_data = strat.analyzers.trades.get_analysis()
    returns_data = strat.analyzers.returns.get_analysis()
    sqn_data = strat.analyzers.sqn.get_analysis()

    total_trades = trades_data.get("total", {}).get("total", 0)
    won = trades_data.get("won", {}).get("total", 0)
    lost = trades_data.get("lost", {}).get("total", 0)
    win_rate = won / total_trades if total_trades > 0 else None

    return {
        "total_return": returns_data.get("rtot", 0.0),
        "sharpe": sharpe_data.get("sharperatio"),
        "max_drawdown": dd_data.get("max", {}).get("drawdown", 0.0) / 100,
        "max_dd_duration": dd_data.get("max", {}).get("len", 0),
        "total_trades": total_trades,
        "won": won,
        "lost": lost,
        "win_rate": win_rate,
        "sqn": sqn_data.get("sqn"),
        "avg_pnl": (trades_data.get("pnl", {}).get("net", {}).get("average", 0.0)),
    }
