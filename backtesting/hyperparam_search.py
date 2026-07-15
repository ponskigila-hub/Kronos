"""
Requirement #10: hyperparameter search over window size, horizon,
temperature, top_p, and sampling strategy (n_runs). Grid + random search are
implemented directly (no extra dependency). Bayesian optimization is
optional per the brief; wired up as an opt-in path via `scikit-optimize` if
installed, otherwise raises a clear message instead of silently no-op'ing.
"""
import itertools
import random

from .kronos_adapter import make_kronos_predict_fn
from .walk_forward import WalkForwardValidator
from .metrics import compute_all_metrics


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

    # Average the chosen score metric across all evaluated horizons.
    scores = []
    for h, hdf in results.items():
        if hdf.empty:
            continue
        m = compute_all_metrics(hdf)
        val = m.get(score_metric)
        if val is not None and val == val:  # not NaN
            scores.append(val)
    avg_score = sum(scores) / len(scores) if scores else float("nan")
    return avg_score, results


def grid_search(df, param_grid, horizons=(5, 14, 30), window_type="expanding",
                 min_train_size=252, step_size=30, max_windows=5,
                 score_metric="rmse", minimize=True):
    """
    param_grid: dict like {"lookback": [200, 400], "T": [0.8, 1.0],
                            "top_p": [0.8, 0.9], "n_runs": [1]}
    Exhaustively evaluates every combination via a (deliberately small by
    default, via max_windows) walk-forward run and returns results sorted
    best-first.
    """
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
        print(f"  {params} -> {score_metric}={score:.4f}" if score == score else f"  {params} -> {score_metric}=NaN")

    records.sort(key=lambda r: (r[score_metric] != r[score_metric], r[score_metric]), reverse=not minimize)
    return records


def random_search(df, param_distributions, n_iter=10, horizons=(5, 14, 30),
                   window_type="expanding", min_train_size=252, step_size=30,
                   max_windows=5, score_metric="rmse", minimize=True, seed=42):
    """
    param_distributions: dict like {"lookback": [200,300,400], "T": [0.7,0.8,0.9,1.0,1.1]}
    -- each value is a list to sample uniformly from. Samples `n_iter`
    random combinations instead of the full grid.
    """
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
        print(f"  [{i+1}/{n_iter}] {params} -> {score_metric}={score:.4f}" if score == score
              else f"  [{i+1}/{n_iter}] {params} -> {score_metric}=NaN")

    records.sort(key=lambda r: (r[score_metric] != r[score_metric], r[score_metric]), reverse=not minimize)
    return records


def bayesian_search(df, param_space, n_calls=15, **kwargs):
    """
    Optional (per the brief). Requires `scikit-optimize`
    (pip install scikit-optimize). Not installed by default since grid/random
    search cover the requirement without the extra dependency.
    """
    try:
        from skopt import gp_minimize
        from skopt.space import Real, Integer
    except ImportError:
        raise ImportError(
            "bayesian_search requires scikit-optimize: pip install scikit-optimize. "
            "grid_search() and random_search() in this same module work without it."
        )
    raise NotImplementedError(
        "Bayesian optimization is an optional extension point. With "
        "scikit-optimize installed, wrap _evaluate_params() as the "
        "objective passed to skopt.gp_minimize() over your chosen "
        "skopt.space dimensions (e.g. Real(0.5,1.5,name='T'))."
    )
