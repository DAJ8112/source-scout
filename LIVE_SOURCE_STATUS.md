# Live source status

Last manually checked: **2026-08-08**.

| Source | Result | Action |
|---|---|---|
| CVS Health Workday | Ready. The CXS endpoint returned nonzero jobs and all four saved facet IDs still matched their labels. | None. Facets are revalidated before every scan. |
| Veralto Phenom | Ready after reading the server-rendered `phApp.ddo.eagerLoadRefineSearch` listing data and same-host `rel=next` pagination. | None. Job details remain constrained to same-host JobPosting JSON-LD pages. |
| Box Happydance | Setup required. The official listing returned HTTP 403 to the connector-lab client. | Revalidate later or obtain explicit supported access from the site owner. The connector does not bypass the block, impersonate a browser, or add Playwright. |

These are current observations, not permanent guarantees. Run the manual live smoke command in
the README to recheck. Automated CI uses sanitized fixtures and never depends on volatile live counts.
