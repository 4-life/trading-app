import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesPrimitive,
  LineSeries,
  LineStyle,
  type SeriesMarker,
  type Time,
  TickMarkType,
  type UTCTimestamp,
} from 'lightweight-charts';
import { useEffect, useRef, useState } from 'react';

import { Checkbox } from '@/components/ui/checkbox';
import { formatDateTime, formatPrice, formatUsd, pnlPercent, priceDigits } from '@/lib/format';
import type { BandPoint, CandleChunk, ChartSwing, LiquidityZone, PaperChart, SwingKind, VwapPoint } from '@/types/chart';

import { fetchCandleChunk } from './api';
import { addCount, isShortFill, positionValue, stateAt, unitProfits } from './backtest';
import { FORCED_EXITS, INDICATORS, OPEN_AT_END, SHORT_FILLS } from './constants';
import { useHiddenIndicators } from './hooks/use-hidden-indicators';
import { Path } from './path';
import { type Point, Rectangle } from './rectangle';
import { Segment } from './segment';
import type { Indicator } from './types';
import { VerticalLine } from './vertical-line';

// Client-only (loaded lazily by ./index.tsx).

const GREEN = '#22c55e';
const RED = '#ef4444';
const BLUE = '#3b82f6';
const ORANGE = '#f97316';
const AMBER = '#f59e0b';
const MUTED = '#8b8b8b';
const VIOLET = '#a855f7';
const CYAN = '#06b6d4'; // an averaging backtest's unwinds - no candle shares it
const PINK = '#ec4899'; // an averaging hedge backtest's short fills
const GRID = 'rgba(139, 139, 139, 0.15)';
const ZONE_FILL = { low: 'rgba(34, 197, 94, 0.25)', high: 'rgba(239, 68, 68, 0.25)' };

const SWING_COLOR: Record<SwingKind, string> = {
  HH: GREEN,
  HL: GREEN,
  LL: RED,
  LH: RED,
};

const TIMEFRAME_SECONDS: Record<string, number> = {
  '1m': 60,
  '5m': 300,
  '15m': 900,
  '1h': 3600,
  '4h': 14_400,
};

const INITIAL_DAYS = 7;
// Older candles load ahead of the view: once it's within PRELOAD_SCREENS
// view widths of the loaded start, the next CHUNK_SCREENS widths (CHUNK_MIN
// to CHUNK_MAX candles) are fetched - ready before the scroll reaches them.
const PRELOAD_SCREENS = 2;
const CHUNK_SCREENS = 4;
const CHUNK_MIN = 500;
const CHUNK_MAX = 5000;
const LEVEL_CANDLES = 15; // a swing level's width
const LEVEL_HEIGHT_PX = 2;

const sec = (iso: string) => Math.floor(new Date(iso).getTime() / 1000);


function lastLevels(swings: ChartSwing[]): ChartSwing[] {
  const last = new Map<SwingKind, ChartSwing>();
  for (const s of swings) last.set(s.kind, s);
  return [...last.values()];
}

// Local time on the axis, as the rest of the dashboard (the library labels in UTC).
function tickMark(time: Time, type: TickMarkType): string {
  const d = new Date((time as number) * 1000);
  switch (type) {
    case TickMarkType.Year:
      return String(d.getFullYear());
    case TickMarkType.Month:
      return d.toLocaleString('en-GB', { month: 'short' });
    case TickMarkType.DayOfMonth:
      return d.toLocaleString('en-GB', { day: '2-digit', month: 'short' });
    default:
      return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false });
  }
}

type InfoRow = { text: string; color?: string };

