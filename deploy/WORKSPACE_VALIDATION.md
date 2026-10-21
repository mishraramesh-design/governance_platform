# Local validation - 2026-10-21

## Passed

46 selected unittest checks:

| Suite | Checks |
| --- | ---: |
| Studio deterministic planning | 3 |
| Framework adapters and bounded ZAP policy | 10 |
| ZAP lifecycle | 4 |
| Workspace documents, contracts and provenance | 8 |
| Workspace HTTP API, orchestration, model policy and secret handling | 14 |
| Browser worker, request gates and real Chromium fixture tests | 7 |

The Chromium tests contacted only a disposable local HTTP fixture. The test-only resolver override is confined to the tests; the shipped worker rejects private target addresses. Tests verified real frame generation, visible-text assertions, secure filling without observation leakage, one-request write approval, blocked origins and stale control rejection.

Backend compilation and whitespace checks passed. Babel parsed/transformed all 86 frontend JS/JSX files. The actual workspace component rendered in a local fixture preview; the split panels and editable plan controls were inspected. Compose files and the Actions workflow parsed successfully. Browser control ports are not published in either Compose file. The browser smoke script also passed locally.

## Not claimed by local validation

- A full frontend production build: Windows filesystem permissions prevented dependency installation. CI has the required production build step.
- Docker image execution on this Windows host: no Docker CLI is available. CI builds the worker image, loads it and runs the smoke script as its non-root image user with the deployed capability/security settings.
- Live provider/model testing: provider calls were mocked in orchestration tests. Model keys and an appropriate maker-profile call ceiling must be configured for agent-driven workflows. Approved direct page checks do not require model calls during execution.
- MongoDB persistence end-to-end: orchestration tests used in-memory mocks. Deployed acceptance must verify evidence, archive/history and owner access against MongoDB.
- Hostinger deployment or complete target-application coverage. Publish all three images after CI succeeds, redeploy, then verify the workspace against an owned isolated application using the acceptance workflow in TESTING_WORKSPACE.md.

No public third-party target was scanned or attacked as part of this feature validation. PASS results describe approved assertions; the report records remaining unexecuted and unmapped requirements rather than claiming universal application coverage or a CMMI rating.
