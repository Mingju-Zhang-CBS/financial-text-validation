# Data audit — access restored; completion conditions remain

## Cloud follow-up, 2026-11-05

The existing authenticated WRDS Cloud Jupyter session successfully connected using `wrds.Connection()`. The session reported read-only transactions. Actual RavenPack Dow Jones equity-year tables, common historical mappings and CRSP stock tables were inspected; SELECT access was tested. Annual news coverage queries completed for every year from 2010 through 2025. A bounded source sample and year-by-year historical company-mapping diagnostics were retained privately.

Legacy CRSP daily stock/index tables stop before the intended endpoint; the CIZ daily stock and index interfaces cover the endpoint and the quarterly source supplies the forward buffer. This is a source-interface issue, not grounds to silently shorten the study. The [WRDS CIZ conversion macro](https://wrds-www.wharton.upenn.edu/pages/wrds-research/macros/crsp-ciztosiz-macro/) provides the ordinary-common-share mapping; effective-dated CIZ security histories replace current tickers and stale name histories.

The source exposes vendor receipt time, event sentiment, event similarity days, story/entity/event identifiers and headline fields. A headline column is not proof of full-text entitlement or public redistribution permission. Missing event coding is common enough to require an explicit missingness treatment; it cannot be assumed to mean neutral or repeated news. Event similarity days is transformed as a novelty proxy. A separate publication timestamp, scoring completion time and a complete historical scoring-version archive have not been verified. The real-data protocol therefore needs an explicit archive/receipt-clock amendment before fitting.

The new adapter tests invented rows for duplicate-event handling, missing novelty, later receipt records and ambiguous company links. Passing these checks is not an empirical result. No licensed sample, security-level output, vendor manual or real-data metric is released here. Original audit attempts remain below as historical evidence.

The [AI policy review](DATA_BOUNDARY.md) adds a separate data-use boundary: subsequent automated checks expose only execution status and source integrity. Actual calculations and their findings stay in Cloud for direct authorized review. This does not resolve aggregate-publication permission.

## Initial local attempt

On 2026-11-05, an official PostgreSQL connection was attempted using the existing private libpq configuration. The WRDS server rejected authentication. The checked-in audit command reproduced this failure and wrote a sanitized private `audit.json`. No credentials, news rows or securities were printed or published.

This initial failure did not imply absence of a RavenPack subscription. It was resolved through the separate Cloud route above; course exports were not used as a substitute for access verification.

|Acceptance item|Verified?|Evidence still required|
|---|---|---|
|Authenticated read-only database/Cloud access|Yes, Cloud|Local PostgreSQL authentication remains a separate issue.|
|RavenPack/CRSP products, table versions and SELECT permissions|Access verified|Dataset update/scoring-vintage documentation still needed.|
|2010–2025 plus buffers|Broad coverage verified|Final eligible-universe completeness and source reconciliation still needed.|
|Timestamp and historical revision meaning|No|Actual vendor documentation/version, field-level checks.|
|Sentiment, novelty, relevance, event labels and identities|Partly|Actual schema and bounded ranges checked; archive/version assumptions remain.|
|Historical security mapping|Partly|CIZ effective dates and annual entity-day diagnostics checked; final selected-universe loss audit pending.|
|Feed completeness vs no news|No|Daily source-coverage reconciliation.|
|Headline/full-text access|No|Explicit entitlement; not inferred from analytics.|
|Raw/derived/model/aggregate dissemination|No|Applicable institution/vendor conditions and documented permitted outputs.|

After access is restored, run metadata discovery first. Review exact tables before bounded coverage queries; do not scan a full vendor corpus speculatively. Save private schema fingerprints, documentation references and sample-loss counts. The discovery command deliberately does not infer completeness from table names or privileges. Freeze real-data protocol only after the remaining checks; otherwise record a new version and the precise unresolved limitations.

## Missing-return follow-up, 2026-11-06

Authenticated supported Cloud database queries compared quarterly/annual CIZ, legacy CRSP, historical CCM-linked Compustat daily total-return candidates, delisting events and distribution records. Exact return durations, previous-price dates and execution closes are retained privately. The [return-review record](RETURN_REVIEW.md) distinguishes independently checked source values, stale accounting marks and assumed terminal settlement. It does not certify missing cash entitlements, complete quote execution or an unrestricted output license. All earlier audits and failures remain.
