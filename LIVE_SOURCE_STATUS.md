# Live source status

Last manually checked: **2026-08-11**. Live availability remains intentionally opt-in because
these sites can rate-limit or reject automated clients without notice.

| Source | Result | Action |
|---|---|---|
| CVS Health Workday | Ready. The CXS endpoint returned nonzero jobs and all four saved facet IDs still matched their labels. | None. Facets are revalidated before every scan. |
| Veralto Phenom | Ready after reading the server-rendered `phApp.ddo.eagerLoadRefineSearch` listing data and same-host `rel=next` pagination. | None. Job details remain constrained to same-host JobPosting JSON-LD pages. |
| Box Happydance | Setup required. The official listing returned HTTP 403 to the connector-lab client. | Revalidate later or obtain explicit supported access from the site owner. The connector does not bypass the block, impersonate a browser, or add Playwright. |
| CCC Workday | Ready. Live CXS validation returned jobs. | None. |
| Rivian iCIMS/Jibe | Ready. Live `/api/jobs` validation returned jobs. | None. |
| Mondelēz Workday | Ready. Live `myworkdaysite.com` CXS discovery returned jobs. | None. |
| GlobalFoundries Eightfold | Setup required live: the site presented a CAPTCHA challenge. Fixture parsing covers `start` pagination and JobPosting JSON-LD. | Revalidate later or obtain supported access; no challenge bypass is attempted. |
| Kwik Trip Phenom | Ready. Live embedded-result validation returned jobs. | None. |
| Honeywell Oracle CE | Ready. Live vanity-page API discovery returned requisitions. | None. |
| Bloomberg Avature | Ready in this smoke run. The connector still maps a live HTTP 406 to visible setup-required state when access is rejected. | Revalidate if access state changes; no browser impersonation or bypass is used. |
| Toyota Phenom | Ready. Live validation returned jobs from the Technology, Data & Analytics category. | Keep the category URL unchanged. |
| JPMC Oracle CE | Ready. Live direct-host API discovery returned requisitions with public canonical links. | None. |
| PRGX Hirebridge | Setup required live: the PRGX page returned HTTP 403. Fixture parsing covers iframe discovery and strict host/client-ID traversal. | Revalidate later or obtain supported access; no access bypass is attempted. |

These are current observations, not permanent guarantees. Run the manual live smoke command in
the README to recheck. Partial traversals save observed jobs but never advance missing/closed job
state. Automated CI uses sanitized fixtures and never depends on volatile live counts.