// What the crosshair's candle shows (top-left box): the candle, the swings
// made on it, the swing levels known at it (the last confirmed swing of
// each kind, the latest liquidity zone) and EMA 9 / VWAP with its signal.
function infoAt(chart: PaperChart, t: number): InfoRow[] {
  const rows: InfoRow[] = [];
  const candle = chart.candles.find((c) => sec(c.time) === t);
  if (!candle) return rows;
  rows.push({ text: formatDateTime(t * 1000) });
  rows.push({
    text:
      `O ${formatPrice(candle.open)} H ${formatPrice(candle.high)} ` +
      `L ${formatPrice(candle.low)} C ${formatPrice(candle.close)}`,
    color: Number(candle.close) >= Number(candle.open) ? GREEN : RED,
  });
  for (const s of chart.swings.filter((x) => sec(x.time) === t)) {
    rows.push({ text: `${s.kind} made here ${formatPrice(s.price)}`, color: SWING_COLOR[s.kind] });
  }
  // A swing / zone counts once the candle that confirmed it has closed - by this candle's close.
  const known = (confirmedAt: string) => sec(confirmedAt) <= t;
  const levels = (['HH', 'HL', 'LH', 'LL'] as const).flatMap((kind) => {
    const last = chart.swings.filter((x) => x.kind === kind && known(x.confirmed_at)).at(-1);
    return last ? [`${kind} ${formatPrice(last.price)}`] : [];
  });
  if (levels.length > 0) rows.push({ text: `levels: ${levels.join(' · ')}` });
  for (const kind of ['low', 'high'] as const) {
    const zone = chart.liquidity_zones
      .filter((z) => z.kind === kind && known(z.confirmed_at))
      .at(-1);
    if (zone) {
      rows.push({
        text: `${kind === 'low' ? 'green' : 'red'} zone ${formatPrice(zone.btm)}–${formatPrice(zone.top)}`,
        color: kind === 'low' ? GREEN : RED,
      });
    }
  }
  const line = chart.vwap.find((p) => sec(p.time) === t);
  if (line) {
    rows.push({
      text: `EMA 9 ${formatPrice(line.ema)} · VWAP ${line.vwap === null ? '—' : formatPrice(line.vwap)}`,
      color: ORANGE,
    });
    if (line.signal) {
      const buy = line.signal === 'long';
      rows.push({ text: buy ? 'BUY signal' : 'SELL signal', color: buy ? BLUE : RED });
    }
  }
  const st = chart.supertrend.find((p) => sec(p.time) === t);
  if (st && st.line !== null) {
    const up = st.trend === 1;
    rows.push({
      text:
        `supertrend ${up ? 'up' : 'down'} · ${formatPrice(st.line)}` +
        (st.signal ? ` · ${st.signal === 'long' ? 'Buy' : 'Sell'}` : ''),
      color: up ? GREEN : RED,
    });
  }
  const band = chart.bands.find((p) => sec(p.time) === t);
  if (band && band.band !== null) {
    const bull = band.state === 1;
    rows.push({
      text:
        `trend ${bull ? 'bullish' : 'bearish'} · band ${formatPrice(band.band)}` +
        (band.inner === null ? '' : ` · value ${formatPrice(band.inner)}`),
      color: bull ? GREEN : RED,
    });
  }
  if (band?.signal) {
    const up = band.signal === 'long';
    rows.push({ text: up ? 'band break-up' : 'band break-down', color: up ? GREEN : RED });
  }
  return rows;
}

