"""Small, side-effect-free helpers used by the model benchmark report/tests."""
from pathlib import Path

import pandas as pd


def _load_backtest_metrics(results_dir):
    """Aggregate Kronos rows from per-ticker metrics CSVs, or return None."""
    root = Path(results_dir)
    frames = []
    tickers = []
    for path in sorted(root.glob("*/metrics_by_model_horizon.csv")):
        try:
            frame = pd.read_csv(path)
        except (OSError, pd.errors.ParserError, UnicodeDecodeError):
            continue
        if "model" not in frame.columns:
            continue
        frame = frame[frame["model"].astype(str).str.casefold() == "kronos"].copy()
        if frame.empty:
            continue
        frames.append(frame)
        tickers.append(path.parent.name)
    if not frames:
        return None

    data = pd.concat(frames, ignore_index=True)
    result = {}
    for column in data.columns:
        if column == "model":
            continue
        numeric = pd.to_numeric(data[column], errors="coerce")
        if numeric.notna().any():
            result[column] = (int(numeric.sum()) if column == "n_predictions"
                              else float(numeric.mean()))
    result["tickers_covered"] = sorted(set(tickers))
    return result


def _to_markdown_table(frame):
    """Render a compact Markdown table without optional tabulate dependency."""
    columns = [str(column) for column in frame.columns]
    rows = ["| " + " | ".join(columns) + " |",
            "|" + "|".join("---" for _ in columns) + "|"]
    for values in frame.itertuples(index=False, name=None):
        cells = []
        for value in values:
            if pd.isna(value):
                cells.append("")
            elif isinstance(value, float):
                cells.append(f"{value:g}")
            else:
                cells.append(str(value))
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)
