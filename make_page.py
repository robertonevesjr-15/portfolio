#!/usr/bin/env python3
"""Generate a mobile-friendly dark-theme index.html from data/holdings.json."""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "holdings.json"
OUT_PATH = ROOT / "index.html"

BROKER_COLORS = {
    "IBKR": "#f0a030",
    "Other broker": "#7aa2ff",
    "ADCB": "#5fd38d",
    "IBKR HSBC": "#c792ea",
    "IBKR USA": "#e07a9a",
    "Kraken": "#5bc0be",
}

HOLDING_PALETTE = [
    "#f0a030",
    "#7aa2ff",
    "#5fd38d",
    "#e07a9a",
    "#c792ea",
    "#5bc0be",
    "#f6c177",
    "#89b4fa",
    "#a6e3a1",
    "#fab387",
    "#94e2d5",
    "#f38ba8",
    "#b4befe",
    "#cba6f7",
    "#89dceb",
]


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def money(value, signed=False) -> str:
    if value is None:
        return "—"
    n = float(value)
    sign = "+" if signed and n > 0 else ("−" if signed and n < 0 else "")
    # Use Unicode minus for negatives so the table stays visually even.
    if not signed and n < 0:
        sign = "−"
        n = abs(n)
    elif signed:
        n = abs(n)
    return f"{sign}${n:,.2f}"


def shares_fmt(value) -> str:
    if value is None:
        return "—"
    n = float(value)
    if abs(n - round(n)) < 1e-9:
        return f"{int(round(n))}"
    text = f"{n:.6f}".rstrip("0").rstrip(".")
    return text


def pct_fmt(value) -> str:
    if value is None:
        return "—"
    return f"{float(value):.1f}%"


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def format_updated(meta: dict) -> str:
    raw = meta.get("updated_at") or ""
    dt = parse_dt(raw)
    label = meta.get("timezone_label") or "Abu Dhabi time"
    if not dt:
        return raw or "Unknown"
    # 25 Nov 2026, 1:31 PM (Abu Dhabi time)
    hour = dt.strftime("%I:%M %p").lstrip("0")
    return f"{dt.strftime('%-d %b %Y')}, {hour} ({label})"


def broker_group(broker: str) -> str:
    if broker in {"IBKR", "IBKR HSBC", "IBKR USA"}:
        return "IBKR"
    return broker


def load() -> dict:
    return json.loads(DATA_PATH.read_text())


def totals(data: dict) -> dict:
    meta_tot = (data.get("meta") or {}).get("totals") or {}
    holdings = data.get("holdings") or []
    cash = data.get("cash") or []
    stocks = round(sum(float(h.get("value") or 0) for h in holdings), 2)
    cash_total = round(sum(float(c.get("value") or 0) for c in cash), 2)
    grand = round(stocks + cash_total, 2)
    known = [h for h in holdings if h.get("pnl") is not None and h.get("cost_total") is not None]
    pnl = round(sum(float(h["pnl"]) for h in known), 2)
    cost = round(sum(float(h["cost_total"]) for h in known), 2)
    return {
        "stocks_funds": meta_tot.get("stocks_funds", stocks) if False else stocks,
        "cash": cash_total,
        "grand_total": grand,
        "pnl_known_cost": pnl,
        "cost_known": cost,
    }


def allocation_by_broker(data: dict, grand: float) -> list[dict]:
    buckets: dict[str, float] = {}
    for h in data.get("holdings") or []:
        key = broker_group(h.get("broker") or "Unknown")
        buckets[key] = buckets.get(key, 0) + float(h.get("value") or 0)
    for c in data.get("cash") or []:
        key = broker_group(c.get("broker") or c.get("name") or "Cash")
        buckets[key] = buckets.get(key, 0) + float(c.get("value") or 0)
    rows = []
    for name, value in sorted(buckets.items(), key=lambda kv: -kv[1]):
        rows.append(
            {
                "name": name,
                "value": round(value, 2),
                "weight": (value / grand * 100) if grand else 0,
                "color": BROKER_COLORS.get(name, "#888"),
            }
        )
    return rows