// The trades open during the crosshair's candle (the box next to it, only
// when there are any): positions and backtest trades, with when they opened.
function tradesAt(chart: PaperChart, t: number): InfoRow[] {
  const step = TIMEFRAME_SECONDS[chart.timeframe] ?? 60;
  const during = (opened: string, closed: string | null) =>
    sec(opened) < t + step && (closed === null || sec(closed) >= t);
  const when = (opened: string, closed: string | null) =>
    `opened ${formatDateTime(opened)}${closed ? ` · closed ${formatDateTime(closed)}` : ' · open'}`;
  const color = (direction: string) => (direction === 'long' ? GREEN : RED);
  const result = (value: number) => (value >= 0 ? GREEN : RED);
  const rows: InfoRow[] = [];
  for (const p of chart.positions.filter((x) => during(x.opened_at, x.closed_at))) {
    const pnl = p.closed_at ? p.realized_pnl_usd : p.unrealized_pnl_usd;
    const pct = pnlPercent(pnl, p.initial_margin_usd);
    rows.push({ text: `#${String(p.id)} ${p.mode} ${p.direction}`, color: color(p.direction) });
    rows.push({ text: when(p.opened_at, p.closed_at) });
    rows.push({
      text: [
        `${formatPrice(p.entry_price)}${p.close_price ? ` → ${formatPrice(p.close_price)}` : ''}`,
        ...(p.stop_loss_price ? [`SL ${formatPrice(p.stop_loss_price)}`] : []),
        ...(p.take_profit_price ? [`TP ${formatPrice(p.take_profit_price)}`] : []),
      ].join(' · '),
    });
    rows.push({
      text: `${p.closed_at ? 'realized' : 'unrealized'} ${formatUsd(pnl)}${pct ? ` (${pct})` : ''}`,
      color: pnl === null ? undefined : result(Number(pnl)),
    });
    rows.push({ text: `${p.entry_reason ?? '—'}${p.closed_at ? ` → ${p.exit_reason ?? '—'}` : ''}` });
  }
  for (const b of chart.backtest.filter((x) => during(x.opened_at, x.closed_at))) {
    const ret = Number(b.return_pct);
    rows.push({ text: `backtest ${b.direction}`, color: color(b.direction) });
    // Still open when the backtest ended: its last candle is the test's end, not a close.
    const ended = b.exit_reason === OPEN_AT_END;
    rows.push({
      text: ended
        ? `opened ${formatDateTime(b.opened_at)} · test ended ${formatDateTime(b.closed_at)}`
        : when(b.opened_at, b.closed_at),
    });
    if (b.margin_usd !== null && b.pnl_usd !== null) {
      // An averaging position: its buys, its peak margin and the result in $.
      const pnl = Number(b.pnl_usd);
      const margin = Number(b.margin_usd);
      const value = positionValue(b);
      rows.push({
        text:
          `${String(addCount(b))} adds · avg ${formatPrice(b.entry_price)} → ` +
          `${formatPrice(b.close_price)} · peak margin ${formatUsd(String(margin))}`,
      });
      rows.push({ text: `position ${formatUsd(value.entry)} → ${formatUsd(value.close)}` });
      // The position at this candle's close (its fills so far, before fees).
      const candle = chart.candles.find((c) => sec(c.time) === t);
      if (candle) {
        const hedgeClose = candle.hedge_close ? Number(candle.hedge_close) : null;
        const now = stateAt(b, t + step, Number(candle.close), hedgeClose);
        rows.push({
          text:
            `now: avg ${formatPrice(String(now.avgEntry))} · margin ${formatUsd(String(now.margin))} ` +
            `· PnL ${formatUsd(String(now.pnl))}`,
          color: result(now.pnl),
        });
        const hedged = b.fills.some(isShortFill);
        if (hedged) {
          const shortPnl = now.shortPnl;
          rows.push({
            text:
              `short now: margin ${formatUsd(String(now.shortMargin))} · PnL ` +
              `${shortPnl === null ? '—' : formatUsd(String(shortPnl))}` +
              (shortPnl === null ? '' : ` · total ${formatUsd(String(now.pnl + shortPnl))}`),
            color: PINK,
          });
        }
      }
      rows.push({
        text:
          `${ended ? 'at the test end ' : ''}${formatUsd(String(pnl))} ` +
          `(${((pnl / margin) * 100).toFixed(1)}% of margin)`,
        color: result(pnl),
      });
      if (b.hedge_pnl_usd !== null) {
        // An averaging hedge position: the long's part and its shorts'.
        const shorts = Number(b.hedge_pnl_usd);
        rows.push({
          text: `= long ${formatUsd(String(pnl - shorts))} + shorts ${formatUsd(b.hedge_pnl_usd)}`,
          color: result(shorts),
        });
      }
      rows.push({ text: `${b.entry_reason ?? '—'} → ${ended ? 'open at the test end' : b.exit_reason}` });
      // The fills on this candle, each with the position right after it.
      const profits = unitProfits(b);
      b.fills.forEach((f, k) => {
        if (sec(f.time) < t || sec(f.time) >= t + step) {
          return;
        }
        if (isShortFill(f)) {
          // The short is on the hedge asset: its price, its margin, its realized PnL.
          const pnl = f.realized_pnl_usd === null ? '' : `, PnL ${formatUsd(f.realized_pnl_usd)}`;
          rows.push({
            text:
              `${SHORT_FILLS[f.side] ?? f.side} · ETH ${formatPrice(f.price)}, ` +
              `margin ${formatUsd(f.margin_usd)}${pnl}`,
            color: PINK,
          });
          return;
        }
        // A short paper's reduction buys back (backend app/backtest/averaging.py).
        const reduced = b.direction === 'short' ? 'bought back' : 'sold';
        const what =
          f.side === 'sell'
            ? `${reduced} a unit ${formatUsd(f.notional_usd)} at ${formatPrice(f.price)} ` +
              `(unit profit ${formatUsd(profits[k])}), -${formatUsd(f.margin_usd)} margin`
            : `${k === 0 ? 'entry' : 'add'} at ${formatPrice(f.price)} +${formatUsd(f.margin_usd)}`;
        rows.push({
          text:
            `${what} → margin ${formatUsd(f.total_margin_usd)}, ` +
            `avg ${formatPrice(f.avg_entry)}, ×${f.leverage.toFixed(1)}, ` +
            `liq ${formatPrice(f.liquidation_price)}, PnL ${formatUsd(f.pnl_usd)}`,
          color: AMBER,
        });
      });
      continue;
    }
    rows.push({
      text: `${formatPrice(b.entry_price)} → ${formatPrice(b.close_price)}${b.stop_loss_price ? ` · SL ${formatPrice(b.stop_loss_price)}` : ''}`,
    });
    rows.push({ text: `${ret >= 0 ? '+' : ''}${ret.toFixed(2)}% of price`, color: result(ret) });
    rows.push({ text: `${b.entry_reason ?? '—'} → ${b.exit_reason}` });
  }
  return rows;
}

