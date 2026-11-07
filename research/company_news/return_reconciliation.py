"""Conservative daily total-return reconciliation; no licensed inputs bundled."""
import numpy as np
import pandas as pd


DAILY_DURATION={'D1','D2','D3','D4','DU'}
MISSING_REASONS={
    'MP':'missing-price','GP':'price-gap-too-long','MV':'missing-corporate-action-value',
    'DM':'missing-delisting-value','DG':'delisting-price-too-late','DP':'delisting-pending',
    'NS':'new-security','NT':'not-tracked','RA':'return-after-not-tracked',
    'NA':'unclassified-or-not-applicable'}


def classify_rows(frame):
    """Keep vendor fields private; classification never implies a zero return."""
    result=frame.copy()
    result['diagnosis']=np.where(result.total_return.notna(),'observed',
        result.return_missing_flag.map(MISSING_REASONS).fillna('unknown-missing-flag'))
    multi=result.return_duration_flag.astype(str).str.fullmatch(r'P[1-9]')
    result.loc[result.total_return.notna()&multi,'diagnosis']='observed-multi-session-return'
    return result


def compustat_total_returns(frame, calendar):
    """Security/currency-stable consecutive-session index ratios, not price ratios.

    Index = (PRCCD/AJEXDI)*TRFD. Missing factors and intervening sessions stay
    missing. This constructs valuation candidates, not an execution quotation.
    """
    frame=frame.sort_values(['gvkey','iid','date']).copy()
    if frame.duplicated(['gvkey','iid','date']).any():
        raise ValueError('Ambiguous Compustat security-date')
    if not frame[['prccd','ajexdi','trfd']].notna().all(axis=1).any():
        frame['candidate_return']=np.nan
        return frame
    good=frame[['prccd','ajexdi','trfd']].gt(0).all(axis=1)
    frame['total_return_index']=(frame.prccd/frame.ajexdi*frame.trfd).where(good)
    grouped=frame.groupby(['gvkey','iid'],sort=False)
    previous=grouped.total_return_index.shift(1)
    prior_date=grouped.date.shift(1)
    prior_currency=grouped.curcdd.shift(1)
    calendar=pd.DatetimeIndex(calendar)
    current_position=calendar.get_indexer(frame.date)
    previous_position=calendar.get_indexer(prior_date)
    consecutive=(previous_position>=0)&(current_position==previous_position+1)
    frame['candidate_return']=(frame.total_return_index/previous-1).where(
        consecutive&frame.curcdd.eq(prior_currency)&frame.curcdd.eq('USD'))
    return frame


def exact_historical_links(candidates, links):
    """Require one GVKEY/IID per PERMNO-date; never substitute a current ticker."""
    keys=candidates[['permno','date']].drop_duplicates()
    matched=keys.merge(links,on='permno',how='left')
    valid=matched.date.ge(matched.valid_from)&matched.date.le(matched.valid_to)
    matched=matched.loc[valid,['permno','date','gvkey','iid']].drop_duplicates()
    matched=matched.loc[~matched.duplicated(['permno','date'],keep=False)]
    return matched.loc[~matched.duplicated(['gvkey','iid','date'],keep=False)].reset_index(drop=True)


