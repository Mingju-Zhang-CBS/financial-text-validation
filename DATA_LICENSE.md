# Data rights and attribution

The bundled numerical observations and policy-statement bodies come directly from the **Board of Governors of the Federal Reserve System**. Its [website policy](https://www.federalreserve.gov/disclaimer.htm) states that Board website information is generally public domain unless otherwise indicated, permits copying/distribution and requests source attribution. This project includes Board policy text and H.10 numerical releases, with no identified third-party copyrighted passages, website imagery, seals, logos or official insignia.

The source is the Board; this independent project is not affiliated with or endorsed by it. The MIT license applies to newly authored software and documentation, not an exclusive claim over government information. Third-party software retains its respective license.

## Exact input scope

- **Text:** monetary-policy statement bodies linked as statements from the official 2009–2020 historical meeting indexes and 2021–2024 calendar entries. Publication dates are checked against the URL and displayed release date. Release metadata, navigation, share controls and voter rosters are excluded from model text. Both scheduled and extraordinary statements in the specified universe are retained before documented exact-duplicate and coverage filtering.
- **Prices:** USD per EUR reference observations extracted from dated archived H.10 releases, January 2009 through February 2025. The [Board's H.10 documentation](https://www.federalreserve.gov/releases/h10/about.htm) distinguishes the non-revised release archive from subsequently updated historical country series. This project keeps the earliest encountered published observation, rather than overwriting it with a later vintage.
- **Release calendar:** official H.10 releaseDates.json, and the official meeting-index links used for discovery. Every fetched page has a raw SHA-256, URL and byte count in the data manifest. Raw HTML is cached locally when fetching; only normalized text/numbers and provenance are redistributed.

These are reference prices, not a licensed exchange execution feed. No commercial news corpus, employer data, course Reuters/RavenPack data, user credentials or paid endpoint is used. XForecast remains a separate candidate benchmark; its paper's license is not treated as permission for third-party news data.

## Reproduction and corrections

The packaged CSV snapshot is immutable for this research version and verified by its SHA-256 before modeling. Historical pages can be edited at their source; a new fetch creates a new data version, not proof that statement bytes are identical to the original release. The Board explicitly describes archived H.10 releases as not subsequently revised, making them preferable to current-vintage prices for feature-availability checks. Publication clocks remain separate from observation clocks.

Sources: [reuse policy](https://www.federalreserve.gov/disclaimer.htm), [H.10 release archive](https://www.federalreserve.gov/releases/h10/default.htm), [H.10 methodology](https://www.federalreserve.gov/releases/h10/about.htm), [FOMC historical materials](https://www.federalreserve.gov/monetarypolicy/fomc_historical.htm), [meeting calendars](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm). Snapshot metadata and per-document source links are in [the data manifest](financial_text_validation/data/manifest.json).
