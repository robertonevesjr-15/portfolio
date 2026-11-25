# Daily portfolio page update

Run this every night at **02:00 Asia/Dubai** (Abu Dhabi time, UTC+4). A fresh agent with no prior context can follow it end to end.

The public site is a static GitHub Pages page. GitHub Actions cannot reach the Interactive Brokers connector, so this bot (or another Grok Bot run with the IBKR connector and `gh` logged in as `robertonevesjr-15`) must refresh the data, rebuild `index.html`, and push.

## Paths and URLs

- Working copy on the box: `/workspace/portfolio-site`
- GitHub repo: https://github.com/robertonevesjr-15/portfolio
- Live page: https://robertonevesjr-15.github.io/portfolio/
- Branch and Pages source: `main`, site root (`/`)
- GitHub account used to push: `robertonevesjr-15` (scopes must include `repo`)

If `/workspace/portfolio-site` is missing, clone the repo there:

```bash
git clone https://github.com/robertonevesjr-15/portfolio.git /workspace/portfolio-site
```

If the folder exists, pull first so you do not overwrite a newer commit:

```bash
cd /workspace/portfolio-site
git checkout main
git pull --ff-only origin main
```

Do not put this project in a folder named `build`, `dist`, `out`, `coverage`, or `target`.

## Tools

1. IBKR connector namespace: `user-Interactive Brokers (IBKR)-xai`.
   Confirm it is ready with `GetDynamicTools`. Read schemas before calling:
   - `get_account_positions` (no arguments)
   - `search_contracts` (`query`)
   - `get_price_snapshot` (`contract_id_exs` for a batch; optional `market_data_names`)
2. `gh` on the box, already able to push to `robertonevesjr-15/portfolio`.
3. Python 3, no third-party packages. Run scripts from `/workspace/portfolio-site`.

## What must stay true

- **Franklin money market fund** (IBKR contract `340336776`, exchange `FUNDSERV`, ticker `FRANKLIN` in our files): always use the **live IBKR unit count**. The cost basis is always **$10,000** total, not the average cost IBKR displays. P&L = market value − $10,000.
- **Space X**: the consolidated total is 9.27 shares (5 at IBKR, 4.27 at another broker). Price **every** Space X share as **SPCX** (contract `890493863` @ `SMART`). This is an assumption; it is not SpaceX private stock. Keep the note on the page.
- **Other-broker lots** (broker = `Other broker`) and **cash lines** come from the master list and live in `data/holdings.json`. Do not delete them. Do not change their quantities or cash amounts unless the owner has given a new figure. Reprice other-broker tickers when IBKR can quote them.
- **IBKR lots** (broker = `IBKR`) follow live `get_account_positions`. If a position disappears from IBKR, drop that IBKR lot (keep any other-broker lot of the same ticker). If a new IBKR position appears, add it.
- **P&L** is only computed where cost is known (IBKR lots, including Franklin at $10,000). Other-broker lots have no cost and no P&L.
- Cash is not a market price. Leave the four cash lines as stored: ADCB USD, IBKR HSBC, IBKR USA, Kraken.
- The page is **public** and has **no password**. Keep `<meta name="robots" content="noindex">`. Do not add the owner's full legal name to the page.

## Contract cache

`data/contracts.json` maps ticker → `{contract_id, exchange, name}`. Reuse these. Only call `search_contracts` for a ticker that is missing from the cache (or whose contract_id no longer works).

Important exchange rule: ordinary US stocks and ETFs use `SMART`. The Franklin fund must be requested as `340336776@FUNDSERV`. Never send the fund as `@SMART` — the snapshot will be empty.

Aliases already in the cache: `I340336776` and `IBCID340336776` → `FRANKLIN`.

## Step-by-step

### 1. Fetch live IBKR positions

Call `get_account_positions`. Save the raw JSON to `data/ibkr_positions.json`.

Use it to:

- Set each IBKR lot's `shares` (and, except Franklin, `avg_cost` / `cost_total`).
- Set Franklin `shares` from contract `340336776` and force `cost_total` to `10000`.
- Discover new IBKR tickers.

