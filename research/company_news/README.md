# WRDS Cloud archive workflow

These independently written scripts expose the real-data engineering and evaluation interfaces. They contain no vendor observations, credentials, empirical metrics or saved models. All tests use invented inputs. The original public FOMC study remains separate.

## Required private inputs

Use only an authorized WRDS Cloud account and the audited product versions. This directory does **not** grant access or recreate the private audit automatically. Before execution supply the privately audited, date-valid `ciz_historical_links_private.parquet` (`permno`, `permco`, `valid_from`, `valid_to`, RavenPack identity fields as required by the adapter) and `ciz_market_calendar_private.parquet` (`date`, `vwretd`) under `~/company_news_research_20261105/`. Review the adapter's exact column contract. Existing private price/news caches may be reused only with recorded provenance.

Upload the required `cloud_*.py` modules and their sibling dependencies from this directory into a versioned source directory. WRDS Cloud provides its supported database connection; these scripts receive a read-only connection or an already prepared archive. Local synthetic tests additionally require PyArrow (`pip install -e ".[test,cloud]"`). An authenticated web session alone does not establish data rights or authorize export.

## Stages and quiet execution

1. `cloud_real_study.execute(db, adapter, links, market)` freezes the archive protocol and prepares 2010–2025 panels with backward/forward buffers. It refuses to overwrite an existing output directory.
2. `cloud_quality_gate.execute(study, links, market, db)` distinguishes unknown mapping/feed coverage from observed no-news and rebuilds labels using unfiltered holding-security prices. It preserves the first-stage panels and writes `panel_checked_YEAR.parquet`. The predictive module requires this checkpoint.
3. `cloud_fit_study.execute(study)` freezes development selections before confirmation scoring; retains 18 model comparisons and 36 implementation scenarios; preserves unestimable scenarios; reconciles security contributions for the fixed delay-0 / 10-bps / 100-bps-borrow reference book.
4. `cloud_diagnostics.execute(study)` produces separate explanatory firm/date estimates, all prespecified descriptive event groups, a private figure, market-exposure diagnostics and contribution reconciliation. Its manifest requires the predictive manifest.
5. `cloud_finalize.execute(study, source_commit=...)` assembles the integrated private English report and input fingerprints. This final input snapshot is explicitly recorded after execution, not misrepresented as a pre-fit cryptographic commitment.
6. If a held-return failure prevents the fixed reference book, `cloud_implementation_audit.execute(study, fitting, db)` reproduces its first failure and performs a bounded read-only source reconciliation. Private source flags support human review. It does not replace a missing return by zero, delete failed trades or change the frozen sample.

## Missing-return follow-up

The [return-review method and execution record](../../docs/company-news/RETURN_REVIEW.md) distinguishes failed observed-only references from conditional settlement accounting. All actual outputs stay private.

|Entry point|Purpose|
|---|---|
|`cloud_return_diagnosis.execute(study, fitting, db)`|Bounded source flags, duration, price dates, trading/quote metadata and source discovery. |
|`cloud_alternate_probe.execute(study, db)`|Bounded annual/legacy and historically linked Compustat total-return probe.|
|`cloud_replay_v3.execute(study, db, ...)`|Two valuation conventions, all 72 fixed cost/borrow/delay attempts; refuses unresolved held returns.|
|`cloud_source_resolution.execute(study, db)`|Fixed-priority whole-segment reconciliation; saves source/protocol fingerprints before replay.|
|`cloud_source_resolution.reconcile_cached_local(study)`|Separate past-only overlap sensitivity using verified cached candidates.|
|`cloud_unresolved_audit.execute(study, db, engine, ...)`|Reproduce the next unresolved reference value privately; return only a software remediation route.|
|`cloud_terminal_sensitivity.execute(study, db)`|Explicit final-price settlement sensitivities, all 108 attempts; no observed execution/cash-settlement claim.|
|`cloud_return_review_report.execute(study)`|Verify all run fingerprints and computed ledgers; integrate the original full report, 324 follow-up attempts and conditional plots.|

`implementation_v3.py` and `return_reconciliation.py` are sibling dependencies. Keep each deployed revision immutable. Do not rerun into an existing output directory; checkpoint names are intentionally fixed to preserve this research record. The checked terminal run uses `execute(study, db, output_name="terminal_sensitivity_v4_checked")` after preserving the original reporting failure. New source or settlement rules require a new version rather than changing an old run. The current source fixes the reference metadata merge; executed historical source hashes remain separately recorded.

Always redirect **both stdout and stderr** into a private Cloud log, including database connection setup and exceptions. The builder's ordinary human-facing progress includes sample counts. Those counts and all actual values must not be copied into an LLM interface. A status-only notebook can use this pattern:

```python
import contextlib
from pathlib import Path
from threadpoolctl import threadpool_limits

root = Path.home() / "company_news_research_20261105"
with (root / "continuation_private.log").open("a") as log:
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        with threadpool_limits(limits=1):
            fitting.execute(study)  # after the audited preparation and quality gate
print("PREDICTIVE_MANIFEST_PRESENT", (study.OUT / "evaluation/manifest.json").exists())
```

For exceptions, keep the traceback inside the private log and return only a sanitized failure class. Avoid rendering actual report tables or figures in any AI-controlled page. Human review can take place directly in the authorized Cloud environment.

## Interpretation and reproducibility limits

This is a retrospective archive design. Vendor receipt is an availability proxy; original publication/scoring-completion clocks and historical scoring vintages are not established. Filtered-feed activity does not certify complete source delivery. A historical CUSIP/date match is an engineering link, not proof of economic identity in every case. A valid terminal CIZ return followed by cash is an explicit implementation assumption.

The supplementary panel's main target is confirmation-period five-session market-adjusted return. Regressors use pre-2021 scale estimates; firm/date effects are removed iteratively. Two-way firm/date clustering and date-score HAC20 are descriptive asymptotic diagnostics. Event paths include offset 0's event-day reaction, overlapping events and all missing-path counts; they are not strategy returns. Market-only exposure does not establish broad factor neutrality or causal effects. No supplementary output selects the predictive model.

`source_provenance.json` records code fingerprints, never data fingerprints or results. The detailed supplementary specification was written without inspecting empirical outcomes; it supplements the original high-level protocol rather than claiming prior external registration. Source-code completion, synthetic tests and real-data execution are separate statuses. Dissemination of real-data aggregates, charts or conclusions still requires applicable permission and human interpretation.

```text
python -m pytest research/company_news
```

## Frozen three-model strategy comparison

`cloud_model_strategy_comparison.execute(study)` replays B0/B1/B2 with the exact saved v4 valuations and unchanged engine. Ranking inputs share every forecast company-day, including missing realized targets. It preserves all 324 model configurations and all 324 same-date pairwise comparisons, stops unresolved holdings, and requires every B2 ledger to reproduce its previous counterpart. Actual holdings may differ; portfolio-construction rules are identical.

`cloud_model_strategy_report.execute(study)` independently reconciles saved ledgers and creates the complete private English report plus a field-limited aggregate publication packet. The paired daily inferential clock is 2021–2025, while cumulative wealth retains the common liquidation buffer. This is a post-execution supplemental design with unadjusted intervals. Read the [full aggregate result and limitations](../../docs/company-news/STRATEGY_COMPARISON.md). Public configuration tables contain experiment summaries, never underlying observations, predictions, identifiers or date-level ledgers.