def allocation_by_holding(data: dict, grand: float) -> list[dict]:
    # Combine lots of the same ticker so Space X / Tesla appear once.
    buckets: dict[str, dict] = {}
    for h in data.get("holdings") or []:
        ticker = h.get("ticker") or h.get("name")
        item = buckets.setdefault(
            ticker,
            {"name": h.get("name") or ticker, "ticker": ticker, "value": 0.0},
        )
        item["value"] += float(h.get("value") or 0)
        # Prefer the longer display name.
        if h.get("name") and len(h["name"]) > len(item["name"] or ""):
            item["name"] = h["name"]
    for c in data.get("cash") or []:
        key = f"CASH:{c.get('id') or c.get('name')}"
        buckets[key] = {
            "name": f"{c.get('name')} (cash)",
            "ticker": c.get("name"),
            "value": float(c.get("value") or 0),
        }
    rows = []
    for i, item in enumerate(sorted(buckets.values(), key=lambda x: -x["value"])):
        value = round(item["value"], 2)
        rows.append(
            {
                "name": item["name"],
                "ticker": item["ticker"],
                "value": value,
                "weight": (item["value"] / grand * 100) if grand else 0,
                "color": HOLDING_PALETTE[i % len(HOLDING_PALETTE)],
            }
        )
    return rows


def stacked_bar(rows: list[dict], height: int = 16) -> str:
    if not rows:
        return ""
    parts = []
    offset = 0.0
    for row in rows:
        w = max(row["weight"], 0)
        if w <= 0:
            continue
        parts.append(
            f'<rect x="{offset:.3f}" y="0" width="{w:.3f}" height="{height}" fill="{esc(row["color"])}"></rect>'
        )
        offset += w
    return (
        f'<svg class="bar" viewBox="0 0 100 {height}" preserveAspectRatio="none" '
        f'role="img" aria-label="Allocation bar">{"".join(parts)}</svg>'
    )


def legend(rows: list[dict]) -> str:
    items = []
    for row in rows:
        items.append(
            "<li>"
            f'<span class="swatch" style="background:{esc(row["color"])}"></span>'
            f'<span class="leg-name">{esc(row["name"])}</span>'
            f'<span class="leg-val">{money(row["value"])}</span>'
            f'<span class="leg-pct">{pct_fmt(row["weight"])}</span>'
            "</li>"
        )
    return "<ul class='legend'>" + "".join(items) + "</ul>"


def holding_rows_html(holdings: list[dict], grand: float) -> str:
    rows = []
    for h in holdings:
        value = float(h.get("value") or 0)
        weight = (value / grand * 100) if grand else 0
        pnl = h.get("pnl")
        pnl_class = "flat" if pnl is None else ("up" if float(pnl) > 0 else ("down" if float(pnl) < 0 else "flat"))
        notes = h.get("notes") or ""
        price_ts = h.get("price_ts") or ""
        title_bits = [h.get("price_source") or ""]
        if price_ts:
            dt = parse_dt(price_ts)
            title_bits.append(format_updated({"updated_at": price_ts, "timezone_label": "Abu Dhabi time"}) if dt else price_ts)
        if notes:
            title_bits.append(notes)
        title = esc(" · ".join(b for b in title_bits if b))
        ticker_label = "FRANKLIN" if h.get("ticker") == "FRANKLIN" else (h.get("ticker") or "")
        rows.append(
            "<tr "
            f"data-name=\"{esc((h.get('name') or '').lower())}\" "
            f"data-ticker=\"{esc((h.get('ticker') or '').lower())}\" "
            f"data-shares=\"{float(h.get('shares') or 0)}\" "
            f"data-price=\"{float(h.get('price') or 0)}\" "
            f"data-value=\"{value}\" "
            f"data-weight=\"{weight}\" "
            f"data-pnl=\"{'' if pnl is None else float(pnl)}\" "
            f"data-broker=\"{esc(h.get('broker') or '')}\">"
            "<td class='col-name'>"
            f"<div class='nm'>{esc(h.get('name'))}</div>"
            f"<div class='sub'><span class='tk'>{esc(ticker_label)}</span>"
            f"<span class='badge'>{esc(h.get('broker'))}</span></div>"
            "</td>"
            f"<td class='num' data-label='Shares'>{esc(shares_fmt(h.get('shares')))}</td>"
            f"<td class='num' data-label='Price' title='{title}'>{money(h.get('price'))}</td>"
            f"<td class='num' data-label='Value'>{money(value)}</td>"
            f"<td class='num' data-label='Weight'>{pct_fmt(weight)}</td>"
            f"<td class='num {pnl_class}' data-label='P&amp;L'>{money(pnl, signed=True)}</td>"
            "</tr>"
        )
    return "".join(rows)


