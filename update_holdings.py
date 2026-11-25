#!/usr/bin/env python3
"""Apply fresh IBKR positions and price quotes to data/holdings.json.

This script does not call Interactive Brokers itself. A nightly run should
write the connector results to:

  data/ibkr_positions.json   raw get_account_positions response
  data/quotes.json           raw get_price_snapshot response

then run:

  python3 update_holdings.py && python3 make_page.py

Rules:
  * IBKR lots follow live positions (quantity and, except Franklin, avg cost).
  * Franklin (contract 340336776) always uses live IBKR units and a $10,000 cost.
  * Other-broker lots and cash are kept as stored in holdings.json.
  * Tickers IBKR can quote are repriced; if a quote is missing, the last price is kept
    and the ticker is listed in meta.unpriced.
  * Space X / SPCX lots, including those at another broker, are priced as SPCX.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
HOLDINGS_PATH = DATA / "holdings.json"
CONTRACTS_PATH = DATA / "contracts.json"
POSITIONS_PATH = DATA / "ibkr_positions.json"
QUOTES_PATH = DATA / "quotes.json"

FRANKLIN_CONTRACT_ID = 340336776
FRANKLIN_COST = 10000.0
FRANKLIN_TICKER = "FRANKLIN"
DUBAI = timezone(timedelta(hours=4))

# IBKR describes the fund as IBCID340336776 @FUNDSERV, not "FRANKLIN".
POSITION_TICKER_ALIASES = {
    "IBCID340336776": FRANKLIN_TICKER,
    "I340336776": FRANKLIN_TICKER,
}


def r2(x) -> float:
    return round(float(x) + 0.0, 2)


def r6(x) -> float:
    return round(float(x) + 0.0, 6)


def load_json(path: Path):
    return json.loads(path.read_text())


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n")


def now_dubai() -> datetime:
    return datetime.now(DUBAI).replace(microsecond=0)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def from_ts(ts) -> datetime | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=DUBAI).replace(microsecond=0)
    except (TypeError, ValueError, OSError):
        return None


def ticker_from_position(pos: dict, contracts: dict) -> str | None:
    cid = pos.get("contract_id")
    if cid == FRANKLIN_CONTRACT_ID:
        return FRANKLIN_TICKER
    for ticker, info in (contracts.get("tickers") or {}).items():
        if info.get("contract_id") == cid:
            return ticker
    raw = (pos.get("contract_description") or "").split("@")[0].strip()
    raw = POSITION_TICKER_ALIASES.get(raw, raw)
    if raw in (contracts.get("tickers") or {}):
        return raw
    aliases = contracts.get("aliases") or {}
    if raw in aliases:
        return aliases[raw]
    # Fall back to a clean ticker-looking description.
    if raw and raw.replace(".", "").isalnum() and len(raw) <= 10:
        return raw
    return None


def index_quotes(raw: dict) -> dict[int, dict]:
    """Map contract_id -> quote object. Keys look like '76792991@SMART'."""
    out: dict[int, dict] = {}
    if not isinstance(raw, dict):
        return out
    # A single-contract response is a flat object of field names, not keyed by id.
    # Nightly runs should always use the batch form (contract_id_exs).
    items = raw.items()
    for key, value in items:
        if not isinstance(value, dict):
            continue
        if "@" in str(key):
            cid_s = str(key).split("@", 1)[0]
            try:
                out[int(cid_s)] = value
            except ValueError:
                continue
        elif "contract_id" in value:
            try:
                out[int(value["contract_id"])] = value
            except (TypeError, ValueError):
                continue
    return out


def pick_price(quote: dict | None):
    if not quote:
        return None, None, None, None
    last = quote.get("last") or {}
    pl = quote.get("plprice") or {}
    prior = quote.get("prior-close") or quote.get("prior_close") or {}
    if last.get("price") is not None:
        is_close = bool(last.get("is_close"))
        source = "IBKR last (session close)" if is_close else "IBKR last"
        return float(last["price"]), source, is_close, from_ts(last.get("ts"))
    if pl.get("price") is not None:
        return float(pl["price"]), "IBKR mark (plprice)", None, None
    prior_px = prior.get("priorClose") if "priorClose" in prior else prior.get("prior_close")
    if prior_px is not None:
        return float(prior_px), "IBKR prior close", True, None
    return None, None, None, None


def mark_price(quote: dict | None):
    if not quote:
        return None
    pl = quote.get("plprice") or {}
    if pl.get("price") is not None:
        return float(pl["price"])
    return None


def apply_price(holding: dict, quote: dict | None, unpriced: list) -> None:
    ticker = holding.get("ticker")
    price, source, is_close, ts = pick_price(quote)
    if price is None:
        label = ticker or holding.get("id") or "unknown"
        if label not in unpriced:
            unpriced.append(label)
        return
    holding["price"] = price
    holding["price_source"] = source
    holding["price_is_close"] = is_close
    holding["price_ts"] = iso(ts)
    shares = float(holding.get("shares") or 0)
    holding["value"] = r2(shares * price)
    if holding.get("cost_total") is not None:
        holding["pnl"] = r2(holding["value"] - float(holding["cost_total"]))
    mark = mark_price(quote)
    notes = holding.get("notes") or ""
    # Drop a previous mark-gap sentence, then re-add if the gap is still large.
    parts = [p.strip() for p in notes.split(".") if p.strip() and not p.strip().startswith("Mark (plprice) was")]
    notes = ". ".join(parts)
    if notes and not notes.endswith("."):
        notes += "."
    if mark is not None and price and abs(price - mark) / price >= 0.015:
        gap = f" Mark (plprice) was ${mark:.2f} vs last ${price:.2f}."
        notes = (notes + gap).strip()
    holding["notes"] = notes


def recompute_lot_value(holding: dict) -> None:
    shares = float(holding.get("shares") or 0)
    price = holding.get("price")
    if price is None:
        holding["value"] = 0.0
        holding["pnl"] = None if holding.get("cost_total") is None else r2(0 - float(holding["cost_total"]))
        return
    holding["value"] = r2(shares * float(price))
    if holding.get("cost_total") is not None:
        holding["pnl"] = r2(holding["value"] - float(holding["cost_total"]))
    else:
        holding["pnl"] = None


def display_name_for(ticker: str, contracts: dict, fallback: str) -> str:
    if ticker == "SPCX":
        return "Space X (priced as SPCX)"
    if ticker == FRANKLIN_TICKER:
        return "Franklin U.S. Dollar Short-Term Money Market A (USD) Inc"
    info = (contracts.get("tickers") or {}).get(ticker) or {}
    return info.get("name") or fallback or ticker


def make_ibkr_lot(ticker: str, pos: dict, contracts: dict, quotes_by_id: dict, unpriced: list) -> dict:
    shares = float(pos.get("position") or 0)
    cid = pos.get("contract_id")
    info = (contracts.get("tickers") or {}).get(ticker) or {}
    exchange = info.get("exchange") or "SMART"
    if cid == FRANKLIN_CONTRACT_ID:
        exchange = "FUNDSERV"
        cost_total = FRANKLIN_COST
        avg_cost = cost_total / shares if shares else None
        notes = "True cost basis is $10,000 (not the cost IBKR displays). Units are the live IBKR position."
    else:
        avg_cost = pos.get("average_price")
        cost_total = r2(shares * float(avg_cost)) if avg_cost is not None else None
        notes = ""
        if ticker == "SPCX":
            notes = "ASSUMPTION: priced as SPCX. This is not SpaceX private stock."
    holding = {
        "id": f"{ticker}-IBKR",
        "ticker": ticker,
        "name": display_name_for(ticker, contracts, pos.get("contract_description") or ticker),
        "broker": "IBKR",
        "type": "holding",
        "shares": shares if shares % 1 else int(shares) if float(shares).is_integer() else shares,
        "avg_cost": r6(avg_cost) if avg_cost is not None else None,
        "cost_total": r2(cost_total) if cost_total is not None else None,
        "price": None,
        "value": 0.0,
        "pnl": None,
        "price_source": None,
        "price_is_close": None,
        "price_ts": None,
        "contract_id": cid or info.get("contract_id"),
        "exchange": exchange,
        "notes": notes,
    }
    # Prefer integer share counts when they are whole numbers, else keep raw.
    if isinstance(holding["shares"], float) and holding["shares"].is_integer():
        holding["shares"] = int(holding["shares"])
    quote = quotes_by_id.get(holding["contract_id"])
    # If the snapshot failed, fall back to the position's market_price so a new
    # IBKR lot is not added at a zero price.
    if pick_price(quote)[0] is None and pos.get("market_price") is not None:
        holding["price"] = float(pos["market_price"])
        holding["price_source"] = "IBKR position market_price"
        recompute_lot_value(holding)
        label = ticker
        if label not in unpriced:
            unpriced.append(label)
    else:
        apply_price(holding, quote, unpriced)
        if holding.get("price") is None and pos.get("market_price") is not None:
            holding["price"] = float(pos["market_price"])
            holding["price_source"] = "IBKR position market_price"
            recompute_lot_value(holding)
    return holding


def update(data: dict, positions_raw, quotes_raw, contracts: dict) -> dict:
    unpriced: list[str] = []
    quotes_by_id = index_quotes(quotes_raw if isinstance(quotes_raw, dict) else {})

    raw_positions = []
    if isinstance(positions_raw, dict):
        raw_positions = positions_raw.get("positions") or positions_raw.get("data") or []
    elif isinstance(positions_raw, list):
        raw_positions = positions_raw

    ibkr_by_ticker: dict[str, dict] = {}
    unknown = []
    for pos in raw_positions:
        ticker = ticker_from_position(pos, contracts)
        if not ticker:
            unknown.append(pos.get("contract_id") or pos.get("contract_description"))
            continue
        ibkr_by_ticker[ticker] = pos
        # Remember contract ids for next time.
        tickers = contracts.setdefault("tickers", {})
        if ticker not in tickers and pos.get("contract_id"):
            exchange = "FUNDSERV" if pos.get("contract_id") == FRANKLIN_CONTRACT_ID else "SMART"
            tickers[ticker] = {
                "contract_id": pos["contract_id"],
                "exchange": exchange,
                "name": display_name_for(ticker, contracts, pos.get("contract_description") or ticker),
            }

    existing = data.get("holdings") or []
    other_lots = [h for h in existing if h.get("broker") != "IBKR"]
    new_holdings = []

    # Refresh every live IBKR position, including ones not in the file yet.
    for ticker, pos in ibkr_by_ticker.items():
        new_holdings.append(make_ibkr_lot(ticker, pos, contracts, quotes_by_id, unpriced))

    # Keep other-broker lots and reprice them when a contract exists.
    for lot in other_lots:
        ticker = lot.get("ticker")
        info = (contracts.get("tickers") or {}).get(ticker) or {}
        cid = lot.get("contract_id") or info.get("contract_id")
        if cid:
            lot["contract_id"] = cid
            lot["exchange"] = lot.get("exchange") or info.get("exchange") or "SMART"
            apply_price(lot, quotes_by_id.get(cid), unpriced)
        else:
            # No contract to quote; keep last price, but still recompute value.
            recompute_lot_value(lot)
            if ticker and ticker not in unpriced:
                unpriced.append(ticker)
        new_holdings.append(lot)

    # If an IBKR lot vanished and there is no other-broker lot, it is simply gone.
    data["holdings"] = new_holdings

    stocks = r2(sum(float(h.get("value") or 0) for h in new_holdings))
    cash_total = r2(sum(float(c.get("value") or 0) for c in (data.get("cash") or [])))
    known = [h for h in new_holdings if h.get("pnl") is not None and h.get("cost_total") is not None]
    pnl = r2(sum(float(h["pnl"]) for h in known))
    cost = r2(sum(float(h["cost_total"]) for h in known))

    meta = data.setdefault("meta", {})
    meta["currency"] = "USD"
    meta["timezone"] = "Asia/Dubai"
    meta["timezone_label"] = "Abu Dhabi time"
    meta["updated_at"] = iso(now_dubai())
    meta["unpriced"] = unpriced
    meta["totals"] = {
        "stocks_funds": stocks,
        "cash": cash_total,
        "grand_total": r2(stocks + cash_total),
        "pnl_known_cost": pnl,
        "cost_known": cost,
    }
    if unknown:
        notes = meta.setdefault("notes", [])
        flag = "Unmapped IBKR positions (contract not matched to a ticker) were skipped: " + ", ".join(str(x) for x in unknown) + "."
        notes = [n for n in notes if not n.startswith("Unmapped IBKR positions")]
        notes.append(flag)
        meta["notes"] = notes
    return data


def main() -> None:
    if not HOLDINGS_PATH.exists():
        raise SystemExit(f"Missing {HOLDINGS_PATH}")
    if not POSITIONS_PATH.exists() or not QUOTES_PATH.exists():
        raise SystemExit(
            "Missing data/ibkr_positions.json or data/quotes.json. "
            "Save the connector responses first (see DAILY_UPDATE.md)."
        )
    data = load_json(HOLDINGS_PATH)
    contracts = load_json(CONTRACTS_PATH) if CONTRACTS_PATH.exists() else {"tickers": {}, "aliases": {}}
    positions = load_json(POSITIONS_PATH)
    quotes = load_json(QUOTES_PATH)
    data = update(data, positions, quotes, contracts)
    save_json(HOLDINGS_PATH, data)
    save_json(CONTRACTS_PATH, contracts)
    tot = data["meta"]["totals"]
    print(
        "Updated holdings.json: "
        f"grand {tot['grand_total']}, stocks/funds {tot['stocks_funds']}, "
        f"cash {tot['cash']}, unpriced {data['meta']['unpriced']}"
    )


if __name__ == "__main__":
    main()
