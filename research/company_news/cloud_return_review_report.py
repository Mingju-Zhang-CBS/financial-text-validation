"""Consolidate private missing-return investigations without exporting data."""
from pathlib import Path
import datetime
import hashlib
import importlib.util
import json
import re
import numpy as np
import pandas as pd


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(study):
    root=study.OUT;output=root/'final_report_return_review_20261106'
    output.mkdir(exist_ok=False)
    spec=importlib.util.spec_from_file_location('return_report_tables',Path(__file__).with_name('cloud_finalize.py'))
    formatting=importlib.util.module_from_spec(spec);spec.loader.exec_module(formatting)
    versions=['implementation_replay_v3','implementation_replay_v3_sources','implementation_replay_v3_local','terminal_sensitivity_v4_checked']
    tables=[];references={};checks=[];input_hashes={}
    for version in versions:
        directory=root/version;manifest=json.loads((directory/'manifest.json').read_text())
        for name,expected in manifest['outputs'].items():
            if sha(directory/name)!=expected:raise ValueError('Changed implementation output')
        input_hashes[version]=sha(directory/'manifest.json')
        filename='all_108_scenarios_PRIVATE.csv' if version=='terminal_sensitivity_v4_checked' else 'all_72_scenarios_PRIVATE.csv'
        results=pd.read_csv(directory/filename);results.insert(0,'version',version);tables.append(results)
        references[version]=json.loads((directory/'reference_diagnostics_PRIVATE.json').read_text())
        for row in results.itertuples(index=False):
            if not row.status.startswith('computed'):continue
            path=directory/f'{row.mode}_delay{row.delay}_cost{row.one_way_bps}_borrow{row.borrow_bps}_PRIVATE.csv'
            ledger=pd.read_csv(path,parse_dates=['date'])
            if not np.allclose(ledger.net,ledger.gross-ledger.borrow-ledger.trading_cost,atol=1e-10):raise ValueError('P&L reconciliation failure')
            if not np.isclose((1+ledger.net).prod()-1,row.total_net,atol=1e-9):raise ValueError('Ledger/table mismatch')
            if not ledger.unquoted_traded_notional.abs().le(1e-9).all():raise ValueError('Unquoted execution')
            checks.append({'version':version,'mode':row.mode,'delay':row.delay,'cost':row.one_way_bps,'borrow':row.borrow_bps,'ledger_reconciles':True,'no_unquoted_execution':True})
    all_results=pd.concat(tables,ignore_index=True)
    all_results.to_csv(output/'all_324_followup_attempts_PRIVATE.csv',index=False)
    pd.DataFrame(checks).to_csv(output/'mechanical_checks_PRIVATE.csv',index=False)
    terminal=root/'terminal_sensitivity_v4_checked'
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    figure,axes=plt.subplots(2,2,figsize=(13,8))
    for multiplier in [.5,1.,1.5]:
        mode=f'final-quote-multiplier-{multiplier:g}'
        path=terminal/f'{mode}_delay0_cost10_borrow100_PRIVATE.csv'
        label=f'Final quote x{multiplier:g}; assumed settlement'
        if path.exists():
            ledger=pd.read_csv(path,parse_dates=['date']);nav=(1+ledger.net).cumprod()
            axes[0,0].plot(ledger.date,nav,label=label)
            peak=np.maximum.accumulate(np.r_[1.,nav.to_numpy()])[1:]
            axes[0,1].plot(ledger.date,nav/peak-1,label=label)
        selected=all_results.loc[all_results.version.eq('terminal_sensitivity_v4_checked')&all_results['mode'].eq(mode)
            &all_results.borrow_bps.eq(100)&all_results.status.str.startswith('computed')]
        costs=selected.loc[selected.delay.eq(0)].sort_values('one_way_bps')
        delays=selected.loc[selected.one_way_bps.eq(10)].sort_values('delay')
        if not costs.empty:axes[1,0].plot(costs.one_way_bps,costs.total_net,marker='o',label=label)
        if not delays.empty:axes[1,1].plot(delays.delay,delays.total_net,marker='o',label=label)
    for axis in axes.flat:
        if axis.lines:axis.legend(fontsize=7)
        else:axis.text(.5,.5,'Conditional reference not estimable',transform=axis.transAxes,ha='center')
    axes[0,0].set_title('Conditional equity: costs 10 bps, borrow 100 bps')
    axes[0,1].set_title('Conditional drawdown')
    axes[1,0].set_title('One-way cost sensitivity; extra delay 0')
    axes[1,0].set_xlabel('bps');axes[1,0].set_ylabel('Cumulative net return')
    axes[1,1].set_title('Additional execution delay; costs 10 bps')
    axes[1,1].set_xlabel('Trading sessions');axes[1,1].set_ylabel('Cumulative net return')
    figure.suptitle('Retrospective terminal-value sensitivities; no observed cash-settlement claim')
    figure.tight_layout();figure.savefig(output/'implementation_sensitivities_PRIVATE.png',dpi=160);plt.close(figure)
    last_reference=references['terminal_sensitivity_v4_checked']
    conditional_complete=all(item['status']=='computed-conditional-settlement' for item in last_reference.values())
    verdict=('All fixed terminal-price reference sensitivities have complete accounting ledgers under explicit settlement assumptions.' if conditional_complete else
        'Some fixed terminal-price reference sensitivities remain unestimable. A complete unconditional strategy result is unavailable.')
    review=['# Company News: Missing Returns and Implementation Review','',
        '**Private licensed-data report. Do not publish or load the empirical contents into an LLM.**','',
        '## Research judgment','',verdict,'',
        'The observed-only primary reference and earlier certified-stale variants remain failed attempts. Neither a final quote nor a mechanically reconciled ledger proves cash realization, borrow availability or executable alpha. Terminal quote multipliers are operational assumptions, not confidence bounds. The report keeps all failures and all conditional outcomes; it does not choose a favorable implementation.','',
        '## Missing-return investigation','',
        'A missing CRSP return was traced using return-missing/duration flags, previous-price dates, regular-session execution closes and trading status. Annual CIZ, legacy CRSP and historically CCM-linked Compustat daily total-return indices were queried. Fixed-priority repairs require exact return endpoints, currency/factors, observed overlap and complete recovery consistency. A separate latest-20-prior-overlap amendment remains distinct from the initial all-overlap gate. No source replaces an execution quote.','',
        'The remaining fixed-reference failure was investigated in quarterly/annual delisting events, legacy delisting records and raw return components. A qualifying final-price quote can anchor a conditional terminal valuation only after the exact last-trading price/date reconciles and no intervening distribution is present. An unavailable cash entitlement is not filled with zero, -100% or a generic academic delisting penalty.','',
        '## Actual source audits (private)','']
    for relative in ['daily_return_review_v3/first_gap_diagnosis_PRIVATE.csv','source_reconciliation_v3/provider_audit_PRIVATE.csv','source_reconciliation_v3_local/provider_audit_PRIVATE.csv','terminal_sensitivity_v4_checked/final-quote-multiplier-1_terminal_audit_PRIVATE.csv']:
        path=root/relative
        if path.exists():review.extend([f'### {relative}','',formatting.table(pd.read_csv(path)),''])
    review.extend(['## Implementation accounting and assumptions','',
        'Same frozen five-session adjusted B2 predictions and original universe. Five overlapping equal-capital cohorts; end-of-day information, next-session close entry plus 0/1/2 extra sessions. No inactive/unquoted orders. Locked economic claims consume their direction budget; borrowing continues until the assumed terminal settlement. Certified closed MP gaps may use stale marks, with the complete vendor return at recovery. These are timing conventions rather than observed zero economic returns.','',
        'The terminal experiment freezes price multipliers 0.5/1/1.5 before P&L, with one-way costs 0/5/10/20 bps and annual borrowing 0/100/300 bps. The 2026 buffer only completes 2025 holdings. Funding, locate availability, impact, actual settlement delay, corporate-action uncertainty and quote bid/ask execution are not established.','',
        '![Private implementation sensitivities](implementation_sensitivities_PRIVATE.png)','',
        '## All fixed reference diagnostics','',
        '```json',json.dumps(references,indent=2),'```','',
        'Intervals are date-block retrospective estimates conditional on each valuation convention; market beta is descriptive, not a factor-neutral alpha claim.','',
        '## All 324 follow-up attempts','',formatting.table(all_results),'',
        'The original 36 v2 implementation attempts remain in the original report below. No historical attempt is overwritten, omitted or reclassified as observed after a sensitivity succeeds.','',
        '## Mechanical validation','',formatting.table(pd.DataFrame(checks)),'',
        'Each computed ledger reconciles gross return, borrowing, one-way transaction cost and net; its cumulative return matches the scenario table and all unquoted traded amounts are zero. The engine additionally checks security contribution reconciliation, immutable prepared arrays and complete ending liquidation under the stated settlement assumptions.','',
        '## Original full statistical study (preserved)',''])
    original=(root/'final_report'/'REPORT_PRIVATE.md').read_text()
    original=re.sub(r'\]\((?!https?:|#|/)([^)]+)\)',lambda m:'](../final_report/'+m.group(1)+')',original)
    review.append(original)
    (output/'REPORT_PRIVATE.md').write_text('\n\n'.join(review),encoding='utf-8')
    (output/'input_fingerprints.json').write_text(json.dumps({'recorded_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'manifests':input_hashes,'original_report':sha(root/'final_report'/'REPORT_PRIVATE.md')},indent=2))
    (output/'manifest.json').write_text(json.dumps({'status':'integrated-return-review-report-verified','conditional_reference_ledgers_complete':conditional_complete,
        'observed_only_reference_validated':False,'observed_cash_settlement_validated':False,'human_economic_review_pending':True,
        'commercial_output_publication_authorized':False,'source_sha256':sha(__file__),
        'outputs':{p.name:sha(p) for p in output.iterdir() if p.is_file()}},indent=2))
    print('INTEGRATED_RETURN_REVIEW_COMPLETED',flush=True)