def accept_daily_candidates(primary, candidate, *, minimum_overlap=20,
                            absolute_tolerance=1e-6, relative_tolerance=1e-5,
                            calendar=None, allowed_missing_flags=frozenset({'MP'}),
                            overlap_scope='global'):
    """No outcome tuning: same historical identity, true daily return, overlap audit.

    An observed daily primary return is never overwritten. A verified multi-session
    recovery is decomposed only with a complete alternate daily segment, matched
    previous-price date and duration. Otherwise the entire gap stays unresolved.
    Overlap checks are retrospective data QC, not a PIT claim.
    """
    if primary.duplicated(['permno','date']).any() or candidate.duplicated(['permno','date']).any():
        raise ValueError('Duplicate reconciliation key')
    merged=primary.merge(candidate,on=['permno','date'],how='left',validate='one_to_one')
    candidate_value=pd.to_numeric(merged.candidate_return,errors='coerce')
    overlap=merged.total_return.notna()&candidate_value.notna()&merged.return_duration_flag.isin(DAILY_DURATION)
    overlap&=merged.delisting.eq('N').fillna(False)
    close=np.isclose(merged.total_return.to_numpy(dtype=float,na_value=np.nan),
        candidate_value.to_numpy(dtype=float,na_value=np.nan),atol=absolute_tolerance,rtol=relative_tolerance)
    audit=pd.DataFrame({'permno':merged.permno,'observations':overlap.astype(int),
        'disagreements':(overlap&~close).astype(int)}).groupby('permno').sum()
    accepted=audit.index[(audit.observations>=minimum_overlap)&audit.disagreements.eq(0)]
    if overlap_scope not in {'global','local-prior20'}:
        raise ValueError('Unspecified source-overlap protocol')
    eligible=merged.total_return.isna()&candidate_value.notna()
    if overlap_scope=='global':
        eligible&=merged.permno.isin(accepted)
    eligible&=merged.return_missing_flag.isin(allowed_missing_flags)&merged.delisting.eq('N').fillna(False)
    recovery=pd.Series(False,index=merged.index)
    for _,group in merged.groupby('permno',sort=False):
        indices=group.sort_values('date').index.to_numpy()
        missing=merged.loc[indices,'total_return'].isna().to_numpy()
        offset=0
        while offset<len(indices):
            if not missing[offset]:
                offset+=1;continue
            end=offset
            while end<len(indices) and missing[end]:
                end+=1
            gap=indices[offset:end]
            valid=offset>0 and end<len(indices) and eligible.loc[gap].all()
            if valid and overlap_scope=='local-prior20':
                cutoff=merged.at[gap[0],'date']
                history=indices[(merged.loc[indices,'date'].lt(cutoff)&merged.loc[indices,'date'].ge(cutoff-pd.Timedelta(days=60))&overlap.loc[indices]).to_numpy()][-minimum_overlap:]
                valid=len(history)==minimum_overlap and bool(np.asarray(close)[history].all())
            if valid:
                next_index=indices[end]
                flag=merged.at[next_index,'return_duration_flag']
                if flag not in DAILY_DURATION:
                    valid=calendar is not None and 'previous_price_date' in merged
                    if valid:
                        valid=validate_bridge(calendar,merged.at[indices[offset-1],'date'],
                            merged.at[next_index,'date'],merged.at[next_index,'previous_price_date'],flag)
                    if valid:
                        valid=pd.notna(candidate_value.at[next_index]) and merged.at[next_index,'delisting']=='N'
                    if valid:
                        original=float(merged.at[next_index,'total_return'])
                        reconstructed=float(np.prod(1+candidate_value.loc[indices[offset:end+1]])-1)
                        valid=np.isclose(original,reconstructed,atol=absolute_tolerance,rtol=relative_tolerance)
                    if valid:
                        recovery.at[next_index]=True
            if not valid:
                eligible.loc[gap]=False
            offset=end
    # Do not resolve MV, GP, pending delisting or identity problems with a close.
    merged['resolved_return']=merged.total_return
    merged.loc[eligible,'resolved_return']=candidate_value.loc[eligible]
    merged.loc[recovery,'resolved_return']=candidate_value.loc[recovery]
    merged['return_provenance']=np.where(eligible,'validated-alternate-daily-total-return','original-crsp')
    merged.loc[recovery,'return_provenance']='validated-daily-decomposition-of-crsp-bridge'
    merged.loc[merged.resolved_return.isna(),'return_provenance']='unresolved'
    return merged,audit


def validate_bridge(calendar, last_mark, recovery_date, previous_date, duration_flag):
    """Validate a CRSP multi-session payoff without distributing it backwards."""
    calendar=pd.DatetimeIndex(calendar)
    last,recovery=calendar.get_indexer([last_mark,recovery_date])
    if min(last,recovery)<0 or recovery<=last or pd.Timestamp(previous_date)!=pd.Timestamp(last_mark):
        return False
    if str(duration_flag) not in {f'P{i}' for i in range(1,10)}:
        return False
    return recovery-last==int(str(duration_flag)[1:])+1
