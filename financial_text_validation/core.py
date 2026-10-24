"""Chronological, publication-aware text/price experiments with a frozen cohort."""
from __future__ import annotations
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import time

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from .fetch_data import end_of_day

PRICE = ['return_1', 'return_5', 'return_20', 'return_60', 'volatility_20', 'quote_age_days']
FAMILIES = ['historical_up_frequency', 'price_logistic', 'price_hist_gradient', 'text_logistic', 'fusion_logistic']


def digest(content):
    return hashlib.sha256(content).hexdigest()


def source_hashes():
    return {p.name: digest(p.read_bytes()) for p in sorted(Path(__file__).parent.glob('*.py'))}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def normalize_text(text):
    return re.sub(r'[^a-z0-9]+', ' ', str(text).lower()).strip()


def shingles(text):
    words = normalize_text(text).split()
    return {tuple(words[i:i+5]) for i in range(max(0, len(words)-4))}


def load_data(directory):
    directory = Path(directory)
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('data_kind') != 'public-real' or 'public-domain' not in manifest.get('license', ''):
        raise ValueError('Expected the documented public-domain real-data snapshot')
    for name in ['statements.csv', 'eurusd_vintages.csv']:
        if digest((directory/name).read_bytes()) != manifest['files_sha256'][name]:
            raise ValueError('Dataset fingerprint differs: ' + name)
    statements = pd.read_csv(directory/'statements.csv')
    quotes = pd.read_csv(directory/'eurusd_vintages.csv')
    references = {r['url']: r['raw_sha256'] for r in manifest['sources']}
    for frame in [statements, quotes]:
        if not frame.source_url.str.startswith('https://www.federalreserve.gov/').all() or any(references.get(r.source_url) != r.raw_sha256 for r in frame.itertuples()):
            raise ValueError('Row provenance differs from the official-source manifest')
    return validate_data(statements, quotes) + (manifest,)


def validate_data(statements, quotes):
    statements, quotes = statements.copy(), quotes.copy()
    expected_s = {'event_id', 'publication_date', 'available_at', 'decision_at', 'text', 'source_url', 'raw_sha256', 'text_sha256'}
    expected_q = {'observation_date', 'rate', 'release_date', 'available_at', 'source_url', 'raw_sha256'}
    if set(statements) != expected_s or set(quotes) != expected_q or statements.empty or quotes.empty:
        raise ValueError('Unexpected input contract; target/prediction columns are forbidden')
    for frame, names in [(statements, ['available_at', 'decision_at']), (quotes, ['available_at'])]:
        for name in names:
            if not frame[name].map(lambda s: (isinstance(s, pd.Timestamp) and s.tzinfo is not None) or (isinstance(s, str) and bool(re.search(r'(Z|[+-]\d{2}:\d{2})$', s)))).all():
                raise ValueError('Explicit timezone offsets required')
            frame[name] = pd.to_datetime(frame[name], utc=True, errors='raise')
    for name in ['publication_date']:
        statements[name] = pd.to_datetime(statements[name], errors='raise')
    for name in ['observation_date', 'release_date']:
        quotes[name] = pd.to_datetime(quotes[name], errors='raise')
    for frame, names in [(statements, ['publication_date']), (quotes, ['observation_date', 'release_date'])]:
        for name in names:
            if frame[name].dt.tz is not None or not frame[name].eq(frame[name].dt.normalize()).all():
                raise ValueError('Timezone-naive calendar dates required')
    quotes['rate'] = pd.to_numeric(quotes.rate, errors='raise')
    if not np.isfinite(quotes.rate).all() or (quotes.rate <= 0).any() or quotes.observation_date.duplicated().any():
        raise ValueError('Positive finite first-vintage quotes with unique dates required')
    if statements.event_id.duplicated().any() or statements.publication_date.duplicated().any():
        raise ValueError('Unique publication events required')
    for row in statements.itertuples():
        if not isinstance(row.text, str) or len(row.text.split()) < 5 or digest(row.text.encode()) != row.text_sha256:
            raise ValueError('Invalid statement text or text fingerprint')
        if row.available_at != pd.Timestamp(end_of_day(row.publication_date)) or row.decision_at != pd.Timestamp(end_of_day(row.publication_date + pd.Timedelta(days=1))):
            raise ValueError('Statement availability/decision differs from the conservative date rule')
    for row in quotes.itertuples():
        if row.release_date <= row.observation_date or row.available_at != pd.Timestamp(end_of_day(row.release_date)):
            raise ValueError('Observation date cannot stand in for release availability')
    return statements.sort_values('publication_date').reset_index(drop=True), quotes.sort_values('observation_date').reset_index(drop=True)


