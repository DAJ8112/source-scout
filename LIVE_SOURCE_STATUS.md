# Live source status

Last implementation review: **2026-08-11**. Fixture-backed status is recorded below; live
availability remains intentionally opt-in because these sites can rate-limit or reject automated
clients without notice.

| Source | Result | Action |
|---|---|---|
| CVS Health Workday | Ready. The CXS endpoint returned nonzero jobs and all four saved facet IDs still matched their labels. | None. Facets are revalidated before every scan. |
| Veralto Phenom | Ready after reading the server-rendered `phApp.ddo.eagerLoadRefineSearch` listing data and same-host `rel=next` pagination. | None. Job details remain constrained to same-host JobPosting JSON-LD pages. |
| Box Happydance | Setup required. The official listing returned HTTP 403 to the connector-lab client. | Revalidate later or obtain explicit supported access from the site owner. The connector does not bypass the block, impersonate a browser, or add Playwright. |
| CCC Workday | Ready in fixtures through the standard Workday CXS API. | Run the opt-in smoke before first monitoring use. |
| Rivian iCIMS/Jibe | Ready in fixtures through `/api/jobs`, including offset pagination and complete listing payloads. | Run the opt-in smoke before first monitoring use. |
| Mondelēz Workday | Ready in fixtures through `myworkdaysite.com/recruiting/{tenant}/{site}` coordinate discovery. | Run the opt-in smoke before first monitoring use. |
| GlobalFoundries Eightfold | Ready in fixtures through the current Eightfold site, `start` pagination, and JobPosting JSON-LD. | Run the opt-in smoke before first monitoring use. |
| Kwik Trip Phenom | Ready in fixtures with embedded-result pagination and escaped-description decoding. | Run the opt-in smoke before first monitoring use. |
| Honeywell Oracle CE | Ready in fixtures with vanity-page API discovery and expanded requisition details. | Run the opt-in smoke before first monitoring use. |
| Bloomberg Avature | Setup required when the live endpoint returns HTTP 406. Fixture parsing is covered. | Revalidate later or obtain supported access; the connector does not impersonate a browser or bypass the rejection. |
| Toyota Phenom | Ready in fixtures and scoped to Technology, Data & Analytics. | Keep the category URL unchanged and run the opt-in smoke before first monitoring use. |
| JPMC Oracle CE | Ready in fixtures with direct-host API discovery and public vanity canonical links. | Run the opt-in smoke before first monitoring use. |
| PRGX Hirebridge | Ready in fixtures with iframe discovery and strict host/client-ID traversal. | Run the opt-in smoke before first monitoring use. |

These are current observations, not permanent guarantees. Run the manual live smoke command in
the README to recheck. Partial traversals save observed jobs but never advance missing/closed job
state. Automated CI uses sanitized fixtures and never depends on volatile live counts.