// Draws `chart` on `api`. Returns its repaint for the same chart with older
// candles prepended (loaded as it scrolls back): the candles, VWAP + EMA 9,
// trade lines and markers follow; the overlays of the first window stay.
function draw(api: IChartApi, chart: PaperChart): (data: PaperChart) => void {
  const step = TIMEFRAME_SECONDS[chart.timeframe] ?? 60;
  const digits = priceDigits(Number(chart.candles.at(-1)?.close ?? 1));
  const priceFormat = { type: 'price' as const, precision: digits, minMove: 10 ** -digits };
  const quiet = { lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false };

  const candles: ISeriesApi<'Candlestick'> = api.addSeries(CandlestickSeries, {
    upColor: GREEN,
    downColor: RED,
    borderUpColor: GREEN,
    borderDownColor: RED,
    wickUpColor: GREEN,
    wickDownColor: RED,
    priceFormat,
  });
  // VWAP + EMA 9: the series here, their points in repaint.
  const vwapLines: [ISeriesApi<'Line'>, (p: VwapPoint) => number | null][] = [];
  if (chart.vwap.length > 0) {
    const line = (title: string, color: string, pick: (p: VwapPoint) => number | null) =>
      vwapLines.push([
        api.addSeries(LineSeries, { title, color, lineWidth: 2, priceFormat, ...quiet }),
        pick,
      ]);
    line('VWAP', ORANGE, (p) => p.vwap);
    line('EMA 9', BLUE, (p) => p.ema);
  }

  // Trend bands: the active band (green lower while bullish, red upper while
  // bearish), its value zone's edge dotted - the series here, their points in repaint.
  const bandLines: [ISeriesApi<'Line'>, (p: BandPoint) => number | null][] = [];
  const bandLine = (title: string, lineStyle: LineStyle, pick: (p: BandPoint) => number | null) =>
    bandLines.push([
      api.addSeries(LineSeries, { title, lineWidth: 1, lineStyle, priceFormat, ...quiet }),
      pick,
    ]);
  bandLine('band', LineStyle.Solid, (p) => p.band);
  bandLine('value', LineStyle.Dotted, (p) => p.inner);

  // A Supertrend paper's Supertrend: green in an uptrend, red in a downtrend,
  // 2px - the series here, its points in repaint.
  const supertrendLine =
    chart.supertrend.length > 0
      ? api.addSeries(LineSeries, { title: 'supertrend', lineWidth: 2, priceFormat, ...quiet })
      : null;

  // An averaging hedge paper's backtest longs: each one's average entry at the
  // moment, a green step path of its own (drawn in repaint).
  const hedged = chart.kind === 'averaging_hedge';

  const markerApi = createSeriesMarkers(candles, []);
  let attached: ISeriesPrimitive<Time>[] = [];
  const attach = (primitive: ISeriesPrimitive<Time>) => {
    candles.attachPrimitive(primitive);
    attached.push(primitive);
  };
  const repaint = (data: PaperChart) => {
    const times = data.candles.map((c) => sec(c.time));
    const first = times[0] ?? 0;
    // Every point must sit on a candle: a time inside one goes to its open.
    const onCandle = (iso: string) => Math.max(first, Math.floor(sec(iso) / step) * step);
    candles.setData(
      data.candles.map((c) => ({
        time: sec(c.time) as UTCTimestamp,
        open: Number(c.open),
        high: Number(c.high),
        low: Number(c.low),
        close: Number(c.close),
      })),
    );

    for (const [series, pick] of vwapLines) {
      series.setData(
        data.vwap.map((p) => {
          const time = sec(p.time) as UTCTimestamp;
          const value = pick(p);
          return value === null ? { time } : { time, value };
        }),
      );
    }

    for (const [series, pick] of bandLines) {
      series.setData(
        data.bands.map((p) => {
          const time = sec(p.time) as UTCTimestamp;
          const value = pick(p);
          return value === null ? { time } : { time, value, color: p.state === 1 ? GREEN : RED };
        }),
      );
    }

    supertrendLine?.setData(
      data.supertrend.map((p) => {
        const time = sec(p.time) as UTCTimestamp;
        return p.line === null
          ? { time }
          : { time, value: p.line, color: p.trend === 1 ? GREEN : RED };
      }),
    );

    for (const primitive of attached) {
      candles.detachPrimitive(primitive);
    }
    attached = [];

    // Every swing's level: a LEVEL_HEIGHT_PX bar at its
    // price from its pivot candle, LEVEL_CANDLES wide (to the last candle at most).
    const lastCandle = times.at(-1) ?? first;
    for (const s of data.swings) {
      const start = onCandle(s.time);
      const end = Math.min(start + LEVEL_CANDLES * step, lastCandle);
      attach(
        new Rectangle(
          { time: start as UTCTimestamp, price: s.price },
          { time: end as UTCTimestamp, price: s.price },
          SWING_COLOR[s.kind],
          LEVEL_HEIGHT_PX,
        ),
      );
    }
    // Liquidity swing zones: the pivot candle across its count.
    for (const z of data.liquidity_zones) {
      attach(
        new Rectangle(
          { time: sec(z.start) as UTCTimestamp, price: z.top },
          { time: sec(z.end) as UTCTimestamp, price: z.btm },
          ZONE_FILL[z.kind === 'low' ? 'low' : 'high'],
        ),
      );
    }

    // Trades: entry -> exit (an open position -> now), dashed, long green, short red.
    const lastTime = times.at(-1) ?? first;
    const lastClose = Number(data.candles.at(-1)?.close ?? 0);
    // One dashed segment per trade (position or backtest trade), so they never
    // join: entry -> exit, an open position -> the last close.
    const trade = (
      opened: string,
      entry: string,
      end: number,
      exit: number,
      direction: string,
    ) => {
      attach(
        new Segment(
          { time: onCandle(opened) as UTCTimestamp, price: Number(entry) },
          { time: end as UTCTimestamp, price: exit },
          direction === 'long' ? GREEN : RED,
        ),
      );
    };
    for (const p of data.positions) {
      trade(
        p.opened_at,
        p.entry_price,
        p.closed_at ? onCandle(p.closed_at) : lastTime,
        p.closed_at ? Number(p.close_price ?? p.entry_price) : lastClose,
        p.direction,
      );
    }
    // Backtest trades closed before the first candle: in the summary only.
    const shown = data.backtest.filter((t) => sec(t.closed_at) >= first);
    for (const t of shown) {
      if (hedged) {
        // Its average entry: each long fill's state, held to the next fill
        // (a step) and to the close - a path per position, never joining the next.
        const points: Point[] = [];
        let held: number | null = null;
        for (const f of t.fills.filter((x) => !isShortFill(x))) {
          const time = onCandle(f.time) as UTCTimestamp;
          if (held !== null) {
            points.push({ time, price: held });
          }
          points.push({ time, price: f.avg_entry });
          held = f.avg_entry;
        }
        if (held !== null) {
          points.push({ time: onCandle(t.closed_at) as UTCTimestamp, price: held });
          attach(new Path(points, GREEN));
        }
      } else {
        trade(t.opened_at, t.entry_price, onCandle(t.closed_at), Number(t.close_price), t.direction);
      }
      // A liquidated or given-up averaging position: a red dashed line across the chart.
      if (FORCED_EXITS.includes(t.exit_reason)) {
        attach(new VerticalLine(onCandle(t.closed_at) as UTCTimestamp, RED));
      }
    }

    // Markers on the candles: swings, BUY / SELL, fills, backtest fills.
    const markers: SeriesMarker<Time>[] = [];
    for (const s of data.swings) {
      const high = s.kind === 'HH' || s.kind === 'LH';
      markers.push({
        time: onCandle(s.time) as UTCTimestamp,
        position: high ? 'aboveBar' : 'belowBar',
        shape: 'circle',
        size: 0, // the letters only - the library draws no shape at size 0
        color: SWING_COLOR[s.kind],
        text: s.kind,
      });
    }
    for (const p of data.vwap) {
      if (!p.signal) continue;
      const buy = p.signal === 'long';
      markers.push({
        time: sec(p.time) as UTCTimestamp,
        position: buy ? 'belowBar' : 'aboveBar',
        shape: buy ? 'arrowUp' : 'arrowDown',
        color: buy ? BLUE : RED,
        text: buy ? 'BUY' : 'SELL',
      });
    }
    for (const p of data.supertrend) {
      if (!p.signal) continue;
      const buy = p.signal === 'long';
      markers.push({
        time: sec(p.time) as UTCTimestamp,
        position: buy ? 'belowBar' : 'aboveBar',
        shape: buy ? 'arrowUp' : 'arrowDown',
        color: buy ? GREEN : RED,
        text: buy ? 'Buy' : 'Sell',
      });
    }
    for (const p of data.bands) {
      if (!p.signal) continue;
      const up = p.signal === 'long';
      markers.push({
        time: sec(p.time) as UTCTimestamp,
        position: up ? 'belowBar' : 'aboveBar',
        shape: up ? 'arrowUp' : 'arrowDown',
        color: up ? GREEN : RED,
        text: 'BRK',
      });
    }
    for (const p of data.positions) {
      for (const f of p.fills) {
        if (f.price === null) continue;
        const opening = (p.direction === 'long') === (f.side === 'buy');
        markers.push({
          time: onCandle(f.time) as UTCTimestamp,
          position: 'atPriceMiddle',
          price: Number(f.price),
          shape: 'circle',
          size: 0.5,
          color: opening ? BLUE : AMBER,
        });
      }
    }
    for (const t of shown) {
      // An averaging position: every buy at its price with its margin ("+$" an
      // add); every unwind of its dip adds above its candle, cyan ("sold $" the
      // size sold) - a dot at the price hid on the candle's body.
      t.fills.forEach((f, k) => {
        // Before the loaded candles: skipped, not stacked on the first one.
        if (sec(f.time) < first) {
          return;
        }
        if (isShortFill(f)) {
          // A hedge short's fill: a pink dot above the candle (its price is the hedge asset's).
          markers.push({
            time: onCandle(f.time) as UTCTimestamp,
            position: 'aboveBar',
            shape: 'circle',
            color: PINK,
            size: 0.5,
          });
          return;
        }
        if (f.side === 'sell') {
          // A short paper's reduction: a buy back, under the candle.
          const short = t.direction === 'short';
          markers.push({
            time: onCandle(f.time) as UTCTimestamp,
            position: short ? 'belowBar' : 'aboveBar',
            shape: short ? 'arrowUp' : 'arrowDown',
            color: CYAN,
            text: `${short ? 'bought back' : 'sold'} $${Number(f.notional_usd).toFixed(0)}`,
          });
          return;
        }
        markers.push({
          time: onCandle(f.time) as UTCTimestamp,
          position: 'atPriceMiddle',
          price: Number(f.price),
          shape: 'circle',
          color: AMBER,
          size: 0.5,
          text: `${k === 0 ? '' : '+'}$${String(Number(f.margin_usd))}`,
        });
      });
      // A position still open when the backtest ended has no close: a grey
      // square at the test's last candle instead, with its result there.
      const open = t.exit_reason === OPEN_AT_END;
      if (open && sec(t.closed_at) >= first) {
        const result =
          t.pnl_usd !== null
            ? formatUsd(t.pnl_usd)
            : `${Number(t.return_pct) >= 0 ? '+' : ''}${Number(t.return_pct).toFixed(2)}%`;
        markers.push({
          time: onCandle(t.closed_at) as UTCTimestamp,
          position: 'atPriceMiddle',
          price: Number(t.close_price),
          shape: 'square',
          color: MUTED,
          size: 0.7,
          text: `test end ${result}`,
        });
      }
      const points: (readonly [string, string])[] =
        t.fills.length > 0
          ? open
            ? []
            : [[t.closed_at, t.close_price]]
          : [
              [t.opened_at, t.entry_price],
              [t.closed_at, t.close_price],
            ];
      for (const [at, price] of points) {
        markers.push({
          time: onCandle(at) as UTCTimestamp,
          position: 'atPriceMiddle',
          price: Number(price),
          shape: 'circle',
          color: VIOLET,
          size: 0.5,
        });
      }
    }
    markers.sort((a, b) => (a.time as number) - (b.time as number));
    markerApi.setMarkers(markers);
  };
  repaint(chart);

  // Levels: the current (last) swing of each kind; an open position's entry, SL and TP.
  for (const s of lastLevels(chart.swings)) {
    candles.createPriceLine({
      price: s.price,
      color: SWING_COLOR[s.kind],
      lineStyle: LineStyle.Dashed,
      lineWidth: 1,
      title: s.kind,
    });
  }
  for (const p of chart.positions.filter((x) => !x.closed_at)) {
    const levels: [string | null, string, string, LineStyle][] = [
      [p.entry_price, 'entry', BLUE, LineStyle.Solid],
      [p.stop_loss_price, 'SL', AMBER, LineStyle.Dotted],
      [p.take_profit_price, 'TP', GREEN, LineStyle.Dotted],
    ];
    for (const [price, label, color, lineStyle] of levels) {
      if (price === null) continue;
      candles.createPriceLine({
        price: Number(price),
        color,
        lineStyle,
        lineWidth: 1,
        title: `#${String(p.id)} ${label}`,
      });
    }
  }

  return repaint;
}