def cash_rows_html(cash: list[dict], grand: float) -> str:
    rows = []
    for c in cash:
        value = float(c.get("value") or 0)
        weight = (value / grand * 100) if grand else 0
        rows.append(
            "<tr>"
            f"<td class='col-name'><div class='nm'>{esc(c.get('name'))}</div>"
            f"<div class='sub'><span class='badge'>{esc(c.get('broker') or c.get('name'))}</span></div></td>"
            f"<td class='num' data-label='Amount'>{money(value)}</td>"
            f"<td class='num' data-label='Weight'>{pct_fmt(weight)}</td>"
            "</tr>"
        )
    return "".join(rows)


def notes_html(meta: dict) -> str:
    items = []
    for note in meta.get("notes") or []:
        items.append(f"<li>{esc(note)}</li>")
    unpriced = meta.get("unpriced") or []
    if unpriced:
        names = ", ".join(str(x) for x in unpriced)
        items.append(
            f"<li>Could not refresh a live price for: {esc(names)}. The last stored price was kept.</li>"
        )
    return "<ul class='notes'>" + "".join(items) + "</ul>"


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#111114">
<meta name="format-detection" content="telephone=no">
<title>Portfolio</title>
<style>
:root {{
  --bg: #111114;
  --card: #232327;
  --card-2: #1c1c1f;
  --line: #333338;
  --text: #f2f2f2;
  --muted: #999;
  --soft: #bbb;
  --accent: #f0a030;
  --up: #5fd38d;
  --down: #ff7a7a;
  --pad: max(16px, env(safe-area-inset-left));
  --padr: max(16px, env(safe-area-inset-right));
}}
* {{ box-sizing: border-box; }}
html {{ -webkit-text-size-adjust: 100%; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  padding: max(20px, env(safe-area-inset-top)) var(--padr) max(32px, env(safe-area-inset-bottom)) var(--pad);
}}
.wrap {{ max-width: 760px; margin: 0 auto; }}
.kicker {{
  color: var(--accent);
  letter-spacing: 2px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
}}
h1 {{ margin: 6px 0 4px; font-size: 28px; font-weight: 700; letter-spacing: -0.03em; }}
.updated {{ color: var(--muted); font-size: 14px; margin-bottom: 20px; line-height: 1.4; }}
.hero {{
  background: linear-gradient(180deg, #2a2418 0%, #232327 100%);
  border: 1px solid #3a3224;
  border-radius: 18px;
  padding: 20px 20px 18px;
  margin-bottom: 14px;
}}
.hero .label {{
  font-size: 12px;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: var(--accent);
  font-weight: 600;
}}
.hero .big {{
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-size: 36px;
  font-weight: 700;
  margin: 8px 0 0;
  letter-spacing: -0.04em;
  font-variant-numeric: tabular-nums;
}}
.grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 20px;
}}
.metric {{
  background: var(--card-2);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 14px 16px;
}}
.metric .label {{
  font-size: 11px;
  letter-spacing: 1.3px;
  text-transform: uppercase;
  color: var(--muted);
  font-weight: 600;
}}
.metric .val {{
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-size: 20px;
  font-weight: 700;
  margin-top: 6px;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.03em;
}}
.metric .hint {{ color: var(--muted); font-size: 12px; margin-top: 4px; }}
.up {{ color: var(--up); }}
.down {{ color: var(--down); }}
.flat {{ color: var(--soft); }}
.card {{
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 18px 18px 8px;
  margin-bottom: 16px;
}}
.ct {{
  color: var(--accent);
  letter-spacing: 1.5px;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 12px;
}}
.bar {{
  width: 100%;
  height: 16px;
  display: block;
  border-radius: 99px;
  overflow: hidden;
  background: #1a1a1d;
}}
.legend {{
  list-style: none;
  padding: 12px 0 8px;
  margin: 0;
}}
.legend li {{
  display: grid;
  grid-template-columns: 12px 1fr auto auto;
  gap: 8px 10px;
  align-items: center;
  padding: 7px 0;
  border-bottom: 1px solid #2c2c30;
  font-size: 14px;
}}
.legend li:last-child {{ border-bottom: 0; }}
.swatch {{ width: 12px; height: 12px; border-radius: 3px; display: inline-block; }}
.leg-name {{ color: var(--soft); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.leg-val, .leg-pct {{
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-variant-numeric: tabular-nums;
  font-size: 13px;
}}
.leg-pct {{ color: var(--muted); min-width: 3.4em; text-align: right; }}
.toolbar {{
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 4px;
}}
.hint {{ color: var(--muted); font-size: 12px; }}
table {{
  width: 100%;
  border-collapse: collapse;
  font-variant-numeric: tabular-nums;
}}
th {{
  text-align: right;
  font-size: 11px;
  letter-spacing: 1px;
  text-transform: uppercase;
  color: var(--muted);
  font-weight: 600;
  padding: 10px 0 10px 10px;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
  cursor: pointer;
  user-select: none;
  -webkit-user-select: none;
}}
th.col-name, td.col-name {{ text-align: left; padding-left: 0; }}
th.sort-asc::after {{ content: " \\25b2"; color: var(--accent); font-size: 9px; }}
th.sort-desc::after {{ content: " \\25bc"; color: var(--accent); font-size: 9px; }}
td {{
  padding: 12px 0 12px 10px;
  border-bottom: 1px solid #2c2c30;
  text-align: right;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-size: 13px;
  vertical-align: top;
}}
td.col-name {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; text-align: left; }}
.nm {{ font-size: 14px; font-weight: 600; line-height: 1.25; color: var(--text); }}
.sub {{ margin-top: 4px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
.tk {{
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-size: 11px;
  color: var(--muted);
  letter-spacing: 0.4px;
}}
.badge {{
  font-size: 10px;
  letter-spacing: 0.6px;
  text-transform: uppercase;
  border: 1px solid #3a3a40;
  color: var(--soft);
  border-radius: 999px;
  padding: 2px 7px;
  font-weight: 600;
}}
.notes {{
  color: #888;
  font-size: 13px;
  line-height: 1.55;
  padding-left: 18px;
  margin: 0 0 8px;
}}
.notes li {{ margin: 0 0 8px; }}
footer {{ color: #666; font-size: 12px; line-height: 1.5; margin-top: 8px; }}
@media (max-width: 560px) {{
  .hero .big {{ font-size: 30px; }}
  .metric .val {{ font-size: 18px; }}
  /* Keep the name visible; allow the numeric columns to scroll together. */
  .table-scroll {{
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    margin: 0 -6px;
    padding: 0 6px;
  }}
  table {{ min-width: 560px; }}
  th, td {{ font-size: 12px; }}
  .nm {{ font-size: 13px; }}
}}
</style>
</head>
<body>
<div class="wrap">
  <div class="kicker">Holdings</div>
  <h1>Portfolio</h1>
  <div class="updated">Last updated {updated}<br>Refreshed daily at 2:00 AM (Abu Dhabi time)</div>

  <div class="hero">
    <div class="label">Grand total</div>
    <div class="big">{grand}</div>
  </div>
  <div class="grid">
    <div class="metric">
      <div class="label">Stocks &amp; funds</div>
      <div class="val">{stocks}</div>
    </div>
    <div class="metric">
      <div class="label">Cash</div>
      <div class="val">{cash}</div>
    </div>
    <div class="metric">
      <div class="label">P&amp;L (known cost)</div>
      <div class="val {pnl_class}">{pnl}</div>
      <div class="hint">On {cost} of cost basis</div>
    </div>
    <div class="metric">
      <div class="label">Known-cost return</div>
      <div class="val {pnl_class}">{pnl_pct}</div>
      <div class="hint">Other-broker lots have no cost</div>
    </div>
  </div>

  <div class="card">
    <div class="ct">Allocation by broker</div>
    {broker_bar}
    {broker_legend}
  </div>

  <div class="card">
    <div class="ct">Allocation by holding</div>
    {holding_bar}
    {holding_legend}
  </div>

  <div class="card">
    <div class="toolbar">
      <div class="ct" style="margin:0">Holdings</div>
      <div class="hint">Tap a column to sort</div>
    </div>
    <div class="table-scroll">
      <table id="holdings">
        <thead>
          <tr>
            <th class="col-name" data-sort="name">Name</th>
            <th data-sort="shares">Shares</th>
            <th data-sort="price">Price</th>
            <th data-sort="value" class="sort-desc">Value</th>
            <th data-sort="weight">Weight</th>
            <th data-sort="pnl">P&amp;L</th>
          </tr>
        </thead>
        <tbody>
          {holding_rows}
        </tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <div class="ct">Cash at brokers</div>
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th class="col-name">Account</th>
            <th>Amount</th>
            <th>Weight</th>
          </tr>
        </thead>
        <tbody>
          {cash_rows}
        </tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <div class="ct">Notes</div>
    {notes}
  </div>
  <footer>Figures are in US dollars. Prices come from Interactive Brokers snapshots (last trade when available, otherwise the mark). This page is a personal snapshot and is not advice.</footer>
</div>
<script>
(function () {{
  const table = document.getElementById("holdings");
  if (!table) return;
  const tbody = table.tBodies[0];
  const heads = table.tHead.rows[0].cells;
  let current = "value";
  let dir = "desc";

  function val(row, key) {{
    if (key === "name") return row.getAttribute("data-name") || "";
    const raw = row.getAttribute("data-" + key);
    if (raw === "" || raw === null) return key === "pnl" ? -Infinity : 0;
    const n = Number(raw);
    return Number.isNaN(n) ? raw : n;
  }}

  function sortBy(key, nextDir) {{
    current = key;
    dir = nextDir;
    const rows = Array.from(tbody.rows);
    rows.sort(function (a, b) {{
      const av = val(a, key);
      const bv = val(b, key);
      if (typeof av === "string" || typeof bv === "string") {{
        const cmp = String(av).localeCompare(String(bv));
        return dir === "asc" ? cmp : -cmp;
      }}
      if (av === bv) return val(b, "value") - val(a, "value");
      return dir === "asc" ? av - bv : bv - av;
    }});
    rows.forEach(function (row) {{ tbody.appendChild(row); }});
    Array.from(heads).forEach(function (th) {{
      th.classList.remove("sort-asc", "sort-desc");
      if (th.getAttribute("data-sort") === key) th.classList.add("sort-" + dir);
    }});
  }}

  Array.from(heads).forEach(function (th) {{
    th.addEventListener("click", function () {{
      const key = th.getAttribute("data-sort");
      if (!key) return;
      const next = (current === key && dir === "desc") ? "asc" : "desc";
      sortBy(key, next);
    }});
  }});

  sortBy("value", "desc");
}})();
</script>
</body>
</html>
"""


def render() -> str:
    data = load()
    meta = data.get("meta") or {}
    tot = totals(data)
    grand = tot["grand_total"] or 0
    pnl = tot["pnl_known_cost"]
    pnl_class = "up" if pnl > 0 else ("down" if pnl < 0 else "flat")
    pnl_pct = (pnl / tot["cost_known"] * 100) if tot["cost_known"] else 0
    brokers = allocation_by_broker(data, grand)
    by_holding = allocation_by_holding(data, grand)
    # Show the full holding legend; it is the actual portfolio.
    return PAGE.format(
        updated=esc(format_updated(meta)),
        grand=esc(money(tot["grand_total"])),
        stocks=esc(money(tot["stocks_funds"])),
        cash=esc(money(tot["cash"])),
        pnl=esc(money(pnl, signed=True)),
        pnl_class=pnl_class,
        cost=esc(money(tot["cost_known"])),
        pnl_pct=esc(("+" if pnl_pct > 0 else "−" if pnl_pct < 0 else "") + f"{abs(pnl_pct):.1f}%"),
        broker_bar=stacked_bar(brokers),
        broker_legend=legend(brokers),
        holding_bar=stacked_bar(by_holding),
        holding_legend=legend(by_holding),
        holding_rows=holding_rows_html(data.get("holdings") or [], grand),
        cash_rows=cash_rows_html(data.get("cash") or [], grand),
        notes=notes_html(meta),
    )


def main() -> None:
    if not DATA_PATH.exists():
        raise SystemExit(f"Missing {DATA_PATH}")
    html_out = render()
    OUT_PATH.write_text(html_out)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
