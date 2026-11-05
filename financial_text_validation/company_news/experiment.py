"""Transparent ablations and paired date-block uncertainty."""
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .panel import split_masks


BASE = ["return_1", "return_5", "return_20", "volatility_20", "log_cap", "log_liquidity", "past_coverage"]
SENTIMENT = ["sentiment", "has_news", "sentiment_missing"]
NOVELTY = ["novelty", "sentiment_novelty", "sentiment_coverage"]


def model_for(name, alpha):
    numeric = BASE + (SENTIMENT if name != "B0" else []) + (NOVELTY if name == "B2" else [])
    transforms = [("numeric", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), numeric)]
    if name == "B2":
        transforms.append(("event", OneHotEncoder(handle_unknown="ignore", sparse_output=False), ["event_type"]))
    return Pipeline([("features", ColumnTransformer(transforms)), ("ridge", Ridge(alpha=alpha))])


def block_interval(values, replications=2000, date_block_length=20, seed=20261105):
    values = np.asarray(values, dtype=float)
    if len(values) < 2:
        raise ValueError("At least two dates required")
    generator = np.random.default_rng(seed)
    block_length = min(date_block_length, len(values))
    draws = []
    for _ in range(replications):
        starts = generator.integers(0, len(values) - block_length + 1, size=int(np.ceil(len(values) / block_length)))
        indices = np.concatenate([np.arange(start, start + block_length) for start in starts])[:len(values)]
        draws.append(values[indices].mean())
    return np.quantile(draws, [.025, .975]).tolist()


def run_models(panel, protocol):
    predictions, metrics, selections = [], [], []
    for horizon in protocol["horizons"]:
        for target in ["raw", "adjusted"]:
            label = f"{target}_{horizon}"
            common = panel[BASE + [label]].notna().all(axis=1)
            masks = split_masks(panel, horizon, protocol["splits"])
            train = panel.loc[masks["train"] & common]
            validation = panel.loc[masks["validation"] & common]
            confirmation = panel.loc[masks["confirmation"] & common]
            if min(len(train), len(validation), len(confirmation)) == 0:
                raise ValueError("Empty split; never silently change research period")
            aligned = confirmation[["date", "permno", label]].rename(columns={label: "target"}).copy()
            aligned["horizon"], aligned["target_type"] = horizon, target
            for name in protocol["models"]:
                scores = []
                for alpha in protocol["ridge_alpha_grid"]:
                    candidate = model_for(name, alpha).fit(train, train[label])
                    score = float(np.mean((validation[label] - candidate.predict(validation)) ** 2))
                    scores.append((score, alpha))
                _, alpha = min(scores)
                selections.append({"horizon": horizon, "target": target, "model": name,
                                   "alpha": alpha, "development_scores": scores})
                eligible = panel.loc[common & panel["date"].lt(confirmation["date"].min())
                                     & panel[f"end_{horizon}"].lt(pd.Timestamp(protocol["splits"]["confirmation"][0], 1, 1))]
                eligible = eligible.loc[eligible["eligible"] & eligible["date"].ge(pd.Timestamp(protocol["splits"]["train"][0], 1, 1))]
                fitted = model_for(name, alpha).fit(eligible, eligible[label])
                aligned[name] = fitted.predict(confirmation)
                metrics.append({"horizon": horizon, "target": target, "model": name,
                                "n": len(confirmation), "mse": float(np.mean((aligned["target"] - aligned[name]) ** 2))})
            predictions.append(aligned)
    predictions = pd.concat(predictions, ignore_index=True)
    contrasts, information = [], []
    for (horizon, target), group in predictions.groupby(["horizon", "target_type"]):
        errors = group.assign(difference=(group.target - group.B0) ** 2 - (group.target - group.B2) ** 2)
        dates = errors.groupby("date")["difference"].mean()
        interval = block_interval(dates.values, **protocol["bootstrap"])
        contrasts.append({"horizon": int(horizon), "target": target,
                          "date_equal_weight_mse_improvement": float(dates.mean()), "interval_95": interval,
                          "note": "Date-equal-weight paired contrast; unadjusted interval"})
        for date, daily in group.groupby("date"):
            for name in protocol["models"]:
                information.append({"date": date, "horizon": horizon, "target": target, "model": name,
                                    "ic": daily[name].corr(daily["target"], method="spearman")})
    return predictions, pd.DataFrame(metrics), selections, contrasts, pd.DataFrame(information)
