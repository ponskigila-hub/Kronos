"""Grid/random search helpers for Kronos forecast hyperparameters."""
import itertools
import math
import random

from .kronos_adapter import make_kronos_predict_fn
from .walk_forward import WalkForwardValidator
from .metrics import compute_all_metrics


def _sort_records(records, score_metric, minimize):
    def key(record):
        try:
            score = float(record[score_metric])
        except (TypeError, ValueError, KeyError):
            score = float("nan")
        if not math.isfinite(score):
            return (1, 0.0)
        return (0, score if minimize else -score)
    return sorted(records, key=key)


def _evaluate_params(df, params, horizons, window_type, min_train_size,
                      step_size, max_windows, score_metric):
    predict_fn = make_kronos_predict_fn(
        lookback=params.get("lookback"),
        T=params.get("T", 1.0),
        top_p=params.get("top_p", 0.9),
        n_runs=params.get("n_runs", 1),
    )
    validator = WalkForwardValidator(
        window_type=window_type, min_train_size=min_train_size,
        step_size=step_size, horizons=horizons, max_windows=max_windows,
    )
    results = validator.run(df, predict_fn, verbose=False)
    scores = []
    for hdf in results.values():
        if hdf.empty:
            continue
        value = compute_all_metrics(hdf).get(score_metric)
        if value is not None and math.isfinite(float(value)):
            scores.append(float(value))
    return (sum(scores) / len(scores) if scores else float("nan")), results


def grid_search(df, param_grid, horizons=(5, 14, 30), window_type="expanding",
                 min_train_size=252, step_size=30, max_windows=5,
                 score_metric="return_rmse", minimize=True):
    """Exhaustively evaluate combinations; keep a final untouched period separately."""
    keys = list(param_grid.keys())
    combos = list(itertools.product(*param_grid.values()))
    print(f"[grid_search] evaluating {len(combos)} combinations "
          f"x {max_windows or 'all'} windows each -- this calls Kronos "
          f"predict() {len(combos) * (max_windows or 1) * len(horizons)}+ times.")
    records = []
    for combo in combos:
        params = dict(zip(keys, combo))
        score, _ = _evaluate_params(df, params, horizons, window_type,
                                     min_train_size, step_size, max_windows, score_metric)
        records.append({**params, score_metric: score})
        print(f"  {params} -> {score_metric}={score:.4f}" if math.isfinite(score)
              else f"  {params} -> {score_metric}=NaN")
    return _sort_records(records, score_metric, minimize)


def random_search(df, param_distributions, n_iter=10, horizons=(5, 14, 30),
                   window_type="expanding", min_train_size=252, step_size=30,
                   max_windows=5, score_metric="return_rmse", minimize=True, seed=42):
    """Randomly sample combinations from supplied lists; this is not final validation."""
    rng = random.Random(seed)
    keys = list(param_distributions.keys())
    print(f"[random_search] evaluating {n_iter} random combinations "
          f"x {max_windows or 'all'} windows each.")
    records = []
    for i in range(n_iter):
        params = {k: rng.choice(v) for k, v in param_distributions.items()}
        score, _ = _evaluate_params(df, params, horizons, window_type,
                                     min_train_size, step_size, max_windows, score_metric)
        records.append({**params, score_metric: score})
        print(f"  [{i+1}/{n_iter}] {params} -> {score_metric}={score:.4f}" if math.isfinite(score)
              else f"  [{i+1}/{n_iter}] {params} -> {score_metric}=NaN")
    return _sort_records(records, score_metric, minimize)


def bayesian_search(df, param_space, n_calls=15, **kwargs):
    """Optional Bayesian search extension point (requires scikit-optimize)."""
    try:
        import skopt  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "bayesian_search requires scikit-optimize: pip install scikit-optimize. "
            "grid_search() and random_search() work without it."
        ) from e
    raise NotImplementedError(
        "Bayesian optimization remains an extension point. Wrap _evaluate_params() "
        "as the objective passed to skopt.gp_minimize() over your chosen dimensions."
    )
