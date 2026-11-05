# Data audit — incomplete

On 2026-11-05, an official PostgreSQL connection was attempted using the existing private libpq configuration. The WRDS server rejected authentication. The checked-in audit command reproduced this failure and wrote a sanitized private `audit.json`. No credentials, news rows or securities were printed or published.

This establishes an access blocker, **not absence of a RavenPack subscription**. A restored authenticated session is required to determine entitlements. Existing course exports and a successful connection in a different earlier research project do not resolve current access or rights.

|Acceptance item|Verified?|Evidence still required|
|---|---|---|
|Authenticated read-only database/Cloud access|No|Successful supported session.|
|RavenPack/CRSP products, table versions and SELECT permissions|No|Metadata inventory and bounded table access.|
|2010–2025 plus buffers|No|Per-year coverage/completeness and boundary checks.|
|Timestamp and historical revision meaning|No|Actual vendor documentation/version, field-level checks.|
|Sentiment, novelty, relevance, event labels and identities|No|Column semantics, ranges, missingness, story/entity/event multiplicity.|
|Historical security mapping|No|Effective dates, ambiguities and year/split loss table.|
|Feed completeness vs no news|No|Daily source-coverage reconciliation.|
|Headline/full-text access|No|Explicit entitlement; not inferred from analytics.|
|Raw/derived/model/aggregate dissemination|No|Applicable institution/vendor conditions and documented permitted outputs.|

After access is restored, run metadata discovery first. Review exact tables before bounded coverage queries; do not scan a full vendor corpus speculatively. Save private schema fingerprints, documentation references and sample-loss counts. The discovery command deliberately does not infer completeness from table names or privileges. Freeze real-data protocol only after the remaining checks; otherwise record a new version and the precise unresolved limitations.