Do not use IBKR quantities to change other-broker lots. Example: if IBKR shows 5 TSLA and the file has 1.37 TSLA at "Other broker", leave the 1.37 as is.

### 2. Fetch today's prices

Build a batch of `contract_id_exs` from `data/contracts.json` (and any new IBKR positions). Request:

```text
market_data_names: ["last", "plprice", "prior_close"]
```

A batch allows at most 100 data points (contracts × fields). With 3 fields, request at most 33 contracts per call. Split larger lists. Do not immediately retry a whole batch if a few fields are null; wait and retry only the missing contracts.

Save the raw snapshot JSON to `data/quotes.json`.

Price choice (already implemented in `update_holdings.py`):

1. `last.price` if present (label it `IBKR last`, or `IBKR last (session close)` when `is_close` is true)
2. else `plprice.price` (`IBKR mark (plprice)`) — this is the usual fallback for the Franklin fund if `last` is missing
3. else `prior-close.priorClose` (`IBKR prior close`)
4. else keep the last stored price and add the ticker to `meta.unpriced`
5. for a brand-new IBKR lot with no snapshot, `market_price` from the position may be used so the lot is not stored at $0, but still list it in `unpriced`

Response keys use hyphens: `prior-close`, not `prior_close`.

### 3. Rebuild the data file and the page

```bash
cd /workspace/portfolio-site
python3 update_holdings.py
python3 make_page.py
```

`update_holdings.py` writes `data/holdings.json` (and refreshes `data/contracts.json` if it learned new ids). `make_page.py` writes `index.html`.

If you cannot use the helper scripts, edit `data/holdings.json` by hand with the same rules and then run `python3 make_page.py`. Never edit `index.html` by hand; it is generated.

`data/ibkr_positions.json` and `data/quotes.json` are gitignored raw dumps. Do not commit them.

### 4. Commit and push

```bash
cd /workspace/portfolio-site
git status
git add index.html data/holdings.json data/contracts.json
# Only add scripts or docs if you actually changed them.
git commit -m "Refresh portfolio prices for YYYY-MM-DD (Abu Dhabi time)"
git push origin main
```

Use a local git identity if the repo has none, for example:

```bash
git config user.name "robertonevesjr-15"
git config user.email "robertonevesjr-15@users.noreply.github.com"
```

Do not force-push. If `git pull --ff-only` fails, stop and report the conflict; do not rewrite history.

### 5. Verify

Wait for GitHub Pages to rebuild (often 30–90 seconds, sometimes a few minutes). Then:

```bash
curl -sS -o /tmp/portfolio.html -w "%{http_code}" https://robertonevesjr-15.github.io/portfolio/
```

- The HTTP status must be `200`.
- The HTML must contain today's `Last updated` stamp in Abu Dhabi time and the new totals from `data/holdings.json` (`meta.totals.grand_total`, `stocks_funds`, `cash`).
- If `meta.unpriced` is not empty, say so in the run report and leave the previous prices in place.

A CDN or Pages cache can lag briefly. If the status is 200 but totals look old, wait once and fetch again with a cache-buster:

```bash
curl -sS -o /tmp/portfolio.html -w "%{http_code}" "https://robertonevesjr-15.github.io/portfolio/?t=$(date +%s)"
```

## Failure handling

- IBKR connector not ready or positions call fails: do not push a zeroed portfolio. Report the error and stop.
- Some quotes fail: keep last prices, list those tickers in `meta.unpriced`, still push if positions were applied and the page builds.
- `gh` or git push fails: leave the local files updated and report the error. Do not try to host the page somewhere else in the same run.
- A new IBKR ticker has no contract cache entry: call `search_contracts`, prefer the US primary listing, store it in `data/contracts.json`, then quote it.
- Cash should only change when the owner provides a new balance.

## After the push

Report: the live Pages URL, the commit, grand total, stocks/funds total, cash, P&L on known cost, any unpriced tickers, and any new or vanished IBKR positions.
