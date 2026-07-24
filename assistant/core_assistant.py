"""
The single entry point every interface (CLI, Discord, WhatsApp, web app)
calls into. Business logic lives entirely here -- interfaces are thin
adapters that just move text in and text/charts out. See item #9's
requirement: "keep all business logic independent of Discord or WhatsApp".
"""
from . import (
    data_fetcher, indicators, forecaster, news, explain, charts, watchlist,
    fundamentals, portfolio_analysis,
)
from .data_fetcher import TickerNotFoundError
from .nlp import parse_intent
from .conversation import get_context

SPARKLINE_POINTS = 14


class StockAssistant:
    def __init__(self, pred_len=30, n_forecast_runs=1):
        self.pred_len = pred_len
        self.n_forecast_runs = n_forecast_runs

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def handle_message(self, user_id, text):
        """
        Returns a dict:
            {"text": str, "chart": plotly.graph_objects.Figure | None,
             "image_path": str | None, "data": {...}, "suggestions": [str]}
        `suggestions` are quick-reply chips the interface can render as
        tappable buttons -- always plain follow-up messages a user could
        have typed themselves, nothing interface-specific.
        """
        context = get_context(user_id)
        parsed = parse_intent(text, context=context)
        intent, tickers = parsed["intent"], parsed["tickers"]

        if parsed.get("mode") is not None:
            context.beginner_mode = parsed["mode"]

        try:
            if intent == "greeting":
                result = self._reply_greeting()
            elif intent == "watchlist_add":
                result = self._watchlist_add(user_id, tickers)
            elif intent == "watchlist_remove":
                result = self._watchlist_remove(user_id, tickers)
            elif intent == "watchlist_show":
                result = self._watchlist_show(user_id)
            elif intent == "correlation":
                result = self._correlation(user_id, tickers)
            elif intent == "backtest":
                result = self._backtest(tickers)
            elif intent == "fundamentals":
                result = self._fundamentals(tickers)
            elif intent == "earnings":
                result = self._earnings(tickers)
            elif intent == "analyst":
                result = self._analyst(tickers)
            elif intent == "set_mode":
                result = self._set_mode(context)
            elif intent == "compare":
                result = self._compare(tickers)
            elif intent == "history":
                result = self._history(tickers)
            elif intent == "news":
                result = self._news(tickers)
            elif intent == "why":
                result = self._why(context, tickers)
            elif intent == "risk":
                result = self._risk(context, tickers)
            elif intent == "forecast":
                result = self._forecast(context, tickers)
            else:
                result = self._fallback(tickers)
        except TickerNotFoundError as e:
            result = {"text": f"⚠️ {e}", "chart": None, "data": {}}
        except Exception as e:  # keep the bot alive on unexpected errors
            result = {"text": f"⚠️ Something went wrong: {e}", "chart": None, "data": {}}

        result.setdefault("suggestions", self._suggestions(intent, tickers))
        context.remember_turn(text, result["text"])
        context.save()
        return result

    # ------------------------------------------------------------------
    # Quick-reply chips
    # ------------------------------------------------------------------
    def _suggestions(self, intent, tickers):
        t = tickers[0] if tickers else None
        if intent == "forecast" and t:
            return [f"Why is {t} moving that way?", f"What risks for {t}?",
                    f"Add {t} to my watchlist", f"Backtest {t}", f"Fundamentals of {t}"]
        if intent == "why" and t:
            return [f"What risks for {t}?", f"Backtest {t}", f"Add {t} to my watchlist"]
        if intent == "risk" and t:
            return [f"Forecast {t}", f"Fundamentals of {t}"]
        if intent == "backtest" and t:
            return [f"Forecast {t}", f"Why is {t} moving that way?"]
        if intent == "fundamentals" and t:
            return [f"Earnings date for {t}", f"Analyst targets for {t}", f"Forecast {t}"]
        if intent in ("earnings", "analyst") and t:
            return [f"Forecast {t}", f"Fundamentals of {t}"]
        if intent == "compare":
            return ["Correlation matrix for my watchlist"]
        if intent == "watchlist_show":
            return ["Correlation matrix for my watchlist", "Backtest my watchlist"]
        if intent == "watchlist_add" and t:
            return ["My watchlist", f"Forecast {t}"]
        if intent == "greeting":
            return ["Forecast AAPL", "My watchlist", "Compare NVDA and AMD"]
        return []

    def _sparkline(self, hist_df):
        if hist_df is None or hist_df.empty:
            return []
        return [round(float(x), 2) for x in hist_df["close"].tail(SPARKLINE_POINTS).tolist()]

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------
    def _reply_greeting(self):
        msg = (
            "Hi! I'm your Kronos AI stock assistant. Try things like:\n"
            "- \"Forecast AAPL\" or \"Predict Tesla for 14 days\"\n"
            "- \"Compare NVDA and AMD\"\n"
            "- \"Why is Apple expected to decline?\"\n"
            "- \"What risks should I watch for Bitcoin?\"\n"
            "- \"Fundamentals of AAPL\" / \"Analyst targets for TSLA\" / \"When does MSFT report earnings\"\n"
            "- \"Add TSLA to my watchlist\" / \"My watchlist\" / \"Correlation matrix\"\n"
            "- \"Backtest AAPL\" -- quick walk-forward accuracy + trading check\n"
            "- Say \"beginner mode\" or \"advanced mode\" any time to change how I explain things."
        )
        return {"text": msg, "chart": None, "data": {}}

    def _set_mode(self, context):
        mode = "beginner" if context.beginner_mode else "advanced"
        return {"text": f"Got it -- I'll explain things in {mode} mode from now on.",
                "chart": None, "data": {"beginner_mode": context.beginner_mode}}

    def _backtest(self, tickers):
        if not tickers:
            return {"text": "Which ticker should I backtest? e.g. \"Backtest AAPL\"",
                     "chart": None, "data": {}}
        ticker = tickers[0]
        # Imported lazily -- backtesting/ pulls in scipy/statsmodels, which
        # only need to load if this command is actually used.
        from backtesting.runner import quick_backtest
        result = quick_backtest(ticker)
        return {"text": result["text"], "chart": None,
                "image_path": result.get("image_path"),
                "data": {"ticker": ticker, "portfolio_metrics": result.get("portfolio_metrics")}}

    def _forecast(self, context, tickers):
        if not tickers:
            return {"text": "Which ticker would you like me to forecast? e.g. \"Forecast AAPL\"",
                     "chart": None, "data": {}}

        ticker = tickers[0]
        hist_df = data_fetcher.fetch_history(ticker)
        ind_df = indicators.compute_indicators(hist_df)
        fc = forecaster.run_forecast(hist_df, pred_len=self.pred_len, n_runs=self.n_forecast_runs)
        news_items, news_summary = news.get_news(ticker)
        earnings_warning = fundamentals.earnings_within_horizon(ticker, self.pred_len)
        explanation = explain.build_explanation(
            ticker, ind_df, fc, news_summary,
            beginner=context.beginner_mode, earnings_warning=earnings_warning,
        )
        fig = charts.build_forecast_chart(ticker, hist_df, ind_df, fc, news_items)
        image_path = charts.build_forecast_png(ticker, hist_df, fc)

        context.update_forecast(
            [ticker],
            {"pct_change": explanation["pct_change"], "trend": explanation["trend"]},
            explanation["text"],
        )

        return {"text": explanation["text"], "chart": fig, "image_path": image_path, "data": {
            "ticker": ticker, "forecast": fc["pred_df"].to_dict(orient="list"),
            "sparkline": self._sparkline(hist_df),
        }}

    def _compare(self, tickers):
        if len(tickers) < 2:
            return {"text": "Give me two or more tickers to compare, e.g. \"Compare NVDA and AMD\".",
                     "chart": None, "data": {}}
        dfs, failed = data_fetcher.fetch_multi(tickers)
        if failed:
            note = f" (couldn't find data for: {', '.join(failed)})"
        else:
            note = ""
        if len(dfs) < 2:
            return {"text": f"I need at least two valid tickers to compare.{note}", "chart": None, "data": {}}

        fig = charts.build_comparison_chart(dfs)
        image_path = charts.build_comparison_png(dfs)
        summaries = []
        for t, df in dfs.items():
            pct = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100
            summaries.append(f"{t}: {pct:+.2f}% over the period")
        text = "Relative performance -- " + "; ".join(summaries) + note
        return {"text": text, "chart": fig, "image_path": image_path, "data": {"tickers": list(dfs.keys())}}

    def _history(self, tickers):
        if not tickers:
            return {"text": "Which ticker's history would you like to see?", "chart": None, "data": {}}
        ticker = tickers[0]
        hist_df = data_fetcher.fetch_history(ticker)
        ind_df = indicators.compute_indicators(hist_df)
        fc = forecaster.run_forecast(hist_df, pred_len=1, n_runs=1)  # minimal, chart focuses on history
        fig = charts.build_forecast_chart(ticker, hist_df, ind_df, fc)
        image_path = charts.build_forecast_png(ticker, hist_df, fc)
        return {"text": f"Here's {ticker}'s recent price history.", "chart": fig,
                "image_path": image_path, "data": {"ticker": ticker, "sparkline": self._sparkline(hist_df)}}

    def _news(self, tickers):
        if not tickers:
            return {"text": "Which ticker's news would you like?", "chart": None, "data": {}}
        ticker = tickers[0]
        items, summary = news.get_news(ticker)
        if not items:
            return {"text": f"No recent news found for {ticker}.", "chart": None, "data": {}}
        lines = [f"Recent news for {ticker} ({summary['label']}):"]
        for item in items[:5]:
            lines.append(f"- [{item['sentiment_label']}] {item['title']} ({item['publisher']})")
        return {"text": "\n".join(lines), "chart": None, "data": {"news": items}}

    def _why(self, context, tickers):
        ticker = tickers[0] if tickers else (context.last_tickers[0] if context.last_tickers else None)
        if not ticker:
            return {"text": "Why about which ticker? Ask me to forecast one first, e.g. \"Forecast TSLA\".",
                     "chart": None, "data": {}}
        hist_df = data_fetcher.fetch_history(ticker)
        ind_df = indicators.compute_indicators(hist_df)
        fc = forecaster.run_forecast(hist_df, pred_len=self.pred_len, n_runs=self.n_forecast_runs)
        news_items, news_summary = news.get_news(ticker)
        earnings_warning = fundamentals.earnings_within_horizon(ticker, self.pred_len)
        explanation = explain.build_explanation(
            ticker, ind_df, fc, news_summary,
            beginner=context.beginner_mode, earnings_warning=earnings_warning,
        )
        return {"text": explanation["text"], "chart": None,
                "data": {"ticker": ticker, "sparkline": self._sparkline(hist_df)}}

    def _risk(self, context, tickers):
        if not tickers:
            return {"text": "Which ticker's risks would you like me to flag?", "chart": None, "data": {}}
        ticker = tickers[0]
        hist_df = data_fetcher.fetch_history(ticker)
        ind_df = indicators.compute_indicators(hist_df)
        _, news_summary = news.get_news(ticker)
        risks = explain.build_risk_note(ind_df, news_summary, beginner=context.beginner_mode)
        text = f"Risks to watch for {ticker}:\n" + "\n".join(f"- {r}" for r in risks)
        return {"text": text, "chart": None,
                "data": {"ticker": ticker, "risks": risks, "sparkline": self._sparkline(hist_df)}}

    def _fundamentals(self, tickers):
        if not tickers:
            return {"text": "Which ticker's fundamentals would you like?", "chart": None, "data": {}}
        ticker = tickers[0]
        data = fundamentals.get_fundamentals(ticker)
        text = fundamentals.format_fundamentals_text(data)
        return {"text": text, "chart": None, "data": {"ticker": ticker, "fundamentals": data}}

    def _earnings(self, tickers):
        if not tickers:
            return {"text": "Which ticker's earnings date would you like?", "chart": None, "data": {}}
        ticker = tickers[0]
        earnings_date = fundamentals.get_earnings_date(ticker)
        if earnings_date is None:
            text = f"No upcoming earnings date found for {ticker} (or it doesn't report earnings, e.g. an ETF/index/crypto)."
        else:
            days_out = (earnings_date - __import__("datetime").date.today()).days
            text = f"{ticker}'s next earnings report is expected around {earnings_date} ({days_out} days from now)."
        return {"text": text, "chart": None, "data": {"ticker": ticker, "earnings_date": str(earnings_date) if earnings_date else None}}

    def _analyst(self, tickers):
        if not tickers:
            return {"text": "Which ticker's analyst targets would you like?", "chart": None, "data": {}}
        ticker = tickers[0]
        data = fundamentals.get_analyst_targets(ticker)
        text = fundamentals.format_analyst_text(data)
        return {"text": text, "chart": None, "data": {"ticker": ticker, "analyst": data}}

    def _correlation(self, user_id, tickers):
        wl = tickers if len(tickers) >= 2 else watchlist.get(user_id)
        if len(wl) < 2:
            return {"text": "I need at least two tickers to compute a correlation matrix -- "
                             "add more to your watchlist or name two or more tickers directly.",
                     "chart": None, "data": {}}
        corr_df, failed = portfolio_analysis.compute_correlation_matrix(wl)
        if corr_df is None:
            return {"text": "Couldn't compute correlations -- not enough overlapping valid history.",
                     "chart": None, "data": {}}
        text = portfolio_analysis.format_correlation_text(corr_df)
        if failed:
            text += f"\n(couldn't fetch: {', '.join(failed)})"
        image_path = portfolio_analysis.build_correlation_heatmap(corr_df)
        return {"text": text, "chart": None, "image_path": image_path, "data": {"tickers": wl}}

    def _watchlist_add(self, user_id, tickers):
        if not tickers:
            return {"text": "Which ticker should I add to your watchlist?", "chart": None, "data": {}}
        lst = None
        for t in tickers:
            lst = watchlist.add(user_id, t)
        return {"text": f"Added {', '.join(tickers)} to your watchlist. Current list: {', '.join(lst)}",
                "chart": None, "data": {"watchlist": lst}}

    def _watchlist_remove(self, user_id, tickers):
        if not tickers:
            return {"text": "Which ticker should I remove from your watchlist?", "chart": None, "data": {}}
        lst = None
        for t in tickers:
            lst = watchlist.remove(user_id, t)
        return {"text": f"Removed {', '.join(tickers)}. Current list: {', '.join(lst) if lst else '(empty)'}",
                "chart": None, "data": {"watchlist": lst}}

    def _watchlist_show(self, user_id):
        lst = watchlist.get(user_id)
        if not lst:
            return {"text": "Your watchlist is empty. Say \"add AAPL to my watchlist\" to start one.",
                     "chart": None, "data": {"watchlist": []}}
        return {"text": f"Your watchlist: {', '.join(lst)}", "chart": None, "data": {"watchlist": lst}}

    def _fallback(self, tickers):
        if tickers:
            return self._forecast(get_context("_scratch"), tickers)
        return {"text": "I didn't quite catch that. Try \"Forecast AAPL\", \"Compare NVDA and AMD\", "
                         "or \"My watchlist\".", "chart": None, "data": {}}
