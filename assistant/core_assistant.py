"""
The single entry point every interface (CLI, Discord, WhatsApp, or a future
web chat) calls into. Business logic lives entirely here -- interfaces are
thin adapters that just move text in and text/charts out. See item #9's
requirement: "keep all business logic independent of Discord or WhatsApp".
"""
from . import data_fetcher, indicators, forecaster, news, explain, charts, watchlist
from .data_fetcher import TickerNotFoundError
from .nlp import parse_intent
from .conversation import get_context


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
            {"text": str, "chart": plotly.graph_objects.Figure | None, "data": {...}}
        """
        context = get_context(user_id)
        parsed = parse_intent(text, context=context)
        intent, tickers = parsed["intent"], parsed["tickers"]

        try:
            if intent == "greeting":
                result = self._reply_greeting()
            elif intent == "watchlist_add":
                result = self._watchlist_add(user_id, tickers)
            elif intent == "watchlist_remove":
                result = self._watchlist_remove(user_id, tickers)
            elif intent == "watchlist_show":
                result = self._watchlist_show(user_id)
            elif intent == "backtest":
                result = self._backtest(tickers)
            elif intent == "compare":
                result = self._compare(tickers)
            elif intent == "history":
                result = self._history(tickers)
            elif intent == "news":
                result = self._news(tickers)
            elif intent == "why":
                result = self._why(context, tickers)
            elif intent == "risk":
                result = self._risk(tickers)
            elif intent == "forecast":
                result = self._forecast(context, tickers)
            else:
                result = self._fallback(tickers)
        except TickerNotFoundError as e:
            result = {"text": f"⚠️ {e}", "chart": None, "data": {}}
        except Exception as e:  # keep the bot alive on unexpected errors
            result = {"text": f"⚠️ Something went wrong: {e}", "chart": None, "data": {}}

        context.remember_turn(text, result["text"])
        context.save()
        return result

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
            "- \"Add TSLA to my watchlist\" / \"My watchlist\"\n"
            "- \"Backtest AAPL\" -- quick walk-forward accuracy + trading check"
        )
        return {"text": msg, "chart": None, "data": {}}

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
        explanation = explain.build_explanation(ticker, ind_df, fc, news_summary)
        fig = charts.build_forecast_chart(ticker, hist_df, ind_df, fc, news_items)
        image_path = charts.build_forecast_png(ticker, hist_df, fc)

        context.update_forecast(
            [ticker],
            {"pct_change": explanation["pct_change"], "trend": explanation["trend"]},
            explanation["text"],
        )

        return {"text": explanation["text"], "chart": fig, "image_path": image_path, "data": {
            "ticker": ticker, "forecast": fc["pred_df"].to_dict(orient="list"),
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
                "image_path": image_path, "data": {"ticker": ticker}}

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
        explanation = explain.build_explanation(ticker, ind_df, fc, news_summary)
        return {"text": explanation["text"], "chart": None, "data": {"ticker": ticker}}

    def _risk(self, tickers):
        if not tickers:
            return {"text": "Which ticker's risks would you like me to flag?", "chart": None, "data": {}}
        ticker = tickers[0]
        hist_df = data_fetcher.fetch_history(ticker)
        ind_df = indicators.compute_indicators(hist_df)
        _, news_summary = news.get_news(ticker)
        risks = explain.build_risk_note(ind_df, news_summary)
        text = f"Risks to watch for {ticker}:\n" + "\n".join(f"- {r}" for r in risks)
        return {"text": text, "chart": None, "data": {"ticker": ticker, "risks": risks}}

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
