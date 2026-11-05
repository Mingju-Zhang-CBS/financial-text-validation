"""Close-to-close cohort ledger; transaction costs use full one-way notional."""
import numpy as np
import pandas as pd


def backtest(predictions, prices, cost_bps=0, borrow_bps=0, delay=0, holding=5):
    returns = prices.pivot(index="date", columns="permno", values="total_return").sort_index()
    if predictions.empty:
        raise ValueError("Empty prediction ledger")
    returns = returns.loc[returns.index >= predictions.date.min()]
    calendar = returns.index
    targets = np.zeros(returns.shape, dtype=float)
    for date, group in predictions.groupby("date"):
        ordered = group.sort_values(["B2", "permno"])
        count = max(1, int(np.floor(len(ordered) * .1)))
        if len(ordered) < 2 * count:
            continue
        start = calendar.get_indexer([date])[0] + 1 + delay
        if start <= 0 or start + holding >= len(calendar):
            continue
        weights = np.zeros(len(returns.columns), dtype=float)
        longs = returns.columns.get_indexer(ordered.tail(count).permno)
        shorts = returns.columns.get_indexer(ordered.head(count).permno)
        if min(longs.min(), shorts.min()) < 0:
            raise ValueError("Prediction security absent from return panel")
        weights[longs] = 1 / count / holding
        weights[shorts] = -1 / count / holding
        targets[start:start + holding] += weights
    previous = np.zeros(len(returns.columns), dtype=float)
    return_values = returns.to_numpy(dtype=float)
    rows = []
    for position, date in enumerate(calendar):
        realized = return_values[position]
        if np.isnan(realized[previous != 0]).any():
            raise ValueError("Missing held-security return; resolve delisting before backtest")
        realized = np.nan_to_num(realized)
        gross = float(previous @ realized)
        short = float(-np.minimum(previous, 0).sum())
        borrow = short * borrow_bps / 10000 / 252
        equity = 1 + gross - borrow
        if equity <= 0:
            raise ValueError("Portfolio equity exhausted")
        drifted = previous * (1 + realized) / equity
        desired = targets[position]
        rate = cost_bps / 10000
        cost = 0.0
        for _ in range(100):
            updated = rate * float(np.abs(desired * (1 - cost) - drifted).sum())
            if abs(updated - cost) < 1e-14:
                cost = updated
                break
            cost = updated
        traded = float(np.abs(desired * (1 - cost) - drifted).sum())
        net = equity * (1 - cost) - 1
        rows.append({"date": date, "gross": gross, "borrow": borrow, "one_way_turnover": traded,
                     "trading_cost": equity * cost, "net": net,
                     "gross_exposure": float(np.abs(desired).sum()), "net_exposure": float(desired.sum())})
        previous = desired.copy()
    return pd.DataFrame(rows)