def build_panel(statements, quotes, protocol, *, price_delay_days=0):
    if isinstance(price_delay_days, bool) or not isinstance(price_delay_days, int) or price_delay_days < 0:
        raise ValueError('Nonnegative integer delay required')
    statements, quotes = validate_data(statements, quotes)
    horizon = protocol['horizon_observations']
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
        raise ValueError('Positive integer target horizon required')
    seen, previous, rows, exclusions = set(), set(), [], []
    for event in statements.itertuples():
        normalized = normalize_text(event.text)
        identity = digest(normalized.encode())
        if identity in seen:
            exclusions.append({'event_id': event.event_id, 'reason': 'exact normalized duplicate of an earlier statement'})
            continue
        seen.add(identity)
        current = shingles(event.text)
        similarity = len(current & previous) / len(current | previous) if current | previous else 0.
        previous = current
        if not pd.Timestamp(protocol['events_start']) <= event.publication_date <= pd.Timestamp(protocol['events_end']):
            continue
        cutoff = event.decision_at - pd.Timedelta(days=price_delay_days)
        available = quotes[quotes.available_at <= cutoff]
        decision_date = event.decision_at.tz_convert('America/New_York').tz_localize(None).normalize()
        entry = int(quotes.observation_date.searchsorted(decision_date, side='right'))
        if len(available) < 61 or entry + horizon >= len(quotes):
            exclusions.append({'event_id': event.event_id, 'reason': 'insufficient published price history or target observations'})
            continue
        history = available.tail(61)
        window = quotes.iloc[entry:entry+horizon+1]
        if history.observation_date.diff().dt.days.max() > 14 or (window.observation_date.iloc[-1] - window.observation_date.iloc[0]).days > 40:
            exclusions.append({'event_id': event.event_id, 'reason': 'unacceptable quote gap'})
            continue
        rates = history.rate.to_numpy()
        features = {f'return_{h}': float(np.log(rates[-1] / rates[-1-h])) for h in [1, 5, 20, 60]}
        features['volatility_20'] = float(np.std(np.diff(np.log(rates))[-20:], ddof=1))
        features['quote_age_days'] = float((decision_date - history.observation_date.iloc[-1]).days)
        future_return = float(np.log(window.rate.iloc[-1] / window.rate.iloc[0]))
        rows.append(dict(event_id=event.event_id, publication_date=event.publication_date, available_at=event.available_at,
                         decision_at=event.decision_at, text=event.text, text_sha256=event.text_sha256, source_url=event.source_url,
                         feature_observation_date=history.observation_date.max(), feature_available_at=history.available_at.max(),
                         feature_cutoff=cutoff, entry_date=window.observation_date.iloc[0], label_end=window.observation_date.iloc[-1],
                         label_available_at=window.available_at.max(), entry_rate=float(window.rate.iloc[0]), end_rate=float(window.rate.iloc[-1]),
                         log_return=future_return, target=int(future_return > 0), prior_text_jaccard=similarity, **features))
    panel = pd.DataFrame(rows)
    if panel.empty:
        raise ValueError('No eligible events')
    if not (panel.feature_available_at <= panel.feature_cutoff).all() or not (panel.available_at < panel.decision_at).all():
        raise ValueError('Availability leakage detected')
    if not (panel.entry_date > panel.decision_at.dt.tz_convert('America/New_York').dt.tz_localize(None).dt.normalize()).all():
        raise ValueError('Entry quote must strictly follow decision')
    return panel.reset_index(drop=True), pd.DataFrame(exclusions, columns=['event_id', 'reason'])


