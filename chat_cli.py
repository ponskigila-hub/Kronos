#!/usr/bin/env python
"""
Local terminal chat for testing the assistant without any bot platform.

Usage:
    python chat_cli.py

Type things like:
    forecast AAPL
    compare NVDA and AMD
    why is tesla expected to decline
    add btc to my watchlist
    my watchlist
    backtest AAPL
    quit
"""
import platform
import subprocess
import sys

from assistant.core_assistant import StockAssistant

BANNER = """
==============================================
 Kronos AI Stock Assistant -- local CLI mode
 Type 'quit' or 'exit' to leave.
==============================================
"""


def _try_open(path):
    """Best-effort: pop the PNG open in the OS's default image viewer, the
    same experience as the original scripts' plt.show(). Silently does
    nothing if that's not possible (e.g. a headless server)."""
    try:
        system = platform.system()
        if system == "Darwin":
            subprocess.run(["open", path], check=False)
        elif system == "Windows":
            import os
            os.startfile(path)  # noqa
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception:
        pass  # not fatal -- the file is still saved and the path is printed


def main():
    print(BANNER)
    bot = StockAssistant()
    user_id = "cli-user"

    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye!")
            break

        if text.lower() in {"quit", "exit"}:
            print("bye!")
            break
        if not text:
            continue

        result = bot.handle_message(user_id, text)
        print(f"\nbot> {result['text']}\n")

        if result.get("image_path"):
            print(f"📊 Chart image saved to: {result['image_path']}")
            _try_open(result["image_path"])

        if result.get("chart") is not None:
            out_path = "last_chart.html"
            result["chart"].write_html(out_path)
            print(f"🌐 Interactive version saved to {out_path} -- open it in a browser.\n")


if __name__ == "__main__":
    main()

