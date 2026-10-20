# Scanner operations and acceptance

Use one backend process/replica and one dedicated private ZAP daemon. The in-process admission lock is not a distributed queue; multiple backend replicas are unsupported. ZAP has no published host port. Keep the existing Hostinger project and mongo_data volume.

## Lifecycle

The UI shows target, current stage, stage percentage when ZAP supplies it, passive queue size, elapsed wall time, and last heartbeat. Percentages are stage progress, never full application coverage. Poll failures and delayed heartbeats are visible. Stop requests are checked at progress checkpoints (normally two seconds, longer during API calls); cleanup must return before the terminal result is saved. AI triage is separately capped at 30 seconds.

A scanner job has a 600-second outer deadline, plus API stop/cleanup and optional AI analysis time. Spider and passive phases each have 120-second ceilings; active scanning has 180 seconds. Partial stages and alert-cap truncation result in partial coverage. Missing inputs and unauthenticated routes remain untested. Reaching 100 percent does not establish vulnerability coverage, successful exploitation, or database access.

On backend startup, orphan spider and active scans are stopped before new scans are accepted. Recovery failure blocks web scan admission until the operator checks/restarts ZAP and backend. Interrupted persisted jobs become interrupted rather than running forever. A failed stop blocks further web scans. New sessions are temporary rather than accumulating named session files. Optional AI failure retains scanner evidence. Finished attempts are archived in studio_scan_attempts; the authenticated history endpoint returns the latest 20 summaries. Studio exports the current evidence report as JSON.

The exact-origin low-strength profile excludes rule 10047 (scheme/port change), 90034 (internal cloud metadata), and 40044 (entity expansion availability test). Context scope alone is not a network firewall. Production needs enforced scanner egress controls, a durable worker queue with leases, tenant isolation, image digest pins, authentication/TLS, and retention policy. This change does not claim those are implemented.

## Deployment

The repository Compose and deploy/hostinger-studio.yml specify a 1536 MB Java heap inside a 3 GB container, allowing native/browser overhead. Keep existing secrets and matching ZAP key values. Publish/merge the code before pulling main images. Verify startup logs say `Using JVM args: -Xmx1536m`.

## Acceptance on an owned isolated staging target

1. Queue passive, then active jobs separately. Observe each stage and heartbeat.
2. Stop during crawling and during active scanning; confirm terminal cancelled status and scanner stop before a retry.
3. Restart backend mid-job; confirm interrupted status and orphan recovery.
4. Disconnect ZAP; verify actionable failed status and failure ledger event.
5. Delay AI or remove keys; ensure deterministic results survive.
6. Inspect result target, exclusions, timestamps, risk versus confidence, partial flags and ledger references. Inspect logs for API key absence.
7. Run the frontend build and lifecycle tests in CI. Repeat full integration using Docker after deployment; offline unit tests do not verify the deployed ZAP API or network scope.