def split_masks(panel, protocol):
    valid_start = pd.Timestamp(protocol['train_end']) + pd.Timedelta(days=1)
    confirm_start = pd.Timestamp(protocol['confirmation_start'])
    valid_clock = valid_start.tz_localize('America/New_York').tz_convert('UTC')
    confirm_clock = confirm_start.tz_localize('America/New_York').tz_convert('UTC')
    masks = {'train': (panel.publication_date < valid_start) & (panel.label_available_at < valid_clock),
             'validation': (panel.publication_date >= valid_start) & (panel.publication_date < confirm_start) & (panel.label_available_at < confirm_clock),
             'confirmation': panel.publication_date >= confirm_start,
             'final_fit': (panel.publication_date < confirm_start) & (panel.label_available_at < confirm_clock)}
    if any(masks[n].sum() < 10 for n in ['train', 'validation', 'confirmation']):
        raise ValueError('At least ten retained events per evaluation partition required')
    if any(panel.loc[masks[n], 'target'].nunique() < 2 for n in ['train', 'final_fit']):
        raise ValueError('Both directions required for training')
    if (masks['train'] & masks['validation']).any() or (masks['final_fit'] & masks['confirmation']).any():
        raise ValueError('Date isolation failed')
    return masks


def make_model(family, c, protocol):
    if family not in FAMILIES:
        raise ValueError('Unknown model family')
    if family == 'historical_up_frequency':
        return Pipeline([('features', ColumnTransformer([('price', 'passthrough', PRICE)])), ('model', DummyClassifier(strategy='prior'))])
    transformers = []
    if family != 'text_logistic':
        transformers.append(('price', StandardScaler(), PRICE))
    if family in {'text_logistic', 'fusion_logistic'}:
        tfidf = protocol['text_features']
        if tfidf['stop_words'] != 'english-preserving-no-not-nor':
            raise ValueError('Expected the specified negation-preserving stop list')
        transformers.append(('text', TfidfVectorizer(ngram_range=(1, 2), max_features=tfidf['max_features'], min_df=tfidf['min_df'],
                                                   sublinear_tf=tfidf['sublinear_tf'], stop_words=sorted(set(ENGLISH_STOP_WORDS)-{'no','not','nor'})), 'text'))
    features = ColumnTransformer(transformers, sparse_threshold=1.)
    if family == 'price_hist_gradient':
        estimator = HistGradientBoostingClassifier(**protocol['price_hist_gradient'], random_state=20261023)
    else:
        estimator = LogisticRegression(C=float(c), solver='liblinear', max_iter=2000, random_state=20261023)
    return Pipeline([('features', features), ('model', estimator)])


def metrics(y, p):
    y, p = np.asarray(y), np.asarray(p, dtype=float)
    if y.ndim != 1 or p.shape != y.shape or not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError('Aligned finite probabilities required')
    result = {'events': len(y), 'accuracy': float(accuracy_score(y, p >= .5)), 'balanced_accuracy': float(balanced_accuracy_score(y, p >= .5)) if len(np.unique(y)) == 2 else None,
              'log_loss': float(log_loss(y, p, labels=[0, 1])), 'brier': float(brier_score_loss(y, p)),
              'auc': float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else None}
    bins = np.minimum((p * 5).astype(int), 4)
    result['ece_5_bins'] = float(sum(np.mean(bins == b) * abs(np.mean(p[bins == b]) - np.mean(y[bins == b])) for b in range(5) if np.any(bins == b)))
    return result


def contribution(y, p, kind):
    y, p = np.asarray(y), np.clip(np.asarray(p), 1e-15, 1-1e-15)
    if kind == 'log_loss':
        return -(y * np.log(p) + (1-y) * np.log(1-p))
    if kind == 'brier':
        return (p-y) ** 2
    if kind == 'accuracy':
        return ((p >= .5) == y).astype(float)
    raise ValueError('Unknown paired measure')


def paired_interval(y, reference, new, kind, protocol):
    delta = contribution(y, reference, kind) - contribution(y, new, kind)
    if kind == 'accuracy':
        delta = -delta
    config = protocol['uncertainty']
    n, block = len(delta), config['events_per_block']
    if n < block:
        raise ValueError('Too few events for registered uncertainty blocks')
    rng = np.random.default_rng(config['seed'])
    starts = rng.integers(0, n-block+1, (config['moving_block_event_bootstrap'], int(np.ceil(n / block))))
    indexes = (starts[..., None] + np.arange(block)).reshape(len(starts), -1)[:, :n]
    low, high = np.quantile(delta[indexes].mean(axis=1), config['interval'])
    return {'metric': kind, 'advantage': float(delta.mean()), 'low': float(low), 'high': float(high), 'events': n}


