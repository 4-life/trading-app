# Dashboard

Docker service: `dashboard`

React, server-side rendered (SSR). Dark theme. Talks only to the [api](api.md). Protected by the app password (see [README: Security](../README.md#security)).

On phones (under 640 px) buttons, inputs and checkboxes are larger touch targets, inputs at 16 px text (iOS zooms into smaller ones); wide tables (the sweep results) scroll sideways.

## Login

`/login` asks for the app password and exchanges it for an API token ([api: Authentication](api.md#authentication)), kept in an HTTP-only `session` cookie (7 days). Without a valid token every page redirects to `/login`. The cookie is `Secure` in production, so the dashboard must be served over HTTPS (see [deployment](deployment.md)).

All API calls happen on the dashboard server (route loaders/actions), which forwards the token and the visitor's IP (`X-Forwarded-For`). The page refreshes its data every 15 seconds.

- **Loading**: the page and its structure render at once — each card shows a **skeleton** (its title and placeholder lines) until its data streams in, card by card, as the API answers (`components/section.tsx`); nothing waits for the slowest call. The tab title (the PnL) and the favicon follow once their data is in.
- **API unreachable**: a card whose call fails keeps the **last data it had** on screen, and a toast says "API unreachable — showing the last data" (one toast, while any part fails; it closes once all answer again). A first load that fails shows the card's "Unavailable". The same when the browser can't reach the dashboard server on a refresh: the page keeps its last data and a toast says so, instead of the error page. A refresh keeps the current data on screen until the new data arrives. An expired login (`401`) goes to `/login`.

## Header

- Title.
- [System health](#system-health).
- Current UTC time (`HH:MM:SS UTC`, ticking every second) — candles, logs and the server run in UTC.
- Buttons that open the [assets](#assets) and [settings](#settings) modals.
- Log out.

## Footer

- App name and the current year, below the cards.

## Live Cards

Equity, Available Balance, Open Positions, Exposure, Total PnL, Unrealized PnL, Realized PnL.

- Big **Auto trading** switch — whether the app places orders on its own for **live** papers: entries, exits (strategy exits, take-profits) and [maintenance-margin closes](execution-engine.md#liquidation). While it's off, live positions are left as they are — closed only by the owner (Close / Doesn't exist, or on Hyperliquid) or by Hyperliquid's own liquidation. **Off after every start** (kept in [Redis](redis.md), which keeps nothing on disk), so a restarted VPS never acts on positions the owner may have closed on Hyperliquid meanwhile. Demo papers ignore it.
- Without a Hyperliquid API key or readable live balance, the cards show "no live data".

## Demo Cards

The same cards for demo mode, smaller than the live ones and on a light sky tint — not real money. No auto-trading switch; a **Reset** button instead (see [papers: Demo Reset](papers.md#demo-reset)).

## Papers

Create and manage [papers](papers.md): **New paper** (a button in the card's header, the form in a dialog that closes once the paper is created — an error stays in it) to create one (type single / scanner / averaging, executor, asset — not for a scanner, timeframe, direction, leverage, and for an averaging paper its [position management](papers.md#averaging-papers)), **Edit** (leverage, and an averaging paper's position management, in a dialog — see [editing](papers.md#editing); a single paper's dialog (and the New paper form) has its **stop-loss / take-profit % of price** ([stop-loss and take-profit](papers.md#stop-loss-and-take-profit)), and its **Find best params** sweeps leverage × stop-loss × take-profit (no max margin; the table: leverage, SL, TP, return, train / test, won, SL / TP hits, liquidations, max drawdown); an averaging paper's dialog also has **Find best params**: a max leverage (the asset's max by default) and max margin (the paper's, else $1,000) start the [settings sweep](api.md) in the API's background — disabled while any sweep runs. The dialog shows the paper's latest sweep as soon as it opens ("Testing… 1,234 of 3,072 runs", polled every 5 s while it runs) and its best 5 runs so far by the stat picked (**Best by**: total, test, train, closed PnL, won, give-ups, most margin, cash drawdown) — leverage, initial size, take-profit, mode (hold / intraday / intraday-reopen), total, train / test, won, give-ups, most margin, drained (the date its cash ran out and it stopped trading, red; drained runs listed last). Nothing about the paper is changed; an averaging paper's runs in two tables — **Fixed budget** and **Compounding**), **Batch sweep** (a button next to New paper: tick averaging papers, one budget per paper, Start — their sweeps run one after another, for overnight; the dialog shows "paper 3 of 10" and the running paper's runs, with **Stop batch**; each paper's results in its Edit dialog), switch demo → live, disable. Above the table, **filters** by type, executor and asset (each "all" or one of the values the papers have) and three toggles, **Enabled only**, **Live only** and **Favourites only** (off: all) — kept in this browser; the star next to a paper's id marks it as a favourite (kept in this browser too); a kept value no paper has any more (a removed executor, a deleted paper's asset) counts as "all". The papers table shows a paper's position management in short under its leverage (e.g. "$10 · auto add $10 ×3 · TP 30% · DD 40%"). A paper being [prepared](papers.md#preparation) shows a spinner with its step (backfilling / backtesting) and can't be deleted until it's ready; a failed preparation shows the error. A scanner shows as "market (scanner)"; the papers it created show "auto · #<scanner id>". Scanners and their papers can't go live yet. Shows `profitability_demo` / `profitability_live` per paper, and whether the [risk-engine](risk-engine.md) has blocked or disabled it, with the reason.

## Positions Table

Open and closed positions.

| Column | |
|---|---|
| Type | live / demo |
| Asset | |
| Dir | long / short |
| Size | |
| Entry Price | |
| Current Price | |
| Unrealized PnL | |
| Margin | an open position's current margin, adds included |
| Exposure | |
| Exit | the position's exit rule |

- Actions on an open position:
  - **Close** — queues a market exit (reason `manual_close`).
  - **Doesn't exist** (live only) — for a position already closed on Hyperliquid by hand or liquidated there, e.g. while the VPS was down. A dialog asks for the price it closed at; the position is recorded closed at that price (reason `closed_on_exchange`), realized PnL minus the entry fee and an estimated taker fee for the exit. Nothing is sent to the exchange. Don't press Close for such a position — a market order on the opposite side would open a new one.
- Filters: open / closed, live / demo.
- The open positions' title shows the margin they lock together (the filtered rows').

## Strategy Chart

A [Lightweight Charts](https://github.com/tradingview/lightweight-charts) (TradingView) candlestick chart of one paper, shown when at least one exists. No legend.

- **Paper selector** — every paper (any executor); the pick is kept in the URL (`?chartPaper=`, default the first one). Only that paper's data is loaded, and only one chart exists on the page: switching destroys the old one. While the picked paper's data loads (a React transition around the navigation), the old chart stays dimmed under a "Loading chart…" spinner and the selector is disabled.
- **Scale** — the paper's timeframe, its whole stored history (up to 6000 candles — 15m: ~62 days, the forming one included — or further back, up to 20,000, to the open of an older position or backtest position still shown, so all its fills sit on candles; the backtest summary and positions table (the **Backtest log** under the chart, collapsed by default) cover every backtest position, the chart draws those on its candles). **Older candles load as you scroll back**: once the view is within two view widths of the loaded start, the next four view widths (500–5,000 candles, `GET /papers/{id}/candles`, through the dashboard's `/chart-candles`) are fetched ahead, so they're ready before the scroll reaches them; every overlay comes with them — VWAP + EMA 9 and BUY / SELL, the trend bands, HH / LL swings and liquidity zones — computed from 5,000 candles before the chunk (the bands' whole path) and 200 after it (confirming the swings at its end), so they match the full history; a swing or zone two chunks share is drawn once. Loaded candles are kept across data refreshes of the same paper, scrolled and zoomed with the mouse (drag, wheel) or on touch screens by dragging (pan) and pinching (zoom); it opens on the last 7 days, and a data refresh keeps the shown range. Times are local.
- **Info box** (top-left) — for the candle under the crosshair (the last candle when the pointer is off the chart): time and OHLC; the swings made on it; the swing levels known at its close (the last confirmed HH / HL / LH / LL, the latest green and red liquidity zone); EMA 9 and VWAP with a BUY / SELL signal; the trend bands' state, band and value edge with a break signal.
- **Trades box** (next to the info box, only while a hovered candle has any) — every position and backtest trade open during that candle: id, mode and direction (green long, red short), when it opened and closed, entry → close, SL, TP, realized / unrealized PnL with % of margin (a backtest trade: its return, % of price) — green for a win, red for a loss — and open → close reasons.
- **Every point sits on a candle** — a fill or a trade inside a candle is drawn at that candle's open time (at its real price).
- **Overlays on every chart** — whatever the paper's executor, the chart draws all of them: the [liquidity swings and HH / LL / LH / HL](swings.md), the VWAP + EMA 9 with its signals, and the trend bands. A Supertrend paper's chart adds [its Supertrend](supertrend-strategy-engine.md#chart).
- **Show / hide** — checkboxes under the chart turn each overlay on or off: Swings (HH / LL / LH / HL, their levels), Liquidity zones, VWAP + EMA 9, Trend bands, and Supertrend (on a Supertrend paper's chart). A hidden overlay's lines, markers and hover rows all go; trades and the backtest stay. The choice is kept in this browser (all shown by default).
- **Liquidity swings** — confirmed zones as transparent green (swing lows) / red (swing highs) rectangles, from the pivot candle across its count ([Liquidity Swings](swings.md#liquidity-swings)) — a port of the library's rectangle plugin example.
- **Swings** — every HH / LH as its letters above its candle and LL / HL below (green HH / HL, red LL / LH), computed exactly as the executor does; every swing's level (previous ones included) as a 2px-high rectangle at its price, from its pivot candle (where the high / low was made), 15 candles wide (to the last candle at most); they don't stretch the price scale. The current (last) level of each kind is also a dashed horizontal line across the chart with its label on the price axis — the levels the strategy trades now.
- **VWAP + EMA 9** — the [VWAP](vwap-strategy-engine.md#lines) (orange) and EMA 9 (blue) lines and the [BUY / SELL signals](vwap-strategy-engine.md#signals) as arrows (blue BUY under the candle, red SELL above it), computed exactly as the VWAP executor does. The VWAP strategy trades them; elsewhere they're for reference.
- **Trend bands** — the [BigBeluga bands](regime-strategy-engine.md#trend-bands), computed over the last 5000 candles exactly as the Regime executor does: the active band as a line (green lower band while bullish, red upper band while bearish; none before the first cross), its value zone's edge dotted, and `BRK` arrows for break-ups (green, under the candle) / break-downs (red, above it).
- **Positions** — a separate dashed line per position from entry to exit (or to the last close while open), green long, red short — trades never join each other; a circle at every fill's price labelled with the position id (blue = open, amber = close, partial closes included). An open position also gets its entry, SL and TP as horizontal lines. Position details are in the [positions](#positions-table) table.
- **Backtest** (temporary, VWAP and Regime papers) — the paper's backtest ([VWAP](vwap-strategy-engine.md#backtest), [Regime](regime-strategy-engine.md#backtest)) trades as separate dashed lines (entry → exit; green long, red short) with small violet circles at each entry and exit — an averaging position still open when the backtest ended stops at the test's last candle with a grey square "test end <result>" there instead of a close (its hover box, the summary and the backtest log say "at the test end", not a live unrealized position); totals above the chart — % of price, compounded at the paper's leverage with the max drawdown, the same at 1× / 3× / 5× / 10× side by side (the paper's leverage in bold), and per month.
- While the paper is being prepared, a loader with the step (backfilling / backtesting) replaces the chart.
- Refreshes with the page (15 s). Rendered in the browser only; the chart code is a separate bundle loaded with the card.

## Trading Log

Paginated, from the [Trading Decision Log](postgres.md#trading-decision-log).

Columns: Time, Asset, Candidate, Signal, Outcome, Size, Price, PnL, Reason. Filters: live / demo, asset. Pages: First, Newer, Older, Last.

A filled decision shows its order: Size in coins with the notional and fee under it, Price the fill price. An exit also shows its position's average entry under the price; the order that closed the position shows the position's whole realized PnL with % of the margin put in — a partial close shows "partial" (its own PnL isn't stored).

The Reason column is how the owner learns why the system entered, exited, rejected a trade, or chose a position size.

## System Health

In the header: the [watchdog](watchdog.md) checks and the kill switch. All
passing and the kill switch off - one pulsing green dot, "All systems OK" and
when it was checked; otherwise only the failing checks (red, with their
detail) and the kill switch, if active. When the latest health load failed:
the last known status, with a grey dot ("Health: last known").

## Assets

Modal with the [asset universe](market-data.md#asset-universe): each asset a tag with a trash can, and an input to add one — any symbol, as the provider names it (not checked: you know it's a real one). The trash can is off while a paper needs the asset; deleting asks first, and removes the asset with all its market data. The asset selects (New paper, the trading log's filter) list these.

## Settings

Modal with the exchange API and the integration keys, stored encrypted in the database (key: `SETTINGS_ENCRYPTION_KEY` in `.env`):

- [Exchange API](#exchange-api) (optional — without it only demo mode works)
- Telegram bot token / chat id (watchdog alerts)
- **App password** — current password, new one (8+ characters) twice. Every other session is logged out; this one stays signed in ([api: Authentication](api.md#authentication)).

### Exchange API

At most **one**, always on **mainnet** (live papers trade real money — testing is [demo mode](papers.md) on real prices, no testnet). **+ Add API** asks for the provider, then its keys:

| Provider | Keys |
|---|---|
| Hyperliquid | API wallet private key, account address |
| Lighter | API key private key, account index, API key index |

The provider places the [live orders](execution-engine.md#live-execution) **and supply all market data** — candles, trades, order book, funding, open interest, the scanner's coin list (see [market-data: Providers](market-data.md#providers)). Without an API, everything (demo only) uses **Hyperliquid** data.

- **Add** connects to the provider with the keys first (up to 30 s); keys it refuses aren't saved, and the error shows its reason.
- **Change** = delete, then add. Stored keys are shown masked.
- **Delete** is refused while anything depends on it: an **open live position**, live **auto-trading on**, or **any paper**. To switch provider: close the live positions, turn auto-trading off, disable and delete every paper, delete the API, add the new one, create the papers again.
- **Add** and **Delete** clear the live equity history (the [risk engine](risk-engine.md#responsibilities)'s drawdown peak and day start), so the drawdown limit starts fresh from the new account.
- **Add** is refused while papers exist if it would change the market-data source (e.g. Lighter after papers on the default Hyperliquid data) — a paper's history comes from one provider.
- Stored history (candles, features, backtests) stays when the API changes.
- The services (market-data, scanner, risk engine, execution engine, watchdog) restart on the new provider within ~15 s of a change.

---
[← Back to README](../README.md)
