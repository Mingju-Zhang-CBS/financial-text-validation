"""Integrated private v3 report and mechanical validation, no empirical export."""
from pathlib import Path
import datetime
import hashlib
import importlib.util
import json
import numpy as np
import pandas as pd


def execute(study, replay_name='implementation_replay_v3', output_name='final_report_v3', source_resolution_name='source_reconciliation_v3'):
    root=study.OUT;replay=root/replay_name
    assert (replay/'manifest.json').exists(), 'Replay must finish before reporting'
    output=root/output_name
    if output.resolve().parent!=root.resolve() or replay.resolve().parent!=root.resolve():
        raise ValueError('Report paths must remain in the private study archive')
    output.mkdir(exist_ok=False)
    spec=importlib.util.spec_from_file_location('v3_table',Path(__file__).with_name('cloud_finalize.py'))
    formatting=importlib.util.module_from_spec(spec);spec.loader.exec_module(formatting)
    meta=json.loads((replay/'manifest.json').read_text())
    for name,expected in meta['outputs'].items():
        with (replay/name).open('rb') as stream:
            assert hashlib.file_digest(stream,'sha256').hexdigest()==expected
    results=pd.read_csv(replay/'all_72_scenarios_PRIVATE.csv')
    assert len(results)==72
    checks=[]
    for row in results.itertuples(index=False):
        if row.status!='computed':
            continue
        name=f'{row.mode}_delay{row.delay}_cost{row.one_way_bps}_borrow{row.borrow_bps}_PRIVATE.csv'
        ledger=pd.read_csv(replay/name,parse_dates=['date'])
        if not np.allclose(ledger.net,ledger.gross-ledger.borrow-ledger.trading_cost,atol=1e-10):
            raise ValueError('Gross, borrow, costs and net P&L do not reconcile')
        if ledger.unquoted_traded_notional.abs().max()>1e-9:
            raise ValueError('Unquoted trades were executed')
        if not np.isclose((1+ledger.net).prod()-1,row.total_net,atol=1e-9):
            raise ValueError('Scenario table and ledger disagree')
        checks.append({'mode':row.mode,'delay':row.delay,'one_way_bps':row.one_way_bps,'borrow_bps':row.borrow_bps,'net_cost_reconciliation':True,'no_unquoted_orders':True,'cumulative_result_reconciled':True})
    pd.DataFrame(checks).to_csv(output/'mechanical_checks_PRIVATE.csv',index=False)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    figure,axes=plt.subplots(1,2,figsize=(12,4))
    curves=0
    for mode in ['strict-observed-daily','certified-stale-valuation']:
        path=replay/f'{mode}_delay0_cost10_borrow100_PRIVATE.csv'
        if not path.exists():
            continue
        ledger=pd.read_csv(path,parse_dates=['date'])
        nav=(1+ledger.net).cumprod();axes[0].plot(ledger.date,nav,label=mode)
        peak=np.maximum.accumulate(np.r_[1.,nav.to_numpy()])[1:]
        axes[1].plot(ledger.date,nav/peak-1,label=mode);curves+=1
    if curves:
        axes[0].legend(fontsize=8);axes[1].legend(fontsize=8)
    else:
        for axis in axes:
            axis.text(.5,.5,'Reference scenarios not estimable',ha='center',va='center',transform=axis.transAxes)
    axes[0].set_title('Fixed reference: equity after costs and borrow');axes[1].set_title('Fixed reference: drawdown')
    figure.tight_layout();figure.savefig(output/'reference_equity_PRIVATE.png',dpi=160);plt.close(figure)
    figure,axis=plt.subplots(figsize=(7,4))
    for mode in ['strict-observed-daily','certified-stale-valuation']:
        selected=results.loc[results['mode'].eq(mode)&results.delay.eq(0)&results.borrow_bps.eq(100)&results.status.eq('computed')].sort_values('one_way_bps')
        if not selected.empty:
            axis.plot(selected.one_way_bps,selected.total_net,marker='o',label=mode)
    axis.set_xlabel('One-way transaction cost (bps)');axis.set_ylabel('Cumulative net return')
    axis.set_title('Predefined cost sensitivity; fixed borrow and delay')
    if axis.lines:
        axis.legend(fontsize=8)
    else:
        axis.text(.5,.5,'No estimable predefined cost scenarios',ha='center',va='center',transform=axis.transAxes)
    figure.tight_layout();figure.savefig(output/'cost_sensitivity_PRIVATE.png',dpi=160);plt.close(figure)
    diagnosis=root/'daily_return_review_v3'/'first_gap_diagnosis_PRIVATE.csv'
    diagnosis_table='See the private source-window audit.'
    if diagnosis.exists():
        frame=pd.read_csv(diagnosis)
        columns=[name for name in ['permno','date','diagnosis','return_missing_flag','return_duration_flag','previous_price_date','trading_status','delisting'] if name in frame]
        diagnosis_table=formatting.table(frame[columns])
    alternate=root/'alternate_source_probe_v3'/'candidate_status_PRIVATE.csv'
    alternate_table=formatting.table(pd.read_csv(alternate)) if alternate.exists() else 'Alternate-source probe not completed.'
    full_source=root/source_resolution_name/'provider_audit_PRIVATE.csv'
    full_source_table=formatting.table(pd.read_csv(full_source)) if full_source.exists() else 'No separate full-period alternate valuation was admitted in this run.'
    source_protocol_path=root/source_resolution_name/'protocol.json'
    source_protocol=json.loads(source_protocol_path.read_text()) if source_protocol_path.exists() else {}
    reference=json.loads((replay/'reference_diagnostics_PRIVATE.json').read_text())
    all_reference_estimable=all(value['status']=='computed' for value in reference.values())
    any_reference_estimable=any(value['status']=='computed' for value in reference.values())
    verdict=('Both predefined valuation conventions have a complete reference ledger.' if all_reference_estimable else
        'At least one reference ledger is complete only under its recorded valuation assumptions; the other convention is not estimable.' if any_reference_estimable else
        'The reference strategy remains unestimable under both predefined conventions. No complete strategy performance is claimed.')
    report=['# Company News — Integrated Private Research Update, Version 3','',
        '**Private WRDS report. Empirical contents and figures are not cleared for dissemination or LLM ingestion.**','',
        'Wharton Research Data Services (WRDS) was used in preparing this company-news research. This service and the data available thereon constitute valuable intellectual property and trade secrets of WRDS and/or its third-party suppliers.','',
        '## What changed and why','',
        'The original v2 portfolio stopped on a missing held-security return. V2 forecasts, labels, reports and failed scenarios remain unchanged. V3 replays the same frozen predictions with current documented CIZ metadata, executable-quote constraints and two prespecified valuation conventions. This is a protocol amendment prompted by a data/implementation failure, not a selection based on observed profitability.','',
        '## Original source-gap diagnosis','',diagnosis_table,'',
        'The missingness flag explains the missing value, the duration flag identifies single-session versus multi-session returns, and previous-price date pins the start of a vendor payoff. Active/halted/suspended/delisted status and the regular-session close determine execution availability. These are distinct questions.','',
        '## Alternate-source findings','',alternate_table,'',
        'Annual CIZ, legacy CRSP where covered and historical CCM-linked Compustat total-return candidates were assessed within the original first-gap window. The Compustat index uses PRCCD/AJEXDI multiplied by TRFD. Missing factors were not set to one. Identity, adjacent sessions, USD continuity, positive volume and observed-day overlap gates are retained. Passing these gates does not independently certify PRCSTD quote semantics or admit that source into the full replay. No alternate price replaces an execution quotation.','',
        '### Separately recorded full-period source reconciliation','',full_source_table,'',
        'The precise source-QC amendment is preserved below; earlier global-gate attempts are retained, and local-prior-window results, if present, are a separate retrospective sensitivity rather than the original forecast confirmation test.','',
        '```json',json.dumps(source_protocol,indent=2),'```','',
        'Where a full-period source-reconciliation archive is used, its independent protocol additionally validates both historical return endpoints and complete recovery segments. It may repair MP/MV/GP valuation intervals with a complete independently sourced total-return index, while new-security, off-exchange and unknown delisting cases remain unresolved. It cannot change raw primary values, identity, execution closes, trading flags or predictions. This is a separate amendment prompted by unresolved data gaps, not by inspected forecast profitability.','',
        '## Complete implementation comparison','',verdict,'',formatting.table(results),'',
        'The strict convention requires observed daily economic returns. The certified convention may carry an explicit stale valuation through a closed MP gap, retain the pre-gap economic claim without discretionary trades, and recognize the full vendor-certified payoff on recovery. The prior price date and trading-session duration must match. These intermediate marks are valuation assumptions, not measured zero returns.','',
        'Orders cannot execute without a positive regular-session close and active trading status. Unquoted positions remain locked, consume the same-direction budget and may exit after the planned fifth session. Borrowing costs continue. Open/unreconciled gaps, unknown corporate actions and pending delisting values still stop a scenario. A completed ledger demonstrates accounting under assumptions; it does not prove executable alpha.','',
        '![Private reference equity and drawdown](reference_equity_PRIVATE.png)','',
        '![Private cost sensitivity](cost_sensitivity_PRIVATE.png)','',
        '## Fixed reference and uncertainty','',
        '```json',json.dumps(reference,indent=2),'```','',
        'The reference remains extra delay 0, one-way costs 10 bps and annual borrowing 100 bps. Block intervals condition on this historical design and stale-value timing, if used. Market-only beta/intercept are descriptive and do not establish broad factor neutrality. Positive net performance, if any, does not prove future profitability.','',
        '## Statistical study and full outputs','',
        f'The original 18 forecast comparisons, explanatory panel, event paths and unfavorable/uncertain findings remain in [the v2 integrated report](../final_report/REPORT_PRIVATE.md). The current source snapshot, protocol, all 72 cost/borrow/delay attempts, per-scenario ledgers, security contributions and buffer-year labels are in [the implementation report](../{replay_name}/REPORT_PRIVATE.md). The initial CIZ-only v3 attempts remain in implementation_replay_v3. No preferred years or scenarios were removed.','',
        'The predefined 2026 liquidation buffer remains distinct from the 2021–2025 confirmation years. Value certainty within trading suspensions, source vintage revisions, historical score availability, borrowing supply, funding, market impact and quote quality remain limitations.','',
        '## Mechanical verification and release boundary','',formatting.table(pd.DataFrame(checks)),'',
        'Computed ledgers reconcile gross P&L, borrow, trading costs and net; unquoted orders must be zero; scenario totals match their ledgers. All source/output fingerprints are preserved. Any unestimable attempts remain in the scenario table. Human economic interpretation and dissemination review remain pending.']
    (output/'REPORT_PRIVATE.md').write_text('\n\n'.join(report),encoding='utf-8')
    (output/'manifest.json').write_text(json.dumps({'status':'integrated-v3-report-and-mechanical-checks-executed',
        'reference_estimability':{mode:value['status'] for mode,value in reference.items()},
        'all_reference_conventions_estimable':all_reference_estimable,'at_least_one_reference_estimable':any_reference_estimable,
        'research_economic_claim_review_pending':True,'commercial_data_publication_authorized':False,
        'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'outputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()}},indent=2))
    print('V3_INTEGRATED_REPORT_COMPLETED',flush=True)