// The older candles (and their overlays) loaded as the chart scrolls back,
// kept across data refreshes of the same paper; `done` once the stored
// history ends.
interface Older extends CandleChunk {
  paperId: number;
  done: boolean;
}

// `chart` with the older candles and their overlays before its first. A
// swing or zone near a chunk's end can come twice (the chunk after it or the
// first window has it too - computed the same way): kept once.
function withOlder(chart: PaperChart, older: Older): PaperChart {
  const first = chart.candles[0];
  if (!first || older.candles.length === 0) {
    return chart;
  }
  const before = (x: { time: string }) => sec(x.time) < sec(first.time);
  const swingKey = (s: ChartSwing) => `${s.kind} ${String(sec(s.time))}`;
  const zoneKey = (z: LiquidityZone) => `${z.kind} ${String(sec(z.start))}`;
  const unique = <T,>(items: T[], key: (x: T) => string, had: T[]): T[] => {
    const seen = new Set(had.map(key));
    return items.filter((x) => {
      const k = key(x);
      if (seen.has(k)) {
        return false;
      }
      seen.add(k);
      return true;
    });
  };
  const swings = unique(older.swings, swingKey, chart.swings);
  const zones = unique(older.liquidity_zones, zoneKey, chart.liquidity_zones);
  return {
    ...chart,
    candles: [...older.candles.filter(before), ...chart.candles],
    vwap: [...older.vwap.filter(before), ...chart.vwap],
    bands: [...older.bands.filter(before), ...chart.bands],
    supertrend: [...older.supertrend.filter(before), ...chart.supertrend],
    swings: [...swings, ...chart.swings],
    liquidity_zones: [...zones, ...chart.liquidity_zones],
  };
}

