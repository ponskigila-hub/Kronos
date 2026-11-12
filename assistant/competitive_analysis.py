"""
Competitive analysis: target ticker vs 3–5 closest peers on the same metrics
and periods. Research synthesis only — not a recommendation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
import math


def _n(v) -> Optional[float]:
    try:
        if v is None:
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _pct_display(v: Optional[float], already_ratio: bool = True) -> str:
    if v is None:
        return "—"
    x = float(v) * 100 if already_ratio else float(v)
    return f"{x:+.1f}%" if already_ratio or abs(x) < 50 else f"{x:.1f}%"


def _fmt_money(n: Optional[float]) -> str:
    if n is None:
        return "—"
    n = float(n)
    sign = "-" if n < 0 else ""
    n = abs(n)
    for u, d in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if n >= d:
            return f"{sign}{n/d:.2f}{u}"
    return f"{sign}{n:.0f}"


def _fmt_num(n: Optional[float], d: int = 1) -> str:
    if n is None:
        return "—"
    return f"{float(n):.{d}f}"


def _load_profile(symbol: str) -> dict:
    import yfinance as yf
    raw = yf.Ticker(symbol).info or {}
    price = _n(raw.get("currentPrice")) or _n(raw.get("regularMarketPrice"))
    return {
        "ticker": symbol,
        "name": raw.get("longName") or raw.get("shortName") or symbol,
        "price": price,
        "currency": raw.get("currency") or "USD",
        "sector": raw.get("sector"),
        "industry": raw.get("industry"),
        "market_cap": _n(raw.get("marketCap")),
        "trailing_pe": _n(raw.get("trailingPE")),
        "forward_pe": _n(raw.get("forwardPE")),
        "peg": _n(raw.get("pegRatio")),
        "price_to_sales": _n(raw.get("priceToSalesTrailing12Months")),
        "price_to_book": _n(raw.get("priceToBook")),
        "ev_to_ebitda": _n(raw.get("enterpriseToEbitda")),
        "revenue_growth": _n(raw.get("revenueGrowth")),
        "earnings_growth": _n(raw.get("earningsGrowth")),
        "gross_margin": _n(raw.get("grossMargins")),
        "operating_margin": _n(raw.get("operatingMargins")),
        "profit_margin": _n(raw.get("profitMargins")),
        "roe": _n(raw.get("returnOnEquity")),
        "roa": _n(raw.get("returnOnAssets")),
        "debt_to_equity": _n(raw.get("debtToEquity")),
        "current_ratio": _n(raw.get("currentRatio")),
        "free_cashflow": _n(raw.get("freeCashflow")),
        "beta": _n(raw.get("beta")),
        "employees": _n(raw.get("fullTimeEmployees")),
        "description": (raw.get("longBusinessSummary") or "")[:500] or None,
    }


def _market_share_proxy(rows: list[dict]) -> dict[str, Optional[float]]:
    """Share of sum of available market caps among the set (not true industry share)."""
    caps = {r["ticker"]: r.get("market_cap") for r in rows if r.get("market_cap")}
    total = sum(caps.values()) if caps else 0
    out = {}
    for r in rows:
        t = r["ticker"]
        if total and caps.get(t):
            out[t] = caps[t] / total * 100.0
        else:
            out[t] = None
    return out


def _rank_note(target: str, rows: list[dict], key: str, higher_better: bool = True) -> str:
    scored = [(r["ticker"], r.get(key)) for r in rows if r.get(key) is not None]
    if len(scored) < 2:
        return ""
    scored.sort(key=lambda x: x[1], reverse=higher_better)
    rank = next((i + 1 for i, (t, _) in enumerate(scored) if t == target), None)
    if rank is None:
        return ""
    return f"ranks {rank}/{len(scored)} on {key.replace('_', ' ')}"


def analyze_competitors(ticker: str, peer_tickers: list[str]) -> dict[str, Any]:
    ticker = (ticker or "").strip().upper()
    peers = []
    for p in peer_tickers or []:
        s = str(p).strip().upper()
        if s and s != ticker and s not in peers:
            peers.append(s)
    if not ticker:
        raise ValueError("Enter a target ticker.")
    if not (3 <= len(peers) <= 5):
        raise ValueError("Enter 3 to 5 competitor tickers (same metrics for every name).")

    from .ticker_utils import validate_ticker
    ok, symbol = validate_ticker(ticker)
    if not ok:
        raise ValueError(f"'{ticker}' is not a valid ticker.")

    target = _load_profile(symbol)
    peer_rows = []
    errors = []
    for p in peers:
        try:
            ok_p, sp = validate_ticker(p)
            if not ok_p:
                errors.append(f"{p}: invalid")
                continue
            peer_rows.append(_load_profile(sp))
        except Exception as e:
            errors.append(f"{p}: {e}")

    if len(peer_rows) < 3:
        raise ValueError(
            "Need at least 3 competitors with usable data. "
            + ("; ".join(errors) if errors else "Try different tickers.")
        )

    all_rows = [target] + peer_rows
    share = _market_share_proxy(all_rows)
    for r in all_rows:
        r["peer_set_cap_share_pct"] = share.get(r["ticker"])

    # Comparison table (same metrics, same period = provider TTM / latest)
    metrics = [
        ("market_cap", "Market cap", False, False),
        ("revenue_growth", "Revenue growth (YoY)", True, True),
        ("earnings_growth", "Earnings growth (YoY)", True, True),
        ("gross_margin", "Gross margin", True, True),
        ("operating_margin", "Operating margin", True, True),
        ("profit_margin", "Profit margin", True, True),
        ("roe", "ROE", True, True),
        ("trailing_pe", "P/E (TTM)", False, False),
        ("forward_pe", "Forward P/E", False, False),
        ("price_to_sales", "P/S", False, False),
        ("ev_to_ebitda", "EV/EBITDA", False, False),
        ("debt_to_equity", "Debt / equity", False, False),
        ("peer_set_cap_share_pct", "Share of set mkt cap", True, False),
    ]

    table = []
    for key, label, is_ratio, higher_better in metrics:
        row = {"key": key, "label": label, "values": {}}
        for r in all_rows:
            v = r.get(key)
            if key in ("revenue_growth", "earnings_growth", "gross_margin", "operating_margin", "profit_margin", "roe"):
                row["values"][r["ticker"]] = None if v is None else round(float(v) * 100, 2)
            elif key == "peer_set_cap_share_pct":
                row["values"][r["ticker"]] = None if v is None else round(float(v), 2)
            else:
                row["values"][r["ticker"]] = None if v is None else round(float(v), 2)
        table.append(row)

    # Edges & threats (rule-based, transparent)
    edges = []
    threats = []
    t = target

    def avg_peers(key):
        vals = [p.get(key) for p in peer_rows if p.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    for key, label, higher_better in [
        ("revenue_growth", "revenue growth", True),
        ("operating_margin", "operating margin", True),
        ("profit_margin", "profit margin", True),
        ("roe", "ROE", True),
    ]:
        tv, pv = t.get(key), avg_peers(key)
        if tv is not None and pv is not None:
            if higher_better and tv > pv * 1.05:
                edges.append(f"Stronger {label} than the peer average ({_pct_display(tv)} vs {_pct_display(pv)}).")
            elif higher_better and tv < pv * 0.9:
                threats.append(f"Weaker {label} vs peers ({_pct_display(tv)} vs avg {_pct_display(pv)}).")

    for key, label in [("trailing_pe", "P/E"), ("forward_pe", "forward P/E"), ("price_to_sales", "P/S")]:
        tv, pv = t.get(key), avg_peers(key)
        if tv is not None and pv is not None and pv > 0:
            if tv < pv * 0.85:
                edges.append(f"Cheaper on {label} than peer average ({_fmt_num(tv)}× vs {_fmt_num(pv)}×).")
            elif tv > pv * 1.2:
                threats.append(f"Richer valuation on {label} ({_fmt_num(tv)}× vs peer avg {_fmt_num(pv)}×) — needs growth to justify.")

    td, pd_ = t.get("debt_to_equity"), avg_peers("debt_to_equity")
    if td is not None and pd_ is not None:
        if td < pd_ * 0.85:
            edges.append(f"Lower leverage (D/E {_fmt_num(td, 0)} vs peer avg {_fmt_num(pd_, 0)}).")
        elif td > pd_ * 1.25:
            threats.append(f"Higher leverage than peers (D/E {_fmt_num(td, 0)} vs avg {_fmt_num(pd_, 0)}).")

    # Industry mismatch warning
    industries = {r.get("industry") for r in all_rows if r.get("industry")}
    sectors = {r.get("sector") for r in all_rows if r.get("sector")}
    warnings = list(errors)
    if len(industries) > 2:
        warnings.append(
            "Peers span multiple industries — treat multiples carefully; business-model differences may dominate."
        )

    if not edges:
        edges.append("No clear quantitative edge on growth/margins/valuation vs this peer set — judgment is qualitative.")
    if not threats:
        threats.append("No automatic threat flags vs this set; still monitor share shifts, pricing power, and regulation.")

    # Narrative
    tickers_order = [r["ticker"] for r in all_rows]
    lines = [
        f"## Competitive analysis — {t['name']} ({symbol})",
        "",
        f"Peers (same metrics / provider periods): **{', '.join(p['ticker'] for p in peer_rows)}**",
        f"Sector / industry (target): **{t.get('sector') or '—'}** / **{t.get('industry') or '—'}**",
        "",
        "### Where it may have an edge",
    ]
    for e in edges:
        lines.append(f"- {e}")
    lines.append("")
    lines.append("### Where competitors may have the advantage")
    for th in threats:
        lines.append(f"- {th}")
    lines.append("")
    lines.append("### Snapshot (same fields for every company)")
    lines.append("")
    # compact markdown table header
    header = "| Metric | " + " | ".join(tickers_order) + " |"
    sep = "|---|—" + "|—".join(["—" for _ in tickers_order]) + "|"
    lines.append(header)
    lines.append("|---|" + "|".join(["---:" for _ in tickers_order]) + "|")
    for m in table:
        cells = []
        for tk in tickers_order:
            v = m["values"].get(tk)
            if v is None:
                cells.append("—")
            elif m["key"] in (
                "revenue_growth", "earnings_growth", "gross_margin", "operating_margin",
                "profit_margin", "roe", "peer_set_cap_share_pct",
            ):
                cells.append(f"{v:+.1f}%" if m["key"].endswith("growth") else f"{v:.1f}%")
            elif m["key"] == "market_cap":
                cells.append(_fmt_money(v))
            else:
                cells.append(f"{v:.1f}")
        lines.append(f"| {m['label']} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append(
        "_Market-share column is only share of this peer-set’s combined market cap — "
        "not true industry volume share. Not a buy/sell recommendation._"
    )
    lines.append(
        f"_Retrieved {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}._"
    )

    return {
        "ticker": symbol,
        "name": t.get("name"),
        "peer_tickers": [p["ticker"] for p in peer_rows],
        "companies": all_rows,
        "table": table,
        "edges": edges,
        "threats": threats,
        "warnings": warnings,
        "text": "\n".join(lines),
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "disclaimer": (
            "Competitive research synthesis using the same provider fields for every ticker. "
            "Not a recommendation to buy or sell. Peer choice drives the conclusion."
        ),
    }
