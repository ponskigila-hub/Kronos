"""
Orchestrates a full screen:

    Universe -> Download (concurrent, cached) -> Metrics -> Filters
    -> Score & Rank -> Top N -> Kronos -> Re-rank Top N -> Result

Single entry point: run_screen(...). Callable programmatically (CLI, bots,
tests) exactly the same way the web app calls it -- the screener has no
dependency on Flask or any particular interface.

Every ticker is isolated: one bad/delisted/thin ticker is recorded with a
reason and skipped, never allowed to abort the rest of the screen (project
brief #21/#27). Nothing here uses information beyond each ticker's own
downloaded history, and everything is computed as of "now" (the latest
available bar) -- see screener/metrics.py's docstring on why that keeps a
single screen run free of look-ahead bias; walk-forward historical
evaluation of the screener itself (brief #25) is intentionally out of
scope for this pass and would be a natural follow-up module.
"""
import time

from . import data as data_mod
from . import metrics as metrics_mod
from . import scoring as scoring_mod
from . import presets as presets_mod
from . import filters as filters_mod
from . import reasons as reasons_mod
from . import kronos_integration
from ..config import SCREENER_CONFIG


def run_screen(
    universe_key="sp500",
    user_id="default",
    custom_text=None,
    csv_rows=None,
    preset_key="none",
    custom_filters=None,
    weights=None,
    min_avg_dollar_volume=None,
    min_history_days=None,
    benchmark=None,
    lookback_days=None,
    preselection_count=None,
    final_count=None,
    enable_kronos=False,
    pred_len=30,
    progress_cb=None,
):
    """See module docstring for the pipeline. `progress_cb(stage, done, total, label)`
    is called throughout -- stage is "download" or "kronos"."""
    from . import universe as universe_mod

    cfg = SCREENER_CONFIG
    min_avg_dollar_volume = cfg["min_avg_dollar_volume"] if min_avg_dollar_volume is None else min_avg_dollar_volume
    min_history_days = cfg["min_history_days"] if min_history_days is None else min_history_days
    benchmark = benchmark or cfg["benchmark"]
    lookback_days = lookback_days or cfg["lookback_days"]
    preselection_count = preselection_count or cfg["preselection_count"]
    final_count = final_count or cfg["final_count"]

    preset = presets_mod.get(preset_key)
    active_weights = weights or preset.get("weights") or scoring_mod.DEFAULT_WEIGHTS
    force_kronos = bool(preset.get("force_kronos"))
    enable_kronos = enable_kronos or force_kronos

    t0 = time.time()

    # ------------------------------------------------------------- universe
    tickers = universe_mod.resolve_universe(
        universe_key, user_id=user_id, custom_text=custom_text, csv_rows=csv_rows,
    )
    tickers = [t for t in dict.fromkeys(tickers) if t and t != benchmark]  # dedupe, preserve order
    universe_size = len(tickers)
    if universe_size == 0:
        return {
            "universe_size": 0, "rows": [], "skipped": [],
            "quality_summary": {"scanned": 0, "analyzed": 0, "insufficient_history": 0,
                                 "download_failed": 0, "low_liquidity": 0, "filtered_out": 0},
            "config_used": {"universe": universe_key, "preset": preset_key},
            "kronos_ran": False, "elapsed_seconds": 0,
            "error": "That universe came back empty -- check the ticker list / CSV / watchlist.",
        }

    # --------------------------------------------------------------- download
    def _dl_progress(done, total, ticker):
        if progress_cb:
            progress_cb("download", done, total, ticker)

    fetch_list = tickers + [benchmark]
    history, failures = data_mod.fetch_universe(fetch_list, lookback_days=lookback_days, progress_cb=_dl_progress)
    benchmark_df = history.get(benchmark)

    # ------------------------------------------------------- metrics + filter
    scored = []
    skipped = []
    filtered_out_count = 0
    low_liquidity_count = 0
    insufficient_history_count = 0

    for ticker in tickers:
        if ticker in failures:
            skipped.append({"ticker": ticker, "reason": "Download Failed", "detail": failures[ticker]})
            continue
        df = history.get(ticker)
        if df is None or len(df) < min_history_days:
            insufficient_history_count += 1
            skipped.append({"ticker": ticker, "reason": "Insufficient History",
                             "detail": f"Only {0 if df is None else len(df)} trading days available "
                                       f"(need {min_history_days})."})
            continue

        try:
            m = metrics_mod.compute_metrics(df, benchmark_df=benchmark_df)
        except Exception as e:
            skipped.append({"ticker": ticker, "reason": "Invalid Data", "detail": str(e)})
            continue

        dv = m.get("liquidity_avg_dollar_volume_20d")
        if dv is not None and dv < min_avg_dollar_volume:
            low_liquidity_count += 1
            skipped.append({"ticker": ticker, "reason": "Low Liquidity",
                             "detail": f"20D avg dollar volume ${dv:,.0f} is below the ${min_avg_dollar_volume:,.0f} minimum."})
            continue

        preset_pass, preset_failed = presets_mod.apply_preset_filters(m, preset_key)
        custom_pass, custom_failed = filters_mod.evaluate_all(m, custom_filters or [])
        if not (preset_pass and custom_pass):
            filtered_out_count += 1
            continue

        cat_scores = scoring_mod.compute_category_scores(m, min_dollar_volume=min_avg_dollar_volume, kronos_result=None)
        overall, _ = scoring_mod.composite_score(cat_scores, weights=active_weights)
        scored.append({
            "ticker": ticker, "price": m.get("price"), "metrics": m,
            "category_scores": cat_scores, "overall_score": overall,
            "kronos": None, "in_kronos_stage": False,
        })

    scored.sort(key=lambda r: r["overall_score"], reverse=True)

    # ------------------------------------------------------------- kronos
    kronos_ran = False
    if enable_kronos and scored:
        top_for_kronos = scored[:preselection_count]
        kronos_tickers = [r["ticker"] for r in top_for_kronos]

        def _kr_progress(done, total, ticker):
            if progress_cb:
                progress_cb("kronos", done, total, ticker)

        kronos_results = kronos_integration.run_for_candidates(
            kronos_tickers, history, pred_len=pred_len, n_runs=1, progress_cb=_kr_progress,
        )
        kronos_ran = True

        for row in top_for_kronos:
            kr = kronos_results.get(row["ticker"])
            row["kronos"] = kr
            row["in_kronos_stage"] = True
            row["category_scores"] = scoring_mod.compute_category_scores(
                row["metrics"], min_dollar_volume=min_avg_dollar_volume, kronos_result=kr,
            )
            row["overall_score"], _ = scoring_mod.composite_score(row["category_scores"], weights=active_weights)

        scored.sort(key=lambda r: r["overall_score"], reverse=True)

    # ------------------------------------------------------ finalize + explain
    shortlist_n = max(preselection_count, final_count)
    rows = []
    for rank, row in enumerate(scored[:shortlist_n], start=1):
        signal = scoring_mod.classify_signal(row["overall_score"], row["category_scores"].get("risk"))
        explanation = reasons_mod.build_reasons(row["metrics"], row["category_scores"], kronos_result=row["kronos"])
        rows.append({
            "rank": rank, "ticker": row["ticker"], "price": row["price"],
            "overall_score": row["overall_score"], "category_scores": row["category_scores"],
            "signal": signal, "in_kronos_stage": row["in_kronos_stage"],
            "kronos": row["kronos"], "metrics": row["metrics"], "reasons": explanation,
        })

    quality_summary = {
        "scanned": universe_size,
        "analyzed": universe_size - len(failures) - insufficient_history_count,
        "download_failed": len(failures),
        "insufficient_history": insufficient_history_count,
        "low_liquidity": low_liquidity_count,
        "filtered_out": filtered_out_count,
        "ranked": len(scored),
    }

    return {
        "universe_size": universe_size,
        "rows": rows,
        "skipped": skipped,
        "quality_summary": quality_summary,
        "config_used": {
            "universe": universe_key, "preset": preset_key, "benchmark": benchmark,
            "min_avg_dollar_volume": min_avg_dollar_volume, "min_history_days": min_history_days,
            "lookback_days": lookback_days, "preselection_count": preselection_count,
            "final_count": final_count, "weights": active_weights, "pred_len": pred_len,
        },
        "kronos_ran": kronos_ran,
        "elapsed_seconds": round(time.time() - t0, 1),
    }