// `chart` without the hidden overlays' data: their lines, markers, levels and
// hover rows all go with it.
function withoutHidden(chart: PaperChart, hidden: Set<Indicator>): PaperChart {
  return {
    ...chart,
    swings: hidden.has('swings') ? [] : chart.swings,
    liquidity_zones: hidden.has('zones') ? [] : chart.liquidity_zones,
    vwap: hidden.has('vwap') ? [] : chart.vwap,
    bands: hidden.has('bands') ? [] : chart.bands,
    supertrend: hidden.has('supertrend') ? [] : chart.supertrend,
  };
}

export default function StrategyChart({ chart }: { chart: PaperChart }) {
  const container = useRef<HTMLDivElement>(null);
  const older = useRef<Older | null>(null);
  // The visible time range, kept across data refreshes of the same paper.
  const view = useRef<{ paperId: number; from: Time; to: Time } | null>(null);
  // The top-left box: the crosshair's candle, the last candle otherwise.
  const [info, setInfo] = useState<InfoRow[]>([]);
  const [trades, setTrades] = useState<InfoRow[]>([]);
  const [hidden, toggle] = useHiddenIndicators();

  useEffect(() => {
    const el = container.current;
    if (!el) return;
    const api = createChart(el, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: MUTED },
      grid: { vertLines: { color: GRID }, horzLines: { color: GRID } },
      rightPriceScale: { borderColor: GRID },
      timeScale: { borderColor: GRID, timeVisible: true, tickMarkFormatter: tickMark },
      localization: {
        locale: 'en-GB',
        timeFormatter: (time: Time) => formatDateTime((time as number) * 1000),
      },
    });
    if (older.current?.paperId !== chart.paper_id) {
      older.current = {
        paperId: chart.paper_id,
        candles: [],
        vwap: [],
        bands: [],
        supertrend: [],
        swings: [],
        liquidity_zones: [],
        done: false,
      };
    }
    const kept: Older = older.current;
    let data = withoutHidden(withOlder(chart, kept), hidden);
    const repaint = draw(api, data);
    const lastCandle = chart.candles.at(-1);
    const latest = () => (lastCandle ? infoAt(data, sec(lastCandle.time)) : []);
    setInfo(latest());
    setTrades([]);
    api.subscribeCrosshairMove((param) => {
      const t = param.time as number | undefined;
      setInfo(t === undefined ? latest() : infoAt(data, t));
      setTrades(t === undefined ? [] : tradesAt(data, t)); // only for a hovered candle
    });
    const timeScale = api.timeScale();

    // Older candles, a chunk at a time, ahead of the scroll. Prepending them
    // keeps the view where it is (the library anchors it to the last candle).
    let loading = false;
    let disposed = false;
    const loadOlder = async () => {
      const range = timeScale.getVisibleLogicalRange();
      const first = data.candles[0];
      if (!range || !first || loading || kept.done || disposed) {
        return;
      }
      const width = Math.max(range.to - range.from, 1);
      if (range.from > width * PRELOAD_SCREENS) {
        return;
      }
      loading = true;
      const limit = Math.min(Math.max(Math.round(width * CHUNK_SCREENS), CHUNK_MIN), CHUNK_MAX);
      let loaded = false;
      try {
        const chunk = await fetchCandleChunk(chart.paper_id, first.time, limit);
        if (chunk !== null && !disposed) {
          kept.candles = [...chunk.candles, ...kept.candles];
          kept.vwap = [...chunk.vwap, ...kept.vwap];
          kept.bands = [...chunk.bands, ...kept.bands];
          kept.supertrend = [...chunk.supertrend, ...kept.supertrend];
          kept.swings = [...chunk.swings, ...kept.swings];
          kept.liquidity_zones = [...chunk.liquidity_zones, ...kept.liquidity_zones];
          kept.done = chunk.candles.length < limit;
          data = withoutHidden(withOlder(chart, kept), hidden);
          repaint(data);
          loaded = true;
        }
      } catch {
        // Retried on the next scroll.
      } finally {
        loading = false;
      }
      if (loaded) {
        void loadOlder(); // still near the start (zoomed far out): the next chunk
      }
    };
    timeScale.subscribeVisibleLogicalRangeChange(() => {
      void loadOlder();
    });
    const shown = view.current;
    const last = chart.candles.at(-1);
    if (shown && shown.paperId === chart.paper_id) {
      timeScale.setVisibleRange({ from: shown.from, to: shown.to });
    } else if (last) {
      const to = sec(last.time);
      timeScale.setVisibleRange({
        from: (to - INITIAL_DAYS * 86_400) as UTCTimestamp,
        to: to as UTCTimestamp,
      });
    }
    void loadOlder();
    return () => {
      disposed = true;
      const range = timeScale.getVisibleRange();
      view.current = range ? { paperId: chart.paper_id, ...range } : null;
      api.remove();
    };
  }, [chart, hidden]);

  // The Supertrend only on a Supertrend paper's chart.
  const toggles = INDICATORS.filter(([key]) => key !== 'supertrend' || chart.supertrend.length > 0);
  return (
    <div className="space-y-1">
      <div className="relative h-140 w-full">
        <div ref={container} className="h-full w-full" />
        <div className="pointer-events-none absolute left-2 top-2 z-10 flex max-w-[90%] flex-wrap items-start gap-2 text-xs">
          {[info, trades]
            .filter((rows) => rows.length > 0)
            .map((rows, box) => (
              <div key={box} className="space-y-0.5 rounded bg-background/80 px-2 py-1">
                {rows.map((row, k) => (
                  <div key={k} style={row.color ? { color: row.color } : undefined}>
                    {row.text}
                  </div>
                ))}
              </div>
            ))}
        </div>
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {toggles.map(([key, label]) => (
          <label key={key} className="flex cursor-pointer items-center gap-1">
            <Checkbox checked={!hidden.has(key)} onCheckedChange={() => toggle(key)} />
            {label}
          </label>
        ))}
      </div>
    </div>
  );
}
