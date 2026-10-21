# Phase 1: access controls and trustworthy evidence

## Deployment

Use `deploy/hostinger-studio.yml` with the existing Compose project name and Mongo volume. Keep the backend, frontend and browser worker on the same published revision. Do not remove the database volume.

Set the following backend environment values before deployment:

```yaml
DEMO_MODE: "false"
BOOTSTRAP_ADMIN_TOKEN: "YOUR_CHOSEN_ACCESS_TOKEN"
```

Replace the example value with your chosen token. The supplied `REPLACE_...` placeholder is deliberately rejected at startup. Sign in using the exact configured token. The database stores its SHA-256 hash. Updating this environment value rotates the bootstrap token on the next backend startup. Keep your existing EDGE_SIGNING_SECRET and matching ZAP keys.

The frontend now displays a token sign-in screen before requesting project data. Public demo identity selection is available only with explicit `DEMO_MODE=true`. Existing seeded/demo tokens are revoked in normal mode; genuine administrator-issued tokens remain supported. The bootstrap administrator receives access to existing projects. Other users retain their existing project assignments.

## Compatibility and migration

### Existing ledger index compatibility fix

The original database can retain a unique `ledger_chain_seq` index on `(chain, seq)`. Phase 1 initially populated only `chain_id`; MongoDB indexes a missing `chain` as null, which can collide with older global records. This was reproduced with the deployed index definition and copied ledger records.

New v2 entries now populate both `chain_id: v2` and `chain: v2`. Both unique indexes remain in place. No old entries, hashes, sequence values, or legacy snapshot anchors are rewritten. No manual index deletion, database reset, or YAML change is required. Publish and redeploy the corrected backend, then retry the failed repository audit and approve a fresh or still-open browser plan. The earlier failed audit can have an incomplete current projection; its preserved historical snapshot remains available.

Persistent storage conflicts now produce a controlled HTTP 503 with a diagnostic reference. Approval remains uncommitted if the ledger cannot accept the event. Logs retain exception type, file basename, function and line numbers without exception messages, source lines or local values.

- Existing project IDs, report IDs, API route shapes, Mongo volume and scanner/browser services are retained.
- APIs now require authentication and project membership. Integrations that previously read protected records anonymously must send `Authorization: Bearer <issued-token>`.
- Platform administration requires a platform role; a project governance role alone no longer grants platform administration.
- A repository re-audit preserves previous findings, events, reports and audit metadata in immutable, hash-checked snapshots before replacing the current views. Reports and findings from those snapshots remain accessible by their original IDs. Snapshots begin with the first re-audit after this upgrade; previously deleted evidence cannot be recovered automatically.
- Repository history is exposed at `GET /api/repo-audit/{project_id}/history` and `GET /api/repo-audit/{project_id}/history/{version_id}`.
- Existing ledger records and hashes are never rewritten. New writes use a separate v2 chain with a Mongo unique sequence index and an anchored snapshot of legacy records. A historically broken ledger remains reported as broken. The active chain and snapshot match are reported separately.
- The former ledger rebuild endpoint returns HTTP 410. A reviewed legacy acknowledgment records a reason and actor without declaring invalid history valid.

## Local verification

The regression suite covers planning, scanner adapters, ZAP lifecycle, workspace controls, a real local Chromium worker, authentication and project boundaries, HTML escaping, immutable repository history, and concurrent ledger insert behavior. The real MongoDB concurrency integration test requires `MONGO_TEST_URL`; GitHub Actions starts MongoDB 7 for that test.

Scanner execution is reported separately from findings. Missing tools, invalid output, timeouts and tool errors are not successful clean scans. Static findings retain tool provenance and remain explicitly unreviewed until independent assessment.

## Checks after deployment

1. Confirm the backend starts without bootstrap configuration errors.
2. In a fresh browser session, verify protected pages show sign-in and anonymous `/api/projects` returns 401.
3. Sign in, open an existing project, and download a report.
4. Run an authorized repository audit twice; verify the earlier snapshot and original report are still available.
5. Inspect ledger verification: distinguish v2 integrity, legacy integrity, and snapshot match.
6. Run bounded browser/scanner tests against an owned test application and inspect tool completion and evidence.

## Limits and rollback

This release does not certify CMMI maturity, guarantee complete security coverage, or validate every installed scanner against a live target. AI inference still requires a configured provider and applicable consent. MongoDB and full container builds must pass CI and deployment checks.

Audit replacement uses preserved snapshots plus current projections, not a multi-document transaction. An interrupted audit can leave an incomplete current view; retained history remains available. A per-repository lease prevents overlapping audits for 30 minutes. Very large archives and ledgers fail closed at documented code limits and require a reviewed offline migration.

Take a database backup before deployment. Rolling back old code also restores its old access behavior and may not understand v2 ledger entries or archived history. Restore the matching backup if a full application/data rollback is necessary; retain the upgrade backup for evidence preservation.
