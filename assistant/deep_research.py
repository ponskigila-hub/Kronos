"""
Medium/long-horizon research signals for Kronos (not trade signals).

Layers:
  1. Earnings revisions / post-earnings drift cues (PEAD-lite)
  2. Relative valuation multiples vs peers and simple history bands
  3. Transparent single-stage / two-stage DCF sanity range
  4. Macro snapshot (rates, USD, equity benchmark)
  5. News/NLP-lite sentiment from the existing news lexicon

All outputs are research scenarios. Yahoo Finance fields can be missing or lag.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional


def _n(value) -> Optional[float]:
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _pct(a, b) -> Optional[float]:
    a, b = _n(a), _n(b)
    if a is None or b is None or b == 0:
        return None
    return (a - b) / abs(b) * 100.0


# ---------------------------------------------------------------------------
# Earnings revisions & PEAD-lite
# ---------------------------------------------------------------------------
def _earnings_revision_block(ticker: str) -> dict:
    """Best-effort PEAD / revision cues from yfinance."""
    out = {
        "available": False,
        "last_report": None,
        "surprise_pct": None,
        "beat": None,
        "eps_trend": None,
        "revision_label": "unavailable",
        "pead_bias": "unknown",
        "notes": [],
    }
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info or {}
    except Exception as e:
        out["notes"].append(f"Could not load earnings fields: {e}")
        return out

    # Earnings history (actual vs estimate)
    surprise_pct = None
    try:
        eh = t.earnings_history
        if eh is not None and len(eh) > 0:
            row = eh.iloc[0]
            # columns vary by yfinance version
            for col in ("surprisePercent", "surprise_pct", "pct_diff"):
                if col in eh.columns:
                    surprise_pct = _n(row.get(col) if hasattr(row, "get") else row[col])
                    break
            if surprise_pct is None:
                act = _n(row.get("epsActual") if hasattr(row, "get") else row.get("actual"))
                est = _n(row.get("epsEstimate") if hasattr(row, "get") else row.get("estimate"))
                if act is not None and est not in (None, 0):
                    surprise_pct = (act - est) / abs(est) * 100.0
            out["last_report"] = {
                "period": str(row.name) if hasattr(row, "name") else None,
                "surprise_pct": None if surprise_pct is None else round(surprise_pct, 2),
            }
            out["surprise_pct"] = None if surprise_pct is None else round(surprise_pct, 2)
            if surprise_pct is not None:
                out["beat"] = surprise_pct > 0
                out["available"] = True
    except Exception:
        pass

    # Analyst EPS trend (current vs 30/60/90d ago) when present
    growth = _n(info.get("earningsGrowth") or info.get("earningsQuarterlyGrowth"))
    rev_growth = _n(info.get("revenueGrowth"))
    target_mean = _n(info.get("targetMeanPrice"))
    price = _n(info.get("currentPrice") or info.get("regularMarketPrice"))
    rec = info.get("recommendationKey") or info.get("recommendationMean")

    trend = {
        "earnings_growth": growth,
        "revenue_growth": rev_growth,
        "recommendation": rec,
        "analyst_upside_pct": _pct(target_mean, price),
    }
    out["eps_trend"] = trend

    # Heuristic revision / PEAD bias (transparent, not a model)
    score = 0
    if surprise_pct is not None:
        if surprise_pct >= 5:
            score += 2
            out["notes"].append(f"Last reported EPS surprise ≈ {surprise_pct:+.1f}% (beat).")
        elif surprise_pct <= -5:
            score -= 2
            out["notes"].append(f"Last reported EPS surprise ≈ {surprise_pct:+.1f}% (miss).")
        else:
            out["notes"].append(f"Last reported EPS surprise ≈ {surprise_pct:+.1f}% (near consensus).")
    if growth is not None:
        if growth > 0.1:
            score += 1
        elif growth < -0.05:
            score -= 1
    upside = trend.get("analyst_upside_pct")
    if upside is not None:
        if upside > 10:
            score += 1
        elif upside < -10:
            score -= 1

    if score >= 2:
        out["revision_label"] = "constructive"
        out["pead_bias"] = "positive_drift_bias"
    elif score <= -2:
        out["revision_label"] = "deteriorating"
        out["pead_bias"] = "negative_drift_bias"
    elif out["available"] or growth is not None:
        out["revision_label"] = "mixed"
        out["pead_bias"] = "neutral"
        out["available"] = True
    else:
        out["notes"].append("Not enough earnings-revision fields from the data provider.")

    out["notes"].append(
        "PEAD here is a research heuristic (surprise + growth + analyst upside), "
        "not a formal event-study result."
    )
    return out


# ---------------------------------------------------------------------------
# Relative multiples
# ---------------------------------------------------------------------------
def _relative_multiples(ticker: str, peer_tickers: Optional[list] = None) -> dict:
    from . import valuation as val_mod

    peers = peer_tickers or []
    if not peers:
        # Soft default: empty peers → company-only snapshot
        try:
            import yfinance as yf
            info = yf.Ticker(ticker).info or {}
        except Exception as e:
            return {"available": False, "error": str(e), "company": {}, "peers": []}

        company = {
            "ticker": ticker.upper(),
            "pe_trailing": _n(info.get("trailingPE")),
            "pe_forward": _n(info.get("forwardPE")),
            "ev_ebitda": _n(info.get("enterpriseToEbitda")),
            "price_to_book": _n(info.get("priceToBook")),
            "price_to_sales": _n(info.get("priceToSalesTrailing12Months")),
            "fcf_yield": None,
            "sector": info.get("sector"),
        }
        fcf = _n(info.get("freeCashflow"))
        mcap = _n(info.get("marketCap"))
        if fcf and mcap and mcap > 0:
            company["fcf_yield"] = round(fcf / mcap * 100.0, 2)
        return {
            "available": True,
            "company": company,
            "peers": [],
            "vs_peers": None,
            "notes": [
                "No peers supplied — showing company multiples only. "
                "Add peers on the Valuation page for relative ranges."
            ],
        }

    try:
        result = val_mod.fetch_relative_valuation(ticker, peers)
        return {
            "available": True,
            "relative_valuation": result,
            "notes": result.get("warnings") or [],
        }
    except Exception as e:
        return {"available": False, "error": str(e), "notes": [str(e)]}


# ---------------------------------------------------------------------------
# Transparent DCF (sanity range, not a bank model)
# ---------------------------------------------------------------------------
def simple_dcf(
    ticker: str,
    *,
    fcf: Optional[float] = None,
    shares: Optional[float] = None,
    growth_years: int = 5,
    growth_rate: Optional[float] = None,
    terminal_growth: float = 0.025,
    wacc: Optional[float] = None,
    net_debt: Optional[float] = None,
) -> dict:
    """Two-stage FCF DCF with explicit assumptions and a sensitivity band."""
    notes = []
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
    except Exception as e:
        return {"available": False, "error": str(e), "notes": [str(e)]}

    fcf = _n(fcf) or _n(info.get("freeCashflow"))
    shares = _n(shares) or _n(info.get("sharesOutstanding"))
    price = _n(info.get("currentPrice") or info.get("regularMarketPrice"))
    debt = _n(info.get("totalDebt")) or 0.0
    cash = _n(info.get("totalCash")) or 0.0
    if net_debt is None:
        net_debt = debt - cash

    if growth_rate is None:
        growth_rate = _n(info.get("earningsGrowth")) or _n(info.get("revenueGrowth")) or 0.06
        # Clamp absurd growth prints
        growth_rate = max(-0.05, min(0.25, growth_rate))
        notes.append(f"Growth defaulted from provider fields / 6% floor-cap → {growth_rate:.1%}.")
    if wacc is None:
        beta = _n(info.get("beta")) or 1.0
        # Rough CAPM-ish WACC: rf 4% + beta * 5% ERP, debt ignored for simplicity
        wacc = 0.04 + beta * 0.05
        wacc = max(0.06, min(0.14, wacc))
        notes.append(f"WACC approximated from beta ({beta:.2f}) → {wacc:.1%} (not company-specific CoD).")

    if not fcf or fcf <= 0 or not shares or shares <= 0:
        return {
            "available": False,
            "notes": notes + ["Need positive free cash flow and shares outstanding for DCF."],
            "assumptions": {
                "growth_rate": growth_rate,
                "terminal_growth": terminal_growth,
                "wacc": wacc,
            },
        }

    if terminal_growth >= wacc:
        terminal_growth = max(0.0, wacc - 0.01)
        notes.append("Terminal growth capped below WACC.")

    def _value(g, w, tg):
        pv = 0.0
        cf = fcf
        for yr in range(1, growth_years + 1):
            cf *= 1.0 + g
            pv += cf / ((1.0 + w) ** yr)
        terminal_cf = cf * (1.0 + tg)
        terminal_val = terminal_cf / (w - tg)
        pv += terminal_val / ((1.0 + w) ** growth_years)
        equity = pv - (net_debt or 0.0)
        return equity / shares

    base = _value(growth_rate, wacc, terminal_growth)
    low = _value(max(-0.02, growth_rate - 0.03), wacc + 0.015, max(0.0, terminal_growth - 0.005))
    high = _value(min(0.28, growth_rate + 0.03), max(0.055, wacc - 0.01), min(wacc - 0.005, terminal_growth + 0.005))

    upside = _pct(base, price) if price else None
    return {
        "available": True,
        "per_share": {
            "base": round(base, 2),
            "low": round(min(low, high), 2),
            "high": round(max(low, high), 2),
        },
        "current_price": price,
        "upside_vs_price_pct": None if upside is None else round(upside, 1),
        "assumptions": {
            "fcf": fcf,
            "shares": shares,
            "net_debt": net_debt,
            "growth_years": growth_years,
            "growth_rate": round(growth_rate, 4),
            "terminal_growth": round(terminal_growth, 4),
            "wacc": round(wacc, 4),
        },
        "notes": notes + [
            "DCF is a transparent sanity range, not a bank-grade intrinsic value. "
            "Small changes in WACC/growth move results a lot."
        ],
    }


# ---------------------------------------------------------------------------
# Macro snapshot
# ---------------------------------------------------------------------------
def macro_snapshot() -> dict:
    """Lightweight macro panel via public Yahoo symbols."""
    symbols = {
        "us_10y": "^TNX",       # 10Y yield *10 on Yahoo historically; treat carefully
        "us_equity": "SPY",
        "usd": "DX-Y.NYB",
        "gold": "GC=F",
        "oil": "CL=F",
    }
    rows = {}
    notes = []
    try:
        import yfinance as yf
        data = yf.download(
            list(symbols.values()),
            period="6mo",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        return {"available": False, "rows": {}, "notes": [str(e)]}

    for name, sym in symbols.items():
        try:
            if len(symbols) == 1:
                close = data["Close"].dropna()
            else:
                # Multi-index columns
                if hasattr(data.columns, "levels"):
                    close = data[sym]["Close"].dropna() if sym in data.columns.get_level_values(0) else None
                    if close is None:
                        # alternate orientation
                        close = data["Close"][sym].dropna() if "Close" in data and sym in data["Close"] else None
                else:
                    close = data["Close"].dropna()
            if close is None or len(close) < 25:
                continue
            last = float(close.iloc[-1])
            d1 = float(close.pct_change().iloc[-1]) * 100
            d21 = float(close.iloc[-1] / close.iloc[-22] - 1) * 100 if len(close) >= 22 else None
            d63 = float(close.iloc[-1] / close.iloc[-64] - 1) * 100 if len(close) >= 64 else None
            rows[name] = {
                "symbol": sym,
                "last": round(last, 4),
                "chg_1d_pct": round(d1, 2),
                "chg_1m_pct": None if d21 is None else round(d21, 2),
                "chg_3m_pct": None if d63 is None else round(d63, 2),
            }
        except Exception:
            continue

    if not rows:
        notes.append("Macro series unavailable from provider right now.")
        return {"available": False, "rows": {}, "notes": notes}

    # Simple regime tags
    tags = []
    eq = rows.get("us_equity")
    if eq and eq.get("chg_1m_pct") is not None:
        tags.append("equity_risk_on" if eq["chg_1m_pct"] > 0 else "equity_soft")
    yld = rows.get("us_10y")
    if yld and yld.get("chg_1m_pct") is not None:
        tags.append("yields_up" if yld["chg_1m_pct"] > 0 else "yields_down")
    notes.append(
        "Macro panel is a desk snapshot (SPY, USD, 10Y proxy, commodities) — "
        "not a full sector-rotation model."
    )
    return {"available": True, "rows": rows, "tags": tags, "notes": notes}


# ---------------------------------------------------------------------------
# Sentiment (reuses news lexicon; FinBERT optional later)
# ---------------------------------------------------------------------------
def sentiment_block(ticker: str) -> dict:
    try:
        from . import news as news_mod
        items, summary = news_mod.get_news(ticker)
    except Exception as e:
        return {"available": False, "notes": [str(e)], "summary": None, "headlines": []}

    headlines = []
    for it in (items or [])[:6]:
        headlines.append({
            "title": it.get("title") or it.get("headline"),
            "publisher": it.get("publisher"),
            "score": it.get("score"),
        })
    return {
        "available": summary is not None,
        "summary": summary,
        "headlines": headlines,
        "notes": [
            "Sentiment is lexicon/NLP-lite over recent headlines (not FinBERT on full transcripts). "
            "Tone can diverge from price."
        ],
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def build_fundamental_insight(
    ticker: str,
    peer_tickers: Optional[list] = None,
    include_macro: bool = True,
) -> dict:
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise ValueError("ticker is required")

    peers = []
    for p in peer_tickers or []:
        s = str(p).strip().upper()
        if s and s != ticker and s not in peers:
            peers.append(s)

    earnings = _earnings_revision_block(ticker)
    relative = _relative_multiples(ticker, peers)
    dcf = simple_dcf(ticker)
    sentiment = sentiment_block(ticker)
    macro = macro_snapshot() if include_macro else {"available": False, "rows": {}, "notes": []}

    # Composite research stance (transparent weights, not a rating agency score)
    score = 0.0
    weights_used = []
    if earnings.get("revision_label") == "constructive":
        score += 1
        weights_used.append("earnings+")
    elif earnings.get("revision_label") == "deteriorating":
        score -= 1
        weights_used.append("earnings-")
    if dcf.get("available") and dcf.get("upside_vs_price_pct") is not None:
        u = dcf["upside_vs_price_pct"]
        if u > 15:
            score += 1
            weights_used.append("dcf+")
        elif u < -15:
            score -= 1
            weights_used.append("dcf-")
    lab = (sentiment.get("summary") or {}).get("label")
    if lab == "mostly positive":
        score += 0.5
        weights_used.append("news+")
    elif lab == "mostly negative":
        score -= 0.5
        weights_used.append("news-")

    if score >= 1.5:
        stance = "fundamentally constructive"
    elif score <= -1.5:
        stance = "fundamentally cautious"
    else:
        stance = "mixed / needs judgment"

    return {
        "ticker": ticker,
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "stance": stance,
        "stance_drivers": weights_used,
        "earnings": earnings,
        "relative": relative,
        "dcf": dcf,
        "sentiment": sentiment,
        "macro": macro,
        "disclaimer": (
            "Research synthesis only — not a recommendation to buy or sell. "
            "DCF and PEAD heuristics are simplified; provider data may be incomplete."
        ),
    }


# ---------------------------------------------------------------------------
# Full Wall Street Breakdown (equity-analyst style research note)
# ---------------------------------------------------------------------------
def _fmt_money(n: Optional[float]) -> str:
    if n is None:
        return "n/a"
    n = float(n)
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(n) >= div:
            return f"{n / div:.2f}{unit}"
    return f"{n:.0f}"


def _fmt_pct_val(n: Optional[float], already_ratio: bool = True) -> str:
    if n is None:
        return "n/a"
    v = float(n) * 100 if already_ratio else float(n)
    return f"{v:.1f}%"


def _safe_info(ticker: str) -> dict:
    try:
        import yfinance as yf
        return yf.Ticker(ticker).info or {}
    except Exception:
        return {}


def _latest_earnings_snapshot(ticker: str) -> dict:
    """Pull the most recent earnings surprise / date when yfinance has it."""
    out = {
        "available": False,
        "period": None,
        "surprise_pct": None,
        "beat": None,
        "next_date": None,
        "days_until": None,
        "notes": [],
    }
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        eh = getattr(t, "earnings_history", None)
        if eh is not None and len(eh) > 0:
            row = eh.iloc[0]
            surprise = None
            for col in ("surprisePercent", "surprise_pct", "pct_diff"):
                if col in eh.columns:
                    surprise = _n(row.get(col) if hasattr(row, "get") else row[col])
                    break
            if surprise is None:
                act = _n(row.get("epsActual") if hasattr(row, "get") else row.get("actual"))
                est = _n(row.get("epsEstimate") if hasattr(row, "get") else row.get("estimate"))
                if act is not None and est not in (None, 0):
                    surprise = (act - est) / abs(est) * 100.0
            out["period"] = str(row.name) if hasattr(row, "name") else None
            out["surprise_pct"] = None if surprise is None else round(surprise, 2)
            out["beat"] = surprise > 0 if surprise is not None else None
            out["available"] = True
        # Next earnings
        try:
            from . import fundamentals as fund_mod
            nxt = fund_mod.get_next_earnings_info(ticker)
            if nxt and nxt.get("date"):
                out["next_date"] = str(nxt["date"])
                out["days_until"] = nxt.get("days_until")
        except Exception:
            pass
    except Exception as e:
        out["notes"].append(f"Earnings snapshot limited: {e}")
    return out


def build_wall_street_breakdown(ticker: str) -> dict:
    """
    Structured equity-analyst style note for one ticker.

    Sections (aligned with a classic Wall Street initiation / update memo):
      1. Business model & positioning
      2. Revenue drivers & growth
      3. Margins & profitability
      4. Cash flow & balance-sheet health
      5. Competitive position
      6. Recent earnings
      7. Catalysts
      8. Biggest risks
      9. Key numbers to monitor

    Data is grounded in Yahoo Finance (info, earnings history, targets) plus
    existing Kronos news/sentiment helpers. Missing fields are called out
    explicitly — never invented.
    """
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise ValueError("ticker is required")

    from . import fundamentals as fund_mod
    from . import news as news_mod

    try:
        fund = fund_mod.get_fundamentals(ticker)
    except Exception as e:
        raise ValueError(f"Could not load fundamentals for {ticker}: {e}") from e

    try:
        analyst = fund_mod.get_analyst_targets(ticker)
    except Exception:
        analyst = {}

    info = _safe_info(ticker)
    earnings = _latest_earnings_snapshot(ticker)

    try:
        _items, news_summary = news_mod.get_news(ticker)
    except Exception:
        news_summary = {"label": "unavailable", "score": None, "headline_count": 0}

    # --- Structured sections (data only) ---
    business = {
        "name": fund.get("name") or ticker,
        "sector": fund.get("sector"),
        "industry": fund.get("industry"),
        "description": (fund.get("description") or info.get("longBusinessSummary") or "")[:1200] or None,
        "employees": fund.get("employees") or info.get("fullTimeEmployees"),
        "country": fund.get("country") or info.get("country"),
        "website": fund.get("website") or info.get("website"),
        "exchange": fund.get("exchange"),
    }

    growth = {
        "revenue_growth": fund.get("revenue_growth"),
        "earnings_growth": fund.get("earnings_growth"),
        "market_cap": fund.get("market_cap"),
        "trailing_pe": fund.get("pe_ratio"),
        "forward_pe": fund.get("forward_pe"),
        "peg": fund.get("peg_ratio"),
        "eps": fund.get("eps"),
        "forward_eps": fund.get("forward_eps"),
    }

    margins = {
        "profit_margin": fund.get("profit_margin"),
        "operating_margin": fund.get("operating_margin"),
        "roe": fund.get("roe"),
        "roa": fund.get("roa"),
    }

    cash = {
        "free_cashflow": fund.get("free_cashflow"),
        "debt_to_equity": fund.get("debt_to_equity"),
        "current_ratio": fund.get("current_ratio"),
        "dividend_yield": fund.get("dividend_yield"),
    }

    competitive = {
        "sector": business["sector"],
        "industry": business["industry"],
        "beta": fund.get("beta"),
        "fifty_two_week_low": fund.get("fifty_two_week_low"),
        "fifty_two_week_high": fund.get("fifty_two_week_high"),
        "current_price": fund.get("current_price"),
    }

    catalysts = []
    if earnings.get("next_date"):
        days = earnings.get("days_until")
        catalysts.append(
            f"Next earnings: {earnings['next_date']}"
            + (f" ({days}d)" if days is not None else "")
        )
    if analyst.get("target_mean") and fund.get("current_price"):
        upside = (analyst["target_mean"] - fund["current_price"]) / fund["current_price"] * 100
        catalysts.append(
            f"Analyst mean target {_fmt_money(analyst['target_mean'])} "
            f"({upside:+.1f}% vs last)"
        )
    if news_summary and news_summary.get("label") not in (None, "unavailable"):
        catalysts.append(f"Recent headline tone: {news_summary.get('label')}")

    risks = []
    if fund.get("debt_to_equity") is not None and float(fund["debt_to_equity"]) > 150:
        risks.append("Elevated debt-to-equity (>150) — leverage / refinancing sensitivity.")
    if fund.get("profit_margin") is not None and float(fund["profit_margin"]) < 0:
        risks.append("Negative profit margin — profitability not yet established or under pressure.")
    if fund.get("beta") is not None and float(fund["beta"]) > 1.4:
        risks.append(f"High beta ({float(fund['beta']):.2f}) — larger swings vs the market.")
    if earnings.get("days_until") is not None and 0 <= earnings["days_until"] <= 14:
        risks.append("Earnings within ~2 weeks — event risk and wider path uncertainty.")
    if not risks:
        risks.append("Standard equity risks: multiple compression, competition, macro, and company-specific execution.")

    monitor = [
        "Next earnings date and EPS / revenue surprise vs consensus",
        "Revenue growth and operating margin trend (QoQ / YoY)",
        "Free cash flow and debt-to-equity path",
        "Forward P/E vs own history and closest peers",
        "Analyst target / recommendation revisions",
        "Any material guidance change or segment mix shift",
    ]

    # --- Narrative (rule-based; optional LLM polish happens upstream if used) ---
    lines = []
    lines.append(f"## Wall Street-style breakdown — {business['name']} ({ticker})")
    lines.append("")
    lines.append(
        "_Research synthesis only. Not a recommendation to buy or sell. "
        "Provider data can be incomplete or lagged._"
    )
    lines.append("")

    # 1 Business model
    lines.append("### 1. Business model & positioning")
    if business["description"]:
        lines.append(business["description"])
    else:
        lines.append("No long business summary returned by the data provider for this ticker.")
    bits = []
    if business["sector"]:
        bits.append(f"Sector: **{business['sector']}**")
    if business["industry"]:
        bits.append(f"Industry: **{business['industry']}**")
    if business["employees"]:
        bits.append(f"Employees: ~{int(business['employees']):,}")
    if business["country"]:
        bits.append(f"HQ country: {business['country']}")
    if bits:
        lines.append("")
        lines.append(" · ".join(bits))
    lines.append("")

    # 2 Growth
    lines.append("### 2. Revenue drivers & growth")
    pe_s = f"{growth['trailing_pe']:.1f}" if growth.get("trailing_pe") is not None else "n/a"
    lines.append(f"- Market cap: **{_fmt_money(growth['market_cap'])}** | Trailing P/E: **{pe_s}**")
    if growth.get("forward_pe") is not None:
        peg_bit = f" | PEG: **{growth['peg']:.2f}**" if growth.get("peg") is not None else ""
        lines.append(f"- Forward P/E: **{growth['forward_pe']:.1f}**{peg_bit}")
    lines.append(
        f"- Revenue growth (YoY, provider): **{_fmt_pct_val(growth['revenue_growth'])}** | "
        f"Earnings growth: **{_fmt_pct_val(growth['earnings_growth'])}**"
    )
    if growth.get("eps") or growth.get("forward_eps"):
        lines.append(
            f"- EPS trailing / forward: "
            f"**{growth['eps'] if growth.get('eps') is not None else 'n/a'}** / "
            f"**{growth['forward_eps'] if growth.get('forward_eps') is not None else 'n/a'}**"
        )
    lines.append(
        "_Revenue-driver detail (segment mix, pricing, volume) is not fully available "
        "from the free data feed — use the company 10-K / latest earnings deck for the real driver tree._"
    )
    lines.append("")

    # 3 Margins
    lines.append("### 3. Margins & profitability")
    lines.append(
        f"- Operating margin: **{_fmt_pct_val(margins['operating_margin'])}** | "
        f"Profit margin: **{_fmt_pct_val(margins['profit_margin'])}**"
    )
    lines.append(
        f"- ROE: **{_fmt_pct_val(margins['roe'])}** | ROA: **{_fmt_pct_val(margins['roa'])}**"
    )
    lines.append("")

    # 4 Cash flow
    lines.append("### 4. Cash flow & balance sheet")
    lines.append(
        f"- Free cash flow (TTM, provider): **{_fmt_money(cash['free_cashflow'])}**"
    )
    de = cash.get("debt_to_equity")
    de_s = "n/a" if de is None else f"{float(de):.1f}"
    cr = cash.get("current_ratio")
    cr_s = "n/a" if cr is None else f"{float(cr):.2f}"
    lines.append(f"- Debt / equity: **{de_s}** | Current ratio: **{cr_s}**")
    if cash.get("dividend_yield"):
        lines.append(f"- Dividend yield: **{_fmt_pct_val(cash['dividend_yield'])}**")
    lines.append("")

    # 5 Competitive
    lines.append("### 5. Competitive position")
    lines.append(
        f"- Industry context: **{competitive.get('industry') or 'n/a'}** "
        f"(sector {competitive.get('sector') or 'n/a'})"
    )
    if competitive.get("beta") is not None:
        lines.append(f"- Beta: **{float(competitive['beta']):.2f}** (sensitivity vs market)")
    if competitive.get("fifty_two_week_low") and competitive.get("fifty_two_week_high"):
        lines.append(
            f"- 52-week range: **{competitive['fifty_two_week_low']:.2f} – "
            f"{competitive['fifty_two_week_high']:.2f}** "
            f"(last ~{competitive.get('current_price') or 'n/a'})"
        )
    lines.append(
        "_Moat quality (switching costs, network effects, cost advantage) requires qualitative "
        "judgment from filings and competitive landscape — not inferred from multiples alone._"
    )
    lines.append("")

    # 6 Recent earnings
    lines.append("### 6. Recent earnings")
    if earnings.get("available"):
        beat = earnings.get("beat")
        surprise = earnings.get("surprise_pct")
        lines.append(
            f"- Last reported period: **{earnings.get('period') or 'n/a'}** | "
            f"EPS surprise: **{f'{surprise:+.1f}%' if surprise is not None else 'n/a'}**"
            + (" (beat)" if beat is True else " (miss)" if beat is False else "")
        )
    else:
        lines.append("- Latest EPS surprise not available from the provider for this ticker.")
    if earnings.get("next_date"):
        lines.append(
            f"- Next report: **{earnings['next_date']}**"
            + (f" ({earnings['days_until']} days)" if earnings.get("days_until") is not None else "")
        )
    lines.append("")

    # 7 Catalysts
    lines.append("### 7. Catalysts")
    if catalysts:
        for c in catalysts:
            lines.append(f"- {c}")
    else:
        lines.append("- No near-term catalyst flagged from earnings date / targets / headlines.")
    if analyst.get("recommendation"):
        lines.append(
            f"- Street consensus: **{str(analyst['recommendation']).replace('_', ' ').title()}** "
            f"({analyst.get('num_analysts') or '?'} analysts)"
        )
    lines.append("")

    # 8 Risks
    lines.append("### 8. Biggest risks")
    for r in risks:
        lines.append(f"- {r}")
    lines.append("")

    # 9 Monitorables
    lines.append("### 9. Key numbers an investor should monitor")
    for m in monitor:
        lines.append(f"- {m}")
    lines.append("")
    lines.append(
        f"_Data retrieved {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. "
        "Prefer the company’s latest 10-Q/10-K and earnings release for the definitive view._"
    )

    text = "\n".join(lines)

    return {
        "ticker": ticker,
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "business": business,
        "growth": growth,
        "margins": margins,
        "cash": cash,
        "competitive": competitive,
        "earnings": earnings,
        "analyst": analyst,
        "news_summary": news_summary,
        "catalysts": catalysts,
        "risks": risks,
        "monitor": monitor,
        "text": text,
        "disclaimer": (
            "Research synthesis only — not a recommendation to buy or sell. "
            "Grounded in provider data (Yahoo Finance) which can lag or be incomplete; "
            "always cross-check the latest company filing."
        ),
    }