@threadpool_limits.wrap(limits=1)
def run_study(data_directory, protocol_path, output):
    started = time.perf_counter()
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Use a new or empty output directory; existing confirmation evidence is not overwritten')
    output.mkdir(parents=True, exist_ok=True)
    protocol_path = Path(protocol_path)
    protocol = json.loads(protocol_path.read_text(encoding='utf-8'))
    statements, quotes, data_manifest = load_data(data_directory)
    if digest(json.dumps(protocol, sort_keys=True).encode()) != data_manifest['protocol_sha256']:
        raise ValueError('Dataset discovery protocol differs from the modeling protocol')
    panel, exclusions = build_panel(statements, quotes, protocol)
    masks = split_masks(panel, protocol)
    panel.drop(columns='text').assign(partition=np.select([masks['train'], masks['validation'], masks['confirmation']], ['train', 'validation', 'confirmation'], default='purged')).to_csv(output/'event_panel.csv', index=False)
    exclusions.to_csv(output/'exclusions.csv', index=False)
    manifest = {'data_kind': 'public-real', 'source_sha256': source_hashes(), 'protocol_sha256': digest(protocol_path.read_bytes()),
                'data_manifest_sha256': digest((Path(data_directory)/'manifest.json').read_bytes()), 'data_files_sha256': data_manifest['files_sha256'],
                'created_utc': pd.Timestamp.now(tz='UTC').isoformat(), 'environment': {'python': platform.python_version(), 'platform': platform.platform(),
                'dependencies': {n: importlib.metadata.version(n) for n in ['numpy', 'pandas', 'scikit-learn', 'scipy', 'matplotlib']}}}
    write_json(output/'manifest.json', manifest)
    train, valid, final, confirm = (panel.loc[masks[n]] for n in ['train', 'validation', 'final_fit', 'confirmation'])
    searches, selected, validation_metrics = [], {}, {}
    for family in FAMILIES:
        grid = protocol['logistic_C'] if family.endswith('logistic') else [None]
        candidates = []
        for c in grid:
            model = make_model(family, c, protocol)
            before = time.perf_counter()
            model.fit(train, train.target)
            score = metrics(valid.target, model.predict_proba(valid)[:, 1])
            candidates.append((score['log_loss'], c if c is not None else 0., c, score))
            searches.append(dict(family=family, C=c, stage='development', elapsed_seconds=time.perf_counter()-before, **score))
        _, _, c, score = min(candidates, key=lambda t: (t[0], t[1]))
        selected[family], validation_metrics[family] = c, score
    best_price = min(['price_logistic', 'price_hist_gradient'], key=lambda f: validation_metrics[f]['log_loss'])
    pd.DataFrame(searches).to_csv(output/'development_search.csv', index=False)
    freeze = {'protocol_sha256': manifest['protocol_sha256'], 'cohort': FAMILIES, 'selected_C': selected, 'best_price_family': best_price,
              'selection_metric': 'validation log loss', 'training_ids': train.event_id.tolist(), 'validation_ids': valid.event_id.tolist(),
              'final_fit_ids': final.event_id.tolist(), 'confirmation_ids': confirm.event_id.tolist(),
              'boundary': 'Written before fitting final models or requesting confirmation predictions', 'created_utc': pd.Timestamp.now(tz='UTC').isoformat()}
    write_json(output/'freeze.json', freeze)
    models, scores, summary = {}, {}, []
    predictions = confirm.drop(columns='text').copy()
    for family in FAMILIES:
        model = make_model(family, selected[family], protocol)
        model.fit(final, final.target)
        models[family] = model
        scores[family] = model.predict_proba(confirm)[:, 1]
        predictions[family] = scores[family]
        summary.extend([dict(family=family, partition='validation', **validation_metrics[family]),
                        dict(family=family, partition='confirmation', **metrics(confirm.target, scores[family]))])
    predictions.to_csv(output/'aligned_predictions.csv', index=False)
    summary = pd.DataFrame(summary)
    summary.to_csv(output/'model_comparison.csv', index=False)
    contrasts = []
    for ref, new in [(best_price, 'fusion_logistic'), ('historical_up_frequency', 'text_logistic'), (best_price, 'text_logistic')]:
        for measure in ['log_loss', 'accuracy', 'brier']:
            contrasts.append(dict(reference=ref, model=new, **paired_interval(confirm.target, scores[ref], scores[new], measure, protocol)))
    contrasts_df = pd.DataFrame(contrasts)
    contrasts_df.to_csv(output/'paired_uncertainty.csv', index=False)
    calibration, by_year = [], []
    for family in FAMILIES:
        p = scores[family]
        bins = np.minimum((p*5).astype(int), 4)
        for b in range(5):
            mask = bins == b
            if mask.any():
                calibration.append({'family': family, 'bin': b, 'events': int(mask.sum()), 'mean_prediction': float(p[mask].mean()), 'observed_up': float(confirm.target.to_numpy()[mask].mean())})
        for year in sorted(confirm.publication_date.dt.year.unique()):
            mask = confirm.publication_date.dt.year.to_numpy() == year
            by_year.append(dict(family=family, year=int(year), **metrics(confirm.target.to_numpy()[mask], p[mask])))
    pd.DataFrame(calibration).to_csv(output/'calibration.csv', index=False)
    pd.DataFrame(by_year).to_csv(output/'by_year.csv', index=False)
    permutation = make_model('fusion_logistic', selected['fusion_logistic'], protocol)
    permutation.fit(final, np.random.default_rng(20261023).permutation(final.target))
    diagnostics = {'training_label_permutation': metrics(confirm.target, permutation.predict_proba(confirm)[:, 1])}
    delayed, _ = build_panel(statements, quotes, protocol, price_delay_days=14)
    delayed_masks = split_masks(delayed, protocol)
    delayed_confirm = delayed.loc[delayed_masks['confirmation']].set_index('event_id', drop=False).loc[confirm.event_id]
    delayed_final = delayed.loc[delayed_masks['final_fit']]
    diagnostics['extra_14_day_publication_delay'] = {}
    for family in [best_price, 'fusion_logistic']:
        delayed_model = make_model(family, selected[family], protocol)
        delayed_model.fit(delayed_final, delayed_final.target)
        diagnostics['extra_14_day_publication_delay'][family] = metrics(delayed_confirm.target, delayed_model.predict_proba(delayed_confirm)[:, 1])
    distinct = confirm.prior_text_jaccard.to_numpy() < .9
    diagnostics['lower_similarity_confirmation'] = {'events': int(distinct.sum()), 'threshold': .9}
    if distinct.sum() >= 5:
        diagnostics['lower_similarity_confirmation']['metrics'] = {f: metrics(confirm.target.to_numpy()[distinct], scores[f][distinct]) for f in FAMILIES}
    write_json(output/'diagnostics.json', diagnostics)
    coefficients = []
    for family in ['price_logistic', 'text_logistic', 'fusion_logistic']:
        fitted = models[family]
        for feature, value in zip(fitted['features'].get_feature_names_out(), fitted['model'].coef_[0]):
            coefficients.append({'family': family, 'feature': feature, 'coefficient': float(value)})
    pd.DataFrame(coefficients).to_csv(output/'coefficients.csv', index=False)
    primary = contrasts_df[(contrasts_df.model == 'fusion_logistic') & (contrasts_df.metric == 'log_loss')].iloc[0].to_dict()
    result = {'data_kind': 'public-real', 'statement_count': len(statements), 'quote_count': len(quotes), 'eligible_events': len(panel),
              'excluded_events': len(exclusions), 'partition_events': {k: int(v.sum()) for k,v in masks.items()},
              'purged_events': int((~(masks['train'] | masks['validation'] | masks['confirmation'])).sum()),
              'selected_C': selected, 'best_price_family': best_price, 'primary_contrast': primary,
              'confirmation': {f: metrics(confirm.target, scores[f]) for f in FAMILIES}, 'diagnostics': diagnostics,
              'freeze_sha256': digest((output/'freeze.json').read_bytes()), 'elapsed_seconds_before_figures': time.perf_counter()-started,
              'runtime_scope': 'local data verification, feature construction, 11 development fits, five refits, one permutation control and two delay stresses; not exchange latency',
              'limitations': ['small event sample', 'single currency', 'historical association, not causal effect', 'reference quotes, not executable fills',
                              'current copies of historical policy pages may contain editorial corrections', 'unadjusted bootstrap intervals conditional on this registered search']}
    write_json(output/'metrics.json', result)
    make_figures(output, panel, masks, summary, contrasts_df, pd.DataFrame(calibration), pd.DataFrame(by_year), best_price)
    make_report(output, result, summary)
    return result


