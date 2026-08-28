# Architecture decisions

## 2026-08-28: Publish guard keeps last-good data

Status: accepted

The collector may persist raw evidence even when every candidate is unknown, excluded, or below the cutoff. It must not replace `summary/latest.json` when the current public ranking is empty. This separates evidence retention from publication and makes an empty dashboard an explicit failure rather than a valid update.

## 2026-08-28: Select history by timestamp, not record count

Status: accepted

The 24-hour window is selected from the UTC timestamp encoded in raw object keys. The pipeline lists only the current and cutoff UTC dates, filters to the exact interval, and sorts chronologically. Missed or delayed runs therefore do not stretch “24h” into an older fixed number of snapshots.

## 2026-08-28: API-key-only operation is a sensor probe

Status: accepted

Until R2 credentials exist, the scheduled workflow performs one real YouTube collection and retains the single-snapshot result as a short-lived GitHub Actions artifact. It is labeled `probe`, is not presented as 24-hour production data, and does not replace the public demo. Once all R2 settings exist, the same workflow switches to raw persistence and last-good publication.

Classification diagnostics are retained as a separate short-lived artifact on every run, including blocked publications. The report contains public stream metadata needed to tune aliases, but never credentials or environment values.

## 2026-08-28: Discover broadly, verify the gaming category after enrichment

Status: accepted

The live search requests the documented `snippet` part without a category constraint, then verifies each candidate's `snippet.categoryId` from `videos.list`. Non-gaming candidates remain in raw evidence and diagnostics as explicitly excluded rows, but can never enter public rankings. This avoids treating an empty category-filtered search result as proof that no gaming streams are live while preserving the two-search-requests-per-run quota budget.

## 2026-08-28: Public data source is injected at build time

Status: accepted

The checked-in site remains a clearly labeled deterministic demo. A deployment may set `R2_PUBLIC_BASE_URL`; the build then injects the HTTPS `summary/latest.json` URL into the generated `dist/index.html`. Credentials are never embedded in the browser bundle.

## 2026-08-28: GitHub Pages deploys only the built dashboard

Status: accepted

Pages deployment uploads `dist/`, not the repository root. This keeps Python, tests, configuration, and raw fixtures outside the public site and guarantees that the same build validation used locally controls the deployed artifact.

## Format compatibility

The current public document uses `schema_version: 1`. Any future incompatible change requires an explicit reader/migration path. Unknown versions must not be silently rewritten or treated as version 1.
