"""Run synthetic engineering verification; never represents RavenPack evidence."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .experiment import run_models
from .panel import aggregate_news, build_panel
from .portfolio import backtest


def synthetic_inputs():
    generator = np.random.default_rng(20261105)
    dates = pd.bdate_range("2009-10-01", "2026-02-10")
    market = generator.normal(0, .008, len(dates))
    prices, news = [], []
    for permno in range(10):
        total = .6 * market + generator.normal(0, .015, len(dates))
        prices.append(pd.DataFrame({"permno": permno, "date": dates, "total_return": total,
                                    "market_return": market, "close": 30.0, "market_cap": 1e9 * (permno + 1),
                                    "dollar_volume": 2e6, "share_code": 10, "exchange": 1}))
        for position in range(0, len(dates), 5):
            timestamp = dates[position].tz_localize("America/New_York") + pd.Timedelta(hours=18)
            news.append({"article_id": f"synthetic-{permno}-{position}", "entity_id": str(permno),
                         "permno": permno, "published_at": timestamp, "vendor_available_at": timestamp,
                         "sentiment": float(generator.uniform(-1, 1)), "novelty": float(generator.uniform(0, 1)),
                         "event_type": ["earnings", "other"][position % 2]})
    return pd.concat(prices, ignore_index=True), pd.DataFrame(news)


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    protocol_path = Path(__file__).with_name("protocol.json")
    protocol = json.loads(protocol_path.read_text())
    prices, news = synthetic_inputs()
    daily = aggregate_news(news, prices.date.unique())
    panel = build_panel(prices, daily)
    predictions, metrics, selection, contrasts, ic = run_models(panel, protocol)
    metrics.to_csv(output / "synthetic_metrics.csv", index=False)
    ic.to_csv(output / "synthetic_daily_ic.csv", index=False)
    (output / "selection.json").write_text(json.dumps(selection, indent=2))
    (output / "contrasts.json").write_text(json.dumps(contrasts, indent=2))
    primary = predictions.loc[predictions.horizon.eq(5) & predictions.target_type.eq("adjusted")]
    costs = []
    for delay in protocol["portfolio"]["extra_delay_sessions"]:
        for rate in protocol["portfolio"]["one_way_cost_bps"]:
            for borrow in protocol["portfolio"]["annual_borrow_bps"]:
                ledger = backtest(primary, prices, rate, borrow, delay)
                ledger.to_csv(output / f"synthetic_ledger_delay{delay}_cost{rate}_borrow{borrow}.csv", index=False)
                active = ledger.loc[ledger.date.ge(primary.date.min())]
                costs.append({"delay": delay, "cost_bps": rate, "borrow_bps": borrow,
                              "total_net": float((1 + active.net).prod() - 1)})
    pd.DataFrame(costs).to_csv(output / "synthetic_cost_scenarios.csv", index=False)
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent,
                                         stderr=subprocess.DEVNULL, text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        commit = None
    package = Path(__file__).parent
    fingerprint = lambda content: hashlib.sha256(content).hexdigest()
    manifest = {"run_id": output.name, "created_utc": datetime.now(timezone.utc).isoformat(),
                "status": "synthetic-engineering-check-completed", "empirical_study_executed": False,
                "code_commit": commit, "code_sha256": {path.name: fingerprint(path.read_bytes()) for path in sorted(package.glob('*.py'))},
                "protocol_sha256": fingerprint(protocol_path.read_bytes()), "python": platform.python_version(),
                "dependencies": {name: importlib.metadata.version(name) for name in ["numpy", "pandas", "scikit-learn", "scipy"]},
                "inputs": {"prices": fingerprint(prices.to_csv(index=False).encode()), "news": fingerprint(news.to_csv(index=False).encode())},
                "outputs": {path.name: fingerprint(path.read_bytes()) for path in output.iterdir() if path.is_file()}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print("Synthetic verification completed. No empirical news result was generated.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="store_true", required=True)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        run(arguments.output)
    except BaseException as error:
        if arguments.output.exists() and not (arguments.output / "manifest.json").exists():
            (arguments.output / "failed.json").write_text(json.dumps({"status": "failed", "failure_class": type(error).__name__,
                "created_utc": datetime.now(timezone.utc).isoformat(), "empirical_study_executed": False}, indent=2))
        raise