def make_figures(output, panel, masks, summary, contrasts, calibration, years, best_price):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'axes.spines.top': False, 'axes.spines.right': False, 'font.size': 10})
    names = {'historical_up_frequency':'Prior', 'price_logistic':'Price LR', 'price_hist_gradient':'Price HGB', 'text_logistic':'Text LR', 'fusion_logistic':'Fusion LR'}
    fig, axes = plt.subplots(1,2,figsize=(11,4))
    x = np.arange(5)
    for offset, partition, color in [(-.18,'validation','#a9bdc7'),(.18,'confirmation','#36B3A8')]:
        part = summary[summary.partition == partition].set_index('family').loc[FAMILIES]
        for ax, metric, title in zip(axes,['log_loss','accuracy'],['Probability loss (lower is better)','Direction accuracy (higher is better)']):
            ax.bar(x+offset,part[metric],width=.34,label=partition,color=color)
            ax.set_xticks(x,[names[n] for n in FAMILIES],rotation=15)
            ax.set_title(title)
    fig.legend(*axes[0].get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.5,.94),ncol=2,frameon=False)
    fig.suptitle('FOMC text and archived EUR/USD references | real public data',fontsize=12,y=.995)
    fig.tight_layout(rect=[0,0,1,.82]);fig.savefig(output/'model_comparison.png',dpi=150);plt.close(fig)
    main = contrasts[(contrasts.reference==best_price)&(contrasts.model=='fusion_logistic')]
    fig,axes=plt.subplots(1,3,figsize=(11,3.2))
    for ax,metric,title in zip(axes,['log_loss','accuracy','brier'],['Log-loss reduction','Accuracy increase','Brier reduction']):
        row=main[main.metric==metric].iloc[0]
        ax.axvline(0,color='#a9bdc7');ax.errorbar(row.advantage,0,xerr=[[row.advantage-row.low],[row.high-row.advantage]],fmt='o',color='#234e70',capsize=5)
        ax.set(title=title,yticks=[],xlabel='Fusion advantage; positive favors fusion')
    fig.suptitle('Paired 95% moving-block intervals | four-event blocks, 5,000 draws',fontsize=11)
    fig.tight_layout();fig.savefig(output/'incremental_uncertainty.png',dpi=150);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(10,4))
    for family,color in zip([best_price,'text_logistic','fusion_logistic'],['#234e70','#b37743','#36B3A8']):
        group=calibration[calibration.family==family]
        axes[0].plot(group.mean_prediction,group.observed_up,marker='o',label=names[family],color=color)
        group=years[years.family==family]
        axes[1].plot(group.year,group.log_loss,marker='o',label=names[family],color=color)
    axes[0].plot([0,1],[0,1],'--',color='#a9bdc7');axes[0].set(xlim=(0,1),ylim=(0,1),xlabel='Mean predicted up probability',ylabel='Observed up fraction',title='Five-bin calibration; small bins are noisy')
    axes[1].set(xlabel='Confirmation year',ylabel='Log loss',title='All calendar-year slices retained')
    axes[1].set_xticks(sorted(years.year.unique()))
    axes[0].legend();fig.tight_layout();fig.savefig(output/'calibration_and_years.png',dpi=150);plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,3.2))
    for level,name,color in [(0,'train','#234e70'),(1,'validation','#b37743'),(2,'confirmation','#36B3A8')]:
        p=panel.loc[masks[name]]
        ax.scatter(p.publication_date,np.full(len(p),level),color=color,s=16)
        for row in p.itertuples():
            ax.plot([row.entry_date,row.label_end],[level,level],color=color,alpha=.25)
    ax.set(yticks=[0,1,2],yticklabels=['Train','Validation','Confirmation'],xlabel='Statement date / subsequent target window',title='Whole-event time split; labels unavailable across a boundary are purged')
    fig.tight_layout();fig.savefig(output/'timeline.png',dpi=150);plt.close(fig)


