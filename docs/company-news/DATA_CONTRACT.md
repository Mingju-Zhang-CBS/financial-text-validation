# Normalized input and rights contract

These interfaces describe locally processed tables. They are not claims about actual RavenPack column names or product availability.

|Table|Required fields|Contract|
|---|---|---|
|News|article_id, entity_id, published_at, vendor_available_at, sentiment, novelty, event_type|UTC-aware timestamps; article identity stable across event rows; sentiment may be missing; normalized sentiment [-1,1], novelty [0,1]. Additional occurrence/revision/relevance/source/story fields retained privately for audit.|
|Links|entity_id, permno, valid_from, valid_to|Inclusive historical date validity; ambiguous concurrent links quarantined; mapping-loss table required.|
|Daily prices|permno, date, total_return, market_return, close, market_cap, dollar_volume, share_code, exchange|One historical security/session row; total returns incorporate distributions and delisting treatment; market series consistent across firms; USD units; no silent internal-session gaps.|
|Calendar|exchange session date, close timestamp|Authoritative session schedule; full sessions, holidays and early closes documented. Synthetic checks use weekdays and are not a real exchange calendar.|

Validation must distinguish missing publication time, unknown vendor availability, missing score, unmapped entity, ambiguous mapping, duplicate story, absent price, inactive listing, universe exclusion and label-window truncation. Record row and unique-article counts after each filter, by year and split. Retain unmatched observations privately instead of silently dropping them.

The real adapter must verify relevance thresholds and taxonomy version before freezing; no arbitrary RavenPack field scale or score sign is assumed. CUSIP8/CUSIP9 normalization alone does not establish date-valid identity. See [WRDS's historical linking discussion](https://wrds-www.wharton.upenn.edu/pages/wrds-research/database-linking-matrix/linking-ravenpack-with-crsp/).

## Publication classes

|Material|Current release rule|
|---|---|
|Independent code, protocol, invented fixtures|Public; MIT for new code.|
|Commercial news, structured analytics, security-level outputs|Private; subject to institutional/vendor agreements.|
|Fitted models and reconstructible derived artifacts|Private unless specifically cleared.|
|Aggregate real-data metrics, charts, coefficients|Pending the applicable permission; aggregation is not a release grant.|
|Headlines/full text|Separate entitlement and dissemination review; structured scores do not establish text access.|
|Chinese interview notes and original submissions|Local only; original collaborators remain attributed.|

The [WRDS terms](https://wrds-www.wharton.upenn.edu/users/tou/) describe supported programmatic access, account restrictions and required credit. No website login/query automation is part of this implementation. Keep data and audit evidence in ignored `private-data/` or outside the public repository; ignore rules do not replace an explicit publication allowlist and history scan.
