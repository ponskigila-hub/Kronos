"""
DIG THROUGH THE FINANCIALS — multi-period statement analysis.

Pulls income statement, balance sheet, and cash flow (annual + quarterly
when available via yfinance), compares periods, and flags unusual moves
or potential red flags. Research only — not a recommendation.
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


def _pct(a, b) -> Optional[float]:
    a, b = _n(a), _n(b)
    if a is None or b is None or b == 0:
        return None
    return (a - b) / abs(b) * 100.0


def _fmt(n: Optional[float], money: bool = True) -> str:
    if n is None:
        return "—"
    n = float(n)
    if not money:
        return f"{n:,.2f}"
    sign = "-" if n < 0 else ""
    n = abs(n)
    for u, d in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= d:
            return f"{sign}{n / d:.2f}{u}"
    return f"{sign}{n:.0f}"


def _fmt_pct(n: Optional[float]) -> str:
    if n is None:
        return "—"
    return f"{n:+.1f}%"


def _col_series(df, row_names: list[str]) -> dict:
    """Map period label -> value for the first matching row name."""
    if df is None or getattr(df, "empty", True):
        return {}
    idx = {str(i).lower(): i for i in df.index}
    key = None
    for name in row_names:
        if name.lower() in idx:
            key = idx[name.lower()]
            break
        # fuzzy contains
        for k, orig in idx.items():
            if name.lower() in k or k in name.lower():
                key = orig
                break
        if key is not None:
            break
    if key is None:
        return {}
    out = {}
    for col in df.columns:
        label = str(col.date()) if hasattr(col, "date") else str(col)[:10]
        out[label] = _n(df.loc[key, col])
    return out


def _periods_sorted(series: dict) -> list[str]:
    return sorted(series.keys(), reverse=True)


def _pick_rows(df) -> dict:
    """Common statement line items with alternate Yahoo row names."""
    if df is None or getattr(df, "empty", True):
        return {}
    mapping = {
        "revenue": ["Total Revenue", "Operating Revenue", "Revenue"],
        "gross_profit": ["Gross Profit"],
        "operating_income": ["Operating Income", "Operating Income Loss"],
        "net_income": ["Net Income", "Net Income Common Stockholders", "Normalized Income"],
        "ebitda": ["EBITDA", "Normalized EBITDA"],
        "eps_diluted": ["Diluted EPS", "Basic EPS"],
        "total_assets": ["Total Assets"],
        "total_liab": ["Total Liabilities Net Minority Interest", "Total Liabilities"],
        "total_equity": ["Stockholders Equity", "Total Equity Gross Minority Interest", "Common Stock Equity"],
        "cash": ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments", "Cash Financial"],
        "total_debt": ["Total Debt", "Long Term Debt", "Net Debt"],
        "current_assets": ["Current Assets"],
        "current_liab": ["Current Liabilities"],
        "operating_cf": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
        "capex": ["Capital Expenditure", "Purchase Of PPE"],
        "free_cash_flow": ["Free Cash Flow"],
        "issuance_stock": ["Issuance Of Capital Stock", "Issuance Of Stock"],
        "repurchase_stock": ["Repurchase Of Capital Stock", "Repurchase Of Stock"],
        "shares": ["Share Issued", "Ordinary Shares Number", "Common Stock"],
    }
    out = {}
    for key, names in mapping.items():
        s = _col_series(df, names)
        if s:
            out[key] = s
    return out


def _load_statements(ticker: str) -> dict:
    import yfinance as yf
    t = yf.Ticker(ticker)
    annual_inc = None
    annual_bs = None
    annual_cf = None
    q_inc = None
    q_bs = None
    q_cf = None
    try:
        annual_inc = getattr(t, "income_stmt", None)
        if annual_inc is None or (hasattr(annual_inc, "empty") and annual_inc.empty):
            annual_inc = getattr(t, "financials", None)
    except Exception:
        pass
    try:
        annual_bs = getattr(t, "balance_sheet", None)
    except Exception:
        pass
    try:
        annual_cf = getattr(t, "cashflow", None)
    except Exception:
        pass
    try:
        q_inc = getattr(t, "quarterly_income_stmt", None)
        if q_inc is None or (hasattr(q_inc, "empty") and q_inc.empty):
            q_inc = getattr(t, "quarterly_financials", None)
    except Exception:
        pass
    try:
        q_bs = getattr(t, "quarterly_balance_sheet", None)
    except Exception:
        pass
    try:
        q_cf = getattr(t, "quarterly_cashflow", None)
    except Exception:
        pass
    return {
        "annual": {
            "income": _pick_rows(annual_inc),
            "balance": _pick_rows(annual_bs),
            "cashflow": _pick_rows(annual_cf),
        },
        "quarterly": {
            "income": _pick_rows(q_inc),
            "balance": _pick_rows(q_bs),
            "cashflow": _pick_rows(q_cf),
        },
    }


def _trend(series: dict, n: int = 4) -> list[dict]:
    """Latest n periods with QoQ/YoY-style change vs prior period in the series."""
    periods = _periods_sorted(series)
    rows = []
    for i, p in enumerate(periods[:n]):
        val = series.get(p)
        prev = series.get(periods[i + 1]) if i + 1 < len(periods) else None
        rows.append({
            "period": p,
            "value": val,
            "chg_pct": _pct(val, prev),
        })
    return rows


def _margin(num: Optional[float], den: Optional[float]) -> Optional[float]:
    num, den = _n(num), _n(den)
    if num is None or den is None or den == 0:
        return None
    return num / den * 100.0


def _flags(annual: dict, quarterly: dict) -> list[str]:
    flags = []
    inc = annual.get("income") or {}
    bs = annual.get("balance") or {}
    cf = annual.get("cashflow") or {}
    q_inc = quarterly.get("income") or {}

    rev = inc.get("revenue") or {}
    ni = inc.get("net_income") or {}
    oi = inc.get("operating_income") or {}
    debt = bs.get("total_debt") or {}
    cash = bs.get("cash") or {}
    equity = bs.get("total_equity") or {}
    ocf = cf.get("operating_cf") or {}
    fcf = cf.get("free_cash_flow") or {}
    issue = cf.get("issuance_stock") or {}
    buyback = cf.get("repurchase_stock") or {}

    # Revenue deceleration / drop
    rev_t = _trend(rev, 3)
    if len(rev_t) >= 2 and rev_t[0].get("chg_pct") is not None:
        if rev_t[0]["chg_pct"] < -10:
            flags.append(f"Revenue down sharply vs prior annual period ({_fmt_pct(rev_t[0]['chg_pct'])}).")
        elif len(rev_t) >= 3 and rev_t[0]["chg_pct"] is not None and rev_t[1].get("chg_pct") is not None:
            if rev_t[0]["chg_pct"] + 8 < rev_t[1]["chg_pct"]:
                flags.append("Revenue growth decelerating vs the prior year-over-year step.")

    # Margin collapse
    if rev_t and ni:
        p0 = rev_t[0]["period"]
        gm_ni = _margin(ni.get(p0), rev.get(p0))
        if gm_ni is not None and gm_ni < 0:
            flags.append(f"Negative net margin in latest annual period ({gm_ni:.1f}%).")
        if len(rev_t) >= 2:
            p1 = rev_t[1]["period"]
            m0 = _margin(oi.get(p0) if oi else None, rev.get(p0))
            m1 = _margin(oi.get(p1) if oi else None, rev.get(p1))
            if m0 is not None and m1 is not None and m0 < m1 - 5:
                flags.append(f"Operating margin compressed ~{m1 - m0:.1f}pp vs prior year.")

    # Debt vs cash
    d_periods = _periods_sorted(debt)
    c_periods = _periods_sorted(cash)
    if d_periods and c_periods:
        d0, c0 = debt.get(d_periods[0]), cash.get(c_periods[0])
        if d0 is not None and c0 is not None and d0 > max(c0 * 3, 1):
            flags.append("Total debt substantially exceeds cash (leverage / liquidity watch).")
        if len(d_periods) >= 2 and debt.get(d_periods[0]) and debt.get(d_periods[1]):
            if _pct(debt[d_periods[0]], debt[d_periods[1]]) and _pct(debt[d_periods[0]], debt[d_periods[1]]) > 25:
                flags.append(f"Debt up {_fmt_pct(_pct(debt[d_periods[0]], debt[d_periods[1]]))} vs prior year.")

    # FCF negative while reporting profit
    f_periods = _periods_sorted(fcf) or _periods_sorted(ocf)
    if f_periods and ni:
        fp = f_periods[0]
        fval = fcf.get(fp) if fcf else ocf.get(fp)
        # align net income period approximately
        n_periods = _periods_sorted(ni)
        nval = ni.get(n_periods[0]) if n_periods else None
        if fval is not None and fval < 0 and nval is not None and nval > 0:
            flags.append("Profitable on net income but free/operating cash flow negative — quality of earnings watch.")

    # Dilution
    if issue:
        ip = _periods_sorted(issue)
        if ip and issue.get(ip[0]) and issue[ip[0]] > 0:
            bb = 0.0
            if buyback:
                bp = _periods_sorted(buyback)
                if bp:
                    bb = abs(buyback.get(bp[0]) or 0)
            issued = issue[ip[0]]
            if issued > bb * 1.2 and issued > 1e6:
                flags.append("Net share issuance / dilution signal (stock issued exceeds buybacks in latest CF period).")

    # Quarterly sequential revenue drop
    q_rev = (q_inc.get("revenue") or {}) if q_inc else {}
    qt = _trend(q_rev, 4)
    if len(qt) >= 2 and qt[0].get("chg_pct") is not None and qt[0]["chg_pct"] < -15:
        flags.append(f"Latest quarter revenue sequential drop {_fmt_pct(qt[0]['chg_pct'])}.")

    if not flags:
        flags.append("No automatic red flags from the simple rule set — still read the footnotes and 10-K/10-Q.")
    return flags


def dig_financials(ticker: str) -> dict[str, Any]:
    """
    Analyze latest multi-period income, balance sheet, and cash flow.
    """
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise ValueError("ticker is required")

    from .ticker_utils import validate_ticker
    ok, symbol = validate_ticker(ticker)
    if not ok:
        raise ValueError(f"'{ticker}' does not look like a valid ticker.")

    raw = _load_statements(symbol)
    annual, quarterly = raw["annual"], raw["quarterly"]

    flags = _flags(annual, quarterly)

    # Build narrative
    lines = []
    lines.append(f"## Dig through the financials — {symbol}")
    lines.append("")
    lines.append(
        "_Multi-period view from the data provider (Yahoo Finance statements). "
        "Prefer the company’s 10-K/10-Q for the definitive numbers._"
    )
    lines.append("")

    def _section(title: str, items: dict, keys: list[tuple[str, str]]):
        lines.append(f"### {title}")
        any_row = False
        for key, label in keys:
            series = items.get(key) or {}
            if not series:
                continue
            any_row = True
            rows = _trend(series, 4)
            parts = []
            for r in rows:
                ch = f" ({_fmt_pct(r['chg_pct'])})" if r.get("chg_pct") is not None else ""
                parts.append(f"**{r['period']}**: {_fmt(r['value'])}{ch}")
            lines.append(f"- **{label}**: " + " · ".join(parts))
        if not any_row:
            lines.append("_No rows returned for this statement (common for some ETFs, funds, or foreign listings)._")
        lines.append("")

    _section("Income statement (annual)", annual.get("income") or {}, [
        ("revenue", "Revenue"),
        ("gross_profit", "Gross profit"),
        ("operating_income", "Operating income"),
        ("net_income", "Net income"),
        ("eps_diluted", "Diluted EPS"),
    ])

    # Margins latest vs prior
    inc = annual.get("income") or {}
    rev_s, ni_s, oi_s = inc.get("revenue") or {}, inc.get("net_income") or {}, inc.get("operating_income") or {}
    rp = _periods_sorted(rev_s)
    if rp:
        p0 = rp[0]
        p1 = rp[1] if len(rp) > 1 else None
        lines.append("### Margins (annual)")
        op_m = _margin(oi_s.get(p0), rev_s.get(p0))
        ni_m = _margin(ni_s.get(p0), rev_s.get(p0))
        lines.append(
            f"- Latest (**{p0}**): operating margin **{_fmt(op_m, False)}%** · "
            f"net margin **{_fmt(ni_m, False)}%**"
        )
        if p1:
            lines.append(
                f"- Prior (**{p1}**): operating **{_fmt(_margin(oi_s.get(p1), rev_s.get(p1)), False)}%** · "
                f"net **{_fmt(_margin(ni_s.get(p1), rev_s.get(p1)), False)}%**"
            )
        lines.append("")

    _section("Balance sheet (annual)", annual.get("balance") or {}, [
        ("cash", "Cash & equivalents"),
        ("total_debt", "Total debt"),
        ("total_assets", "Total assets"),
        ("total_equity", "Equity"),
        ("current_assets", "Current assets"),
        ("current_liab", "Current liabilities"),
    ])

    _section("Cash flow (annual)", annual.get("cashflow") or {}, [
        ("operating_cf", "Operating cash flow"),
        ("capex", "Capex"),
        ("free_cash_flow", "Free cash flow"),
        ("issuance_stock", "Stock issuance"),
        ("repurchase_stock", "Stock repurchase"),
    ])

    # Quarterly snapshot
    q_inc = quarterly.get("income") or {}
    if q_inc.get("revenue"):
        lines.append("### Quarterly revenue (recent)")
        for r in _trend(q_inc["revenue"], 4):
            ch = f" ({_fmt_pct(r['chg_pct'])} seq.)" if r.get("chg_pct") is not None else ""
            lines.append(f"- **{r['period']}**: {_fmt(r['value'])}{ch}")
        lines.append("")

    lines.append("### Flags & unusual changes")
    for f in flags:
        lines.append(f"- {f}")
    lines.append("")
    lines.append(
        f"_Retrieved {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. "
        "Compare at least 3–4 periods; one quarter alone is easy to misread._"
    )

    return {
        "ticker": symbol,
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "annual": annual,
        "quarterly": quarterly,
        "flags": flags,
        "text": "\n".join(lines),
        "disclaimer": (
            "Research synthesis from provider statements — not audited filings. "
            "Not a recommendation to buy or sell."
        ),
    }