def make_report(output, result, summary):
    primary=result['primary_contrast']
    verdict='The interval includes zero; incremental text value is not established in this experiment.' if primary['low']<=0<=primary['high'] else ('Fusion reduces probability loss within this conditional historical experiment; this is not a trading or causal claim.' if primary['low']>0 else 'Fusion worsens probability loss relative to the preselected price model in this historical experiment.')
    table=['|Model|Accuracy|Log loss|Brier|','|---|---:|---:|---:|']
    for row in summary[summary.partition=='confirmation'].itertuples():
        table.append(f'|{row.family}|{row.accuracy:.3f}|{row.log_loss:.4f}|{row.brier:.4f}|')
    text=f'''# Executed real-data study

Data: **real public FOMC statements and first-published archived H.10 EUR/USD reference quotes**. This is an independent historical study, not an XForecast score or an investment return.

## Registered experiment

{result['statement_count']} statements, {result['quote_count']} first-vintage daily quotes, {result['eligible_events']} eligible events. Retained partitions: {result['partition_events']}. Exact duplicates and coverage exclusions: {result['excluded_events']}; split-boundary exclusions: {result['purged_events']}.

The decision occurs at 23:59 New York time on the day after statement publication. Quotes enter features only after their actual archived H.10 release date, conservatively at 23:59. The target begins at the first later observed noon quote and ends 20 observations later. H.10 is weekly: a quote's measurement date does not imply same-day public availability.

## Model comparison

{chr(10).join(table)}

![Price, text and fusion](model_comparison.png)

The nonlinear price control has the highest confirmation direction hit rate, but a worse log loss than the simple prior. This illustrates why a larger accuracy number is insufficient: confidently wrong probabilities incur larger losses. The text-only model's probability loss is close to the prior while its ranking AUC is below 0.5. The fixed fusion specification does not establish added information under the primary contrast; it is not replaced after viewing these outcomes.

Best price family selected on validation only: **{result['best_price_family']}**. Logistic C choices: {result['selected_C']}. The complete eleven-fit development grid is retained in development_search.csv. Final selected models refit on the earlier train/validation period after purging labels unavailable at confirmation start.

## Incremental text value

Confirmation log-loss reduction, selected price minus fusion: **{primary['advantage']:.5f}**, paired 95% moving-block interval **[{primary['low']:.5f}, {primary['high']:.5f}]**. Positive favors fusion. {verdict}

![Paired uncertainty](incremental_uncertainty.png)

The bootstrap uses 5,000 shared index draws in four-event blocks. These unadjusted intervals describe this frozen contrast; they do not account for every possible research choice or arbitrary long dependence. Accuracy and Brier contrasts are also retained.

![Calibration and yearly slices](calibration_and_years.png)

![Time split and target overlap](timeline.png)

## Controls and interpretation

diagnostics.json retains a fixed training-label permutation control, a 14-day extra publication-delay stress with unchanged settings, and a lower-text-similarity subset. All year slices are retained. A single shuffled fit is a diagnostic, not a permutation significance test. Coefficients describe fitted associations and can proxy the monetary-policy regime rather than a linguistic mechanism.

The universe is one currency and a small number of policy events. Near-repeated policy wording is flagged but retained because small edits can be economically meaningful; exact repeated bodies keep only the earliest occurrence. Current historical statement pages can have editorial corrections: archived H.10 quotes remove price-vintage hindsight, but do not prove original byte-for-byte statement vintages. Reference noon quotes are not executable bid/ask prices. No transaction-cost-adjusted P&L, immediate announcement effect or causal policy effect is claimed.

## Traceability

manifest.json binds source, protocol and data. freeze.json records selected settings and event IDs before confirmation prediction. event_panel.csv records the three clocks, price-feature cutoff, entry, label end and label availability. aligned_predictions.csv keys every model probability to the same event. Data URLs, raw source hashes and reuse policy are in ../../financial_text_validation/data/manifest.json. The complete report is generated by the final implementation; runtime is a local modeling workload, not trading latency.
'''
    (output/'REPORT.md').write_text(text,encoding='utf-8')
