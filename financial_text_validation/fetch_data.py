"""Fetch only official Board documents; normalize text and unrevised FX vintages."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import pandas as pd
import requests

BASE = 'https://www.federalreserve.gov'
_lock = threading.Lock()
_last = 0.


def sha(data):
    return hashlib.sha256(data).hexdigest()


def get_source(url, cache):
    global _last
    if urlparse(url).netloc != 'www.federalreserve.gov' or not url.startswith('https://'):
        raise ValueError('Only official Federal Reserve Board HTTPS sources are supported')
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (sha(url.encode()) + '.html')
    if target.exists():
        return target.read_bytes()
    for attempt in range(3):
        with _lock:
            time.sleep(max(0, .5 - (time.monotonic() - _last)))
            _last = time.monotonic()
        response = requests.get(url, timeout=40, headers={'User-Agent': 'FinancialTextValidation/0.1 public research; cached low-rate downloads'})
        if response.status_code == 200:
            if urlparse(response.url).netloc != 'www.federalreserve.gov':
                raise ValueError('Unexpected source redirect')
            target.write_bytes(response.content)
            return response.content
        if response.status_code not in {429, 500, 502, 503, 504}:
            response.raise_for_status()
        time.sleep(2 ** attempt)
    raise RuntimeError('Official source could not be downloaded: ' + url)


def end_of_day(date):
    return (pd.Timestamp(date).normalize() + pd.Timedelta(hours=23, minutes=59)).tz_localize('America/New_York').tz_convert('UTC').isoformat()


def parse_statement(content, url):
    soup = BeautifulSoup(content, 'html.parser')
    article = soup.select_one('#article')
    if article is None:
        raise ValueError('Missing policy statement article: ' + url)
    declared = article.select_one('.article__time')
    if declared is None:
        raise ValueError('Missing explicit release date')
    date = pd.Timestamp(declared.get_text(' ', strip=True)).date()
    encoded = re.search(r'monetary/?(\d{8})a\.htm$', url)
    if encoded is None or date != pd.to_datetime(encoded[1], format='%Y%m%d').date():
        raise ValueError('URL and displayed publication date differ')
    columns = article.select('div.col-sm-8:not(.heading)')
    paragraphs = [p.get_text(' ', strip=True) for c in columns for p in c.find_all('p')]
    text = '\n'.join(p for p in paragraphs if p)
    text = re.split(r'\bVoting (?:for|against)', text, maxsplit=1, flags=re.I)[0]
    text = re.sub(r'[ \t\r\f\v]+', ' ', text).strip()
    if len(text.split()) < 60 or len(text) > 30000:
        raise ValueError('Unexpected policy-body length: ' + url)
    return {'event_id': 'FOMC-' + date.isoformat(), 'publication_date': date.isoformat(),
            'available_at': end_of_day(date), 'decision_at': end_of_day(pd.Timestamp(date) + pd.Timedelta(days=1)),
            'text': text, 'source_url': url, 'raw_sha256': sha(content), 'text_sha256': sha(text.encode())}


def parse_h10(content, release_date, url):
    release_date = pd.Timestamp(release_date)
    soup = BeautifulSoup(content, 'html.parser')
    header, values = [], []
    table = soup.find('table', class_='statistics')
    if table is None:
        table = next((t for t in soup.find_all('table') if 'EMU MEMBERS' in t.get_text() and 'COUNTRY' in t.get_text()), None)
    if table is not None:
        for row in table.find_all('tr'):
            cells = row.find_all(['th', 'td'])
            texts = [c.get_text(' ', strip=True) for c in cells]
            if texts and texts[0] == 'COUNTRY':
                header = texts[2:]
            if len(texts) >= 7 and 'EMU MEMBERS' in texts[0] and texts[1] == 'EURO':
                values = texts[2:]
                break
    else:
        pre = soup.find('pre')
        if pre is None:
            raise ValueError('Missing archived H.10 table: ' + url)
        lines = pre.get_text().splitlines()
        date_pattern = r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}'
        date_matches = next((list(re.finditer(date_pattern, line)) for line in lines if len(list(re.finditer(date_pattern, line))) == 5), None)
        if not date_matches:
            raise ValueError('Missing five-date header: ' + url)
        header = [m[0] for m in date_matches]
        centers = [(m.start() + m.end()) / 2 for m in date_matches]
        row = next((line for line in lines if 'EMU MEMBERS' in line and 'EURO' in line), None)
        if row is None:
            raise ValueError('Missing EUR row')
        values = ['ND'] * 5
        for match in re.finditer(r'\d+\.\d+', row):
            center = (match.start() + match.end()) / 2
            column = min(range(5), key=lambda i: abs(centers[i] - center))
            if abs(centers[column] - center) > 5 or values[column] != 'ND':
                raise ValueError('Ambiguous fixed-width quote alignment')
            values[column] = match[0]
    if len(header) != 5 or len(values) != 5:
        raise ValueError('Expected a five-observation archived release: ' + url)
    rows = []
    for label, value in zip(header, values):
        month_day = re.sub(r'\.', '', label).strip()
        candidates = [pd.to_datetime(f'{month_day} {y}', errors='coerce') for y in [release_date.year - 1, release_date.year]]
        eligible = [d for d in candidates if pd.notna(d) and 0 < (release_date - d).days <= 14]
        if len(eligible) != 1:
            raise ValueError('Ambiguous observation year in release: ' + url)
        observation = eligible[0]
        if re.fullmatch(r'\d+\.\d+', value):
            rate = float(value)
            if not .1 < rate < 5:
                raise ValueError('Unexpected USD-per-EUR quote')
            rows.append({'observation_date': observation.date().isoformat(), 'rate': rate,
                         'release_date': release_date.date().isoformat(), 'available_at': end_of_day(release_date),
                         'source_url': url, 'raw_sha256': sha(content)})
    if not rows:
        raise ValueError('No valid EUR quotes in archived release')
    return rows


def fetch_dataset(output, cache, protocol):
    output, cache = Path(output), Path(cache)
    output.mkdir(parents=True, exist_ok=True)
    references = []
    def get(url):
        raw = get_source(url, cache)
        references.append({'url': url, 'raw_sha256': sha(raw), 'bytes': len(raw)})
        return raw
    policy_url = BASE + '/disclaimer.htm'
    policy = get(policy_url)
    if b'public domain' not in policy:
        raise ValueError('Official reuse policy needs human review')
    calendar_urls = [BASE + f'/monetarypolicy/fomchistorical{year}.htm' for year in range(2009, 2021)] + [BASE + '/monetarypolicy/fomccalendars.htm']
    statements = set()
    for url in calendar_urls:
        soup = BeautifulSoup(get(url), 'html.parser')
        for anchor in soup.select('a[href]'):
            href = anchor['href']
            if re.search(r'/newsevents/(?:pressreleases/monetary|press/monetary/)\d{8}a\.htm$', href) and (anchor.get_text(' ', strip=True) == 'Statement' or 'Statement:' in anchor.parent.get_text(' ', strip=True)):
                date = re.search(r'(\d{8})a\.htm$', href)[1]
                if protocol['events_start'].replace('-', '') <= date <= protocol['events_end'].replace('-', ''):
                    statements.add(urljoin(BASE, href))
    dates_url = BASE + '/releases/h10/releaseDates.json'
    calendar = json.loads(get(dates_url))
    releases = sorted({d for year in calendar for month in year['Months'] for d in month['Dates']
                       if protocol['quote_download_start'].replace('-', '') <= d <= protocol['quote_download_end'].replace('-', '')})
    print(json.dumps({'statement_sources': len(statements), 'archived_h10_sources': len(releases)}), flush=True)
    statement_rows, quote_rows, errors = [], [], []
    tasks = [('statement', u) for u in sorted(statements)] + [('quote', BASE + '/releases/h10/' + d + '/') for d in releases]
    def process(task):
        kind, url = task
        try:
            raw = get_source(url, cache)
            reference = {'url': url, 'raw_sha256': sha(raw), 'bytes': len(raw)}
            rows = [parse_statement(raw, url)] if kind == 'statement' else parse_h10(raw, pd.to_datetime(url.rstrip('/').split('/')[-1], format='%Y%m%d'), url)
            return kind, rows, reference, None
        except Exception as exc:
            return kind, [], {'url': url}, str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        for count, (kind, rows, reference, error) in enumerate(pool.map(process, tasks), 1):
            (statement_rows if kind == 'statement' else quote_rows).extend(rows)
            references.append(reference)
            if error:
                errors.append({'url': reference['url'], 'error': error})
            if count % 50 == 0:
                print(json.dumps({'processed': count, 'total': len(tasks), 'errors': len(errors)}), flush=True)
    (cache/'download_errors.json').write_text(json.dumps(errors, indent=2), encoding='utf-8')
    if errors:
        raise ValueError('Source collection failed closed; inspect the cache download_errors.json before using any dataset')
    statements_df = pd.DataFrame(statement_rows).sort_values('publication_date')
    quotes_df = pd.DataFrame(quote_rows).sort_values(['observation_date', 'available_at'])
    # Retain the first published vintage for repeated observations; no latest-vintage overwrite.
    quotes_df = quotes_df.drop_duplicates('observation_date', keep='first')
    statements_df.to_csv(output/'statements.csv', index=False, lineterminator='\n')
    quotes_df.to_csv(output/'eurusd_vintages.csv', index=False, lineterminator='\n')
    manifest = {'data_kind': 'public-real', 'retrieved_utc': datetime.now(timezone.utc).isoformat(),
                'license': 'Federal Reserve Board public-domain information; source attribution; no seals, logos or third-party material',
                'policy_url': policy_url, 'sources': references, 'statement_count': len(statements_df), 'quote_count': len(quotes_df),
                'files_sha256': {name: sha((output/name).read_bytes()) for name in ['statements.csv', 'eurusd_vintages.csv']},
                'protocol_sha256': sha((json.dumps(protocol, sort_keys=True)).encode())}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'complete', 'statements': len(statements_df), 'quotes': len(quotes_df)}), flush=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--cache', required=True)
    parser.add_argument('--protocol', required=True)
    args = parser.parse_args()
    fetch_dataset(args.output, args.cache, json.loads(Path(args.protocol).read_text(encoding='utf-8')))
