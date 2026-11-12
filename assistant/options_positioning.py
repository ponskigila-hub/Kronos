"""
Options & derivatives positioning snapshot (research only).

Uses Yahoo option chains via yfinance when available:
- Put/Call volume and open-interest ratios
- Rough implied-vol skew (OTM put IV vs OTM call IV near selected expiry)
- Simplified dealer gamma *heuristic* near the spot (not OPRA/official GEX)

Yahoo options data is delayed/incomplete for many names and unavailable for
some listings (e.g. many IDX tickers). Always treated as a research aid.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
import math

import pandas as pd

from .ticker_utils import validate_ticker


def _n(v) -> Optional[float]:
    try:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _safe_sum(series) -> float:
    if series is None:
        return 0.0
    s = pd.to_numeric(series, errors="coerce").fillna(0)
    return float(s.sum())


def _pick_expiry(expiries: list[str], prefer_days: int = 30) -> Optional[str]:
    if not expiries:
        return None
    today = datetime.now(timezone.utc).date()
    best, best_diff = None, 10**9
    for e in expiries:
        try:
            d = datetime.strptime(e, "%Y-%m-%d").date()
        except ValueError:
            continue
        diff = abs((d - today).days - prefer_days)
        if (d - today).days < 2:
            continue
        if diff < best_diff:
            best, best_diff = e, diff
    return best or expiries[0]


def _atm_iv(df: pd.DataFrame, spot: float, side: str) -> Optional[float]:
    """Nearest-strike IV on one side of the chain."""
    if df is None or df.empty or not spot:
        return None
    work = df.copy()
    if "impliedVolatility" not in work.columns or "strike" not in work.columns:
        return None
    work["iv"] = pd.to_numeric(work["impliedVolatility"], errors="coerce")
    work["strike"] = pd.to_numeric(work["strike"], errors="coerce")
    work = work.dropna(subset=["iv", "strike"])
    if work.empty:
        return None
    # prefer slightly OTM: puts strikes < spot, calls strikes > spot
    if side == "put":
        sub = work[work["strike"] <= spot]
        if sub.empty:
            sub = work
        row = sub.iloc[(spot - sub["strike"]).abs().argsort()[:1]]
    else:
        sub = work[work["strike"] >= spot]
        if sub.empty:
            sub = work
        row = sub.iloc[(sub["strike"] - spot).abs().argsort()[:1]]
    iv = _n(row["iv"].iloc[0])
    return iv * 100 if iv is not None and iv < 5 else (iv if iv is not None else None)


def _approx_gamma(spot: float, strike: float, t_years: float, iv: float) -> float:
    """Black-Scholes gamma proxy (call=put gamma). Very rough."""
    if not spot or not strike or t_years <= 0 or not iv or iv <= 0:
        return 0.0
    try:
        import math as m
        sigma = iv if iv > 1 else iv  # already decimal if <1
        if sigma > 1:  # percent
            sigma = sigma / 100.0
        sqrt_t = m.sqrt(t_years)
        if sqrt_t < 1e-6 or sigma < 1e-6:
            return 0.0
        d1 = (m.log(spot / strike) + 0.5 * sigma * sigma * t_years) / (sigma * sqrt_t)
        pdf = m.exp(-0.5 * d1 * d1) / m.sqrt(2 * m.pi)
        return pdf / (spot * sigma * sqrt_t)
    except Exception:
        return 0.0


def analyze_options_positioning(ticker: str) -> dict[str, Any]:
    ok, symbol = validate_ticker(ticker)
    if not ok:
        raise ValueError(f"'{ticker}' does not look like a valid ticker.")

    import yfinance as yf
    t = yf.Ticker(symbol)
    info = t.info or {}
    spot = _n(info.get("currentPrice") or info.get("regularMarketPrice"))
    if spot is None:
        try:
            h = t.history(period="5d")
            if h is not None and not h.empty:
                spot = float(h["Close"].iloc[-1])
        except Exception:
            pass
    if spot is None:
        raise ValueError(f"No spot price for {symbol}.")

    try:
        expiries = list(t.options or [])
    except Exception as e:
        raise ValueError(f"No options chain for {symbol}: {e}") from e
    if not expiries:
        raise ValueError(
            f"Yahoo has no listed equity options for {symbol}. "
            "Many non-US tickers (e.g. .JK) have no chain on Yahoo."
        )

    expiry = _pick_expiry(expiries, prefer_days=30)
    try:
        chain = t.option_chain(expiry)
    except Exception as e:
        raise ValueError(f"Could not load option chain for {symbol} {expiry}: {e}") from e

    calls, puts = chain.calls, chain.puts
    call_vol = _safe_sum(calls.get("volume"))
    put_vol = _safe_sum(puts.get("volume"))
    call_oi = _safe_sum(calls.get("openInterest"))
    put_oi = _safe_sum(puts.get("openInterest"))

    pc_vol = (put_vol / call_vol) if call_vol > 0 else None
    pc_oi = (put_oi / call_oi) if call_oi > 0 else None

    put_iv = _atm_iv(puts, spot, "put")
    call_iv = _atm_iv(calls, spot, "call")
    skew_pts = None
    if put_iv is not None and call_iv is not None:
        skew_pts = put_iv - call_iv  # positive = put IV richer (bearish skew)

    # Dealer gamma heuristic: sum OI * gamma * contract multiplier, sign flips
    # for puts (dealers often short customer puts → opposite gamma).
    # This is NOT professional GEX — illustrative only.
    try:
        exp_d = datetime.strptime(expiry, "%Y-%m-%d").date()
        t_years = max((exp_d - datetime.now(timezone.utc).date()).days, 1) / 365.0
    except Exception:
        t_years = 30 / 365.0

    mult = 100.0
    gex_call = 0.0
    gex_put = 0.0
    for _, row in calls.iterrows():
        iv = _n(row.get("impliedVolatility")) or 0
        oi = _n(row.get("openInterest")) or 0
        k = _n(row.get("strike")) or 0
        g = _approx_gamma(spot, k, t_years, iv)
        # Convention: positive GEX when dealers long calls (customers short)
        # We assume dealers are net short retail premium → flip sign of customer OI gamma
        gex_call += -oi * g * mult * spot
    for _, row in puts.iterrows():
        iv = _n(row.get("impliedVolatility")) or 0
        oi = _n(row.get("openInterest")) or 0
        k = _n(row.get("strike")) or 0
        g = _approx_gamma(spot, k, t_years, iv)
        # short puts → dealers have positive gamma on puts in some books; use opposite of OI
        gex_put += oi * g * mult * spot
    net_gex = gex_call + gex_put

    # Narrative
    stance = []
    if pc_vol is not None:
        if pc_vol >= 1.2:
            stance.append(f"Put/call **volume** ratio **{pc_vol:.2f}** — elevated put activity vs calls.")
        elif pc_vol <= 0.7:
            stance.append(f"Put/call **volume** ratio **{pc_vol:.2f}** — calls dominate today’s volume.")
        else:
            stance.append(f"Put/call **volume** ratio **{pc_vol:.2f}** — balanced.")
    if pc_oi is not None:
        stance.append(f"Put/call **open interest** ratio **{pc_oi:.2f}**.")
    if skew_pts is not None:
        if skew_pts > 3:
            stance.append(f"IV skew **+{skew_pts:.1f} vol pts** (OTM-ish puts richer than calls) — demand for downside protection.")
        elif skew_pts < -3:
            stance.append(f"IV skew **{skew_pts:.1f} vol pts** — call side richer than puts near this expiry.")
        else:
            stance.append(f"IV skew roughly flat (**{skew_pts:+.1f}** pts put−call).")
    if net_gex is not None:
        if net_gex > 0:
            stance.append(
                "Heuristic **net gamma** near spot is **positive** — dealer hedging *may* dampen moves "
                "(buy dips / sell rips). Treat as illustrative only."
            )
        else:
            stance.append(
                "Heuristic **net gamma** near spot is **negative** — hedging flows *may* amplify moves. "
                "Illustrative only; not official GEX."
            )

    lines = [
        f"## Options positioning — {symbol}",
        "",
        f"Spot ≈ **{spot:,.2f}** · Expiry focus **{expiry}** · Yahoo chain (delayed).",
        "",
        "### Put / Call",
        f"- Call volume **{call_vol:,.0f}** · Put volume **{put_vol:,.0f}**",
        f"- Call OI **{call_oi:,.0f}** · Put OI **{put_oi:,.0f}**",
        f"- P/C volume **{(f'{pc_vol:.2f}' if pc_vol is not None else '—')}** · "
        f"P/C OI **{(f'{pc_oi:.2f}' if pc_oi is not None else '—')}**",
        "",
        "### Implied vol skew (near-ATM)",
        f"- Put IV ≈ **{(f'{put_iv:.1f}%' if put_iv is not None else '—')}** · "
        f"Call IV ≈ **{(f'{call_iv:.1f}%' if call_iv is not None else '—')}**",
        f"- Skew (put − call) ≈ **{(f'{skew_pts:+.1f}' if skew_pts is not None else '—')}** vol pts",
        "",
        "### Dealer gamma heuristic",
        f"- Net GEX proxy (scaled) ≈ **{net_gex:,.0f}**",
        "- Built from OI × BS-gamma near one expiry with a short-dealer assumption. "
        "**Not** the same as SpotGamma / official dealer reports.",
        "",
        "### Read-through",
    ]
    for s in stance:
        lines.append(f"- {s}")
    lines += [
        "",
        "### Caveats",
        "- Options data on Yahoo can be thin, delayed, or missing greeks.",
        "- Hedging flows are path-dependent; one snapshot cannot force the next print.",
        "- Research only — not a trade recommendation.",
        "",
        f"_Retrieved {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}._",
    ]

    return {
        "ticker": symbol,
        "spot": spot,
        "expiry": expiry,
        "expiries": expiries[:12],
        "call_volume": call_vol,
        "put_volume": put_vol,
        "call_oi": call_oi,
        "put_oi": put_oi,
        "pc_volume": pc_vol,
        "pc_oi": pc_oi,
        "put_iv": put_iv,
        "call_iv": call_iv,
        "skew_pts": skew_pts,
        "net_gex_proxy": net_gex,
        "notes": stance,
        "text": "\n".join(lines),
        "disclaimer": (
            "Yahoo options snapshot for research only. Put/call and skew are descriptive; "
            "dealer gamma is a simplified heuristic — not a prediction or recommendation."
        ),
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
