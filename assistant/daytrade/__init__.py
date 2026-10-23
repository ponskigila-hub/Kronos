"""
Day-trade toolkit (vendored pure-Python tools).

Originally from the open-source day-trader-skill pack (MIT) — chart scanner,
entry timer, exit planner, risk/size helpers. Integrated into Kronos as a
first-class web tab with **no Claude / Claude Code dependency**. All tools
read free public data (Yahoo charts, etc.) and never place orders.
"""
from . import service

__all__ = ["service"]
