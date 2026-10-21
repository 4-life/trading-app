from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import async_session
from app.feature_engine import indicators, orderbook
from app.feature_engine.models import Feature
from app.market_data.models import (
    Candle,
    FundingRate,
    OpenInterestSnapshot,
    OrderBookSnapshot,
    Trade,
)

# Duration of each return window, in minutes - independent of which candle
# interval actually sources it (see return_windows_for_interval below).
RETURN_WINDOWS = [("1m", 1), ("5m", 5), ("15m", 15), ("1h", 60), ("4h", 240), ("1d", 1440)]

INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}


def return_windows_for_interval(interval: str) -> list[tuple[str, int]]:
    """RETURN_WINDOWS scaled to bars-back for `interval`. A window finer
    than the interval itself (e.g. return_1m from 1h candles) can't be
    computed at all - dropped rather than rounded to a fractional bar."""
    interval_minutes = INTERVAL_MINUTES[interval]
    return [
        (label, duration_minutes // interval_minutes)
        for label, duration_minutes in RETURN_WINDOWS
        if duration_minutes // interval_minutes >= 1
    ]


# The largest fixed-bar-count lookback any indicator in compute_features()
# needs, independent of RETURN_WINDOWS (the largest is
# volatility_expansion_ratio's 40-bar window), with margin.
MIN_INDICATOR_LOOKBACK_BARS = 120


def candle_lookback_for_interval(interval: str) -> int:
    """Must exceed the largest bars-back window any feature needs at
    `interval` - returns() needs len(closes) > periods_back, so any smaller
    cap makes that window's return permanently unbuildable regardless of how
    much candle history actually exists. Confirmed at a previous fixed value
    (200): return_4h/return_1d had zero rows ever, for any asset, always
    None - not a market condition, a hardcoded ceiling below what the
    feature itself needs. MIN_INDICATOR_LOOKBACK_BARS is the same fix for
    every other indicator's own, RETURN_WINDOWS-independent requirement."""
    windows = return_windows_for_interval(interval)
    return max(max(bars for _, bars in windows) + 1, MIN_INDICATOR_LOOKBACK_BARS)


# Fixed prior-snapshot count for the OI query - independent of the candle
# interval.
CANDLE_LOOKBACK = candle_lookback_for_interval("1m")
TRADE_LOOKBACK = 500
# Funding rows land far more often than candles (confirmed 2026-09-24: ~170
# rows/day for BTC/gold/SP500 alike, well under an hour apart) - 100 gives
# funding_zscore's default window=20 comfortable margin while staying a
# "recent regime" window (well under a day), not a multi-week one.
FUNDING_LOOKBACK = 100


async def compute_features(asset: str, now: datetime, interval: str) -> dict[str, float]:
    """Features as of `now`, from candles that had closed by `now` only."""
    features: dict[str, float] = {}
    candle_lookback = candle_lookback_for_interval(interval)
    last_closed_open_time = now - timedelta(minutes=INTERVAL_MINUTES[interval])

    async with async_session() as session:
        # desc()+limit then reversed, not order_by(open_time).limit(N) - the
        # latter returns the OLDEST N rows, which is only ever "recent" by
        # coincidence when total candle count stays under candle_lookback.
        # Once backfill seeds thousands of candles (app/market_data/backfill.py),
        # that coincidence breaks and every indicator below silently computes
        # from a stale, frozen window instead of one that actually reflects
        # `now`. The <= now bound is what makes this safe to call with a
        # historical `now` too (see app/feature_engine/backfill.py).
        candles = list(
            reversed(
                (
                    await session.scalars(
                        select(Candle)
                        .where(
                            Candle.asset == asset,
                            Candle.interval == interval,
                            Candle.open_time <= last_closed_open_time,
                        )
                        .order_by(Candle.open_time.desc())
                        .limit(candle_lookback)
                    )
                ).all()
            )
        )
        closes = [float(c.close) for c in candles]
        highs = [float(c.high) for c in candles]
        lows = [float(c.low) for c in candles]
        volumes = [float(c.volume) for c in candles]

        for label, bars in return_windows_for_interval(interval):
            r = indicators.returns(closes, bars)
            if r is not None:
                features[f"return_{label}"] = r

        for name, value in (
            ("momentum", indicators.momentum(closes)),
            ("volatility", indicators.volatility(closes)),
            ("volatility_expansion_ratio", indicators.volatility_expansion_ratio(closes)),
            ("atr", indicators.atr(highs, lows, closes)),
            ("distance_from_high", indicators.distance_from_high(closes)),
            ("distance_from_low", indicators.distance_from_low(closes)),
            ("breakout_distance", indicators.breakout_distance(closes)),
            ("volume_z_score", indicators.volume_z_score(volumes)),
            ("relative_volume", indicators.relative_volume(volumes)),
            ("volume_acceleration", indicators.volume_acceleration(volumes)),
        ):
            if value is not None:
                features[name] = value

        oi_rows = list(
            reversed(
                (
                    await session.scalars(
                        select(OpenInterestSnapshot)
                        .where(
                            OpenInterestSnapshot.asset == asset,
                            OpenInterestSnapshot.collected_at <= now,
                        )
                        .order_by(OpenInterestSnapshot.collected_at.desc())
                        .limit(CANDLE_LOOKBACK)
                    )
                ).all()
            )
        )
        if oi_rows:
            features["open_interest"] = float(oi_rows[-1].open_interest)
            oic = indicators.oi_change([float(r.open_interest) for r in oi_rows])
            if oic is not None:
                features["oi_change"] = oic

        funding_rows = list(
            reversed(
                (
                    await session.scalars(
                        select(FundingRate)
                        .where(FundingRate.asset == asset, FundingRate.exchange_timestamp <= now)
                        .order_by(FundingRate.exchange_timestamp.desc())
                        .limit(FUNDING_LOOKBACK)
                    )
                ).all()
            )
        )
        if funding_rows:
            features["funding"] = float(funding_rows[-1].funding_rate)
            fz = indicators.funding_zscore([float(r.funding_rate) for r in funding_rows])
            if fz is not None:
                features["funding_zscore"] = fz

        latest_book = await session.scalar(
            select(OrderBookSnapshot)
            .where(OrderBookSnapshot.asset == asset, OrderBookSnapshot.exchange_timestamp <= now)
            .order_by(OrderBookSnapshot.exchange_timestamp.desc())
            .limit(1)
        )
        if latest_book is not None:
            bid_depth, ask_depth = float(latest_book.bid_depth), float(latest_book.ask_depth)
            imb = orderbook.bid_ask_imbalance(bid_depth, ask_depth)
            if imb is not None:
                features["bid_ask_imbalance"] = imb
            features["market_depth"] = orderbook.market_depth(bid_depth, ask_depth)
            sp = orderbook.spread(float(latest_book.best_bid), float(latest_book.best_ask))
            if sp is not None:
                features["spread"] = sp

        recent_trades = (
            await session.scalars(
                select(Trade)
                .where(Trade.asset == asset, Trade.exchange_timestamp <= now)
                .order_by(Trade.exchange_timestamp.desc())
                .limit(TRADE_LOOKBACK)
            )
        ).all()
        ratio = orderbook.aggressive_buy_sell_ratio(
            [(t.side, float(t.size)) for t in recent_trades]
        )
        if ratio is not None:
            features["aggressive_buy_sell_ratio"] = ratio

    return features


async def compute_and_store(asset: str, interval: str) -> None:
    """Computes features once per closed candle, stamped at its close time.
    A candle counts as closed once the next one has been collected (the
    collector re-fetches the closed candle in that same request, so its
    final values are stored)."""
    async with async_session() as session:
        now = await session.scalar(
            select(Candle.open_time)
            .where(Candle.asset == asset, Candle.interval == interval)
            .order_by(Candle.open_time.desc())
            .limit(1)
        )
        if now is None:
            return
        done = await session.scalar(
            select(Feature.id)
            .where(Feature.asset == asset, Feature.interval == interval, Feature.computed_at == now)
            .limit(1)
        )
    if done is not None:
        return
    values = await compute_features(asset, now, interval)
    if not values:
        return
    stmt = pg_insert(Feature).values(
        [
            {
                "asset": asset,
                "name": name,
                "interval": interval,
                "value": Decimal(str(value)),
                "computed_at": now,
            }
            for name, value in values.items()
        ]
    )
    stmt = stmt.on_conflict_do_nothing(index_elements=["asset", "name", "interval", "computed_at"])
    async with async_session() as session:
        await session.execute(stmt)
        await session.commit()
