# Governance AI Studio

Governance AI Studio extends the IV&V Governance Platform into a project-scoped assurance workspace. It combines deterministic checks and evidence with optional model-assisted analysis. Independent review and accountable human gate decisions remain part of the process.

## Current capability

- Create a governed assessment plan from a GitHub URL, pasted or uploaded FRS requirements (TXT, Markdown, DOCX, PDF), an optional deployed URL, runtime logs, and a selected assessment window.
- Require an authorization attestation, named owner, approval/ticket reference, exact scope, exclusions, and expiry window before a web target can be registered.
- Extract candidate requirements with source-line references; redact recognized secrets and PII before candidate text is retained.
- Draft deterministic, trace-linked functional and non-functional test outlines from candidate requirements. Drafts require human review, do not invent performance thresholds, and are not executable test evidence.
- Summarize runtime error, HTTP status, and security-signal counts; scan for known secret and PII patterns while discarding raw log text. This is pattern-based detection, not a guarantee that all sensitive data is found.
- Run bounded repository-local Semgrep CE (bundled offline rules), Gitleaks, Trivy filesystem scans and Ruff checks in the backend image. Static tool output is reduced to normalized findings plus a digest; raw output is discarded. Trivy downloads its vulnerability database at scan time and needs outbound access to its configured database mirrors.
- Run an explicitly owner-authorized framework assessment: Playwright Chromium performs an unauthenticated browser smoke check; Schemathesis sends OpenAPI-generated requests using Hypothesis with a 30-second budget, 1 request/second, one worker, 25 generated examples per operation maximum, five-second request timeout, and redirects disabled; k6 sends only paced GET requests with redirects disabled and a maximum of three virtual users for 30 seconds, using owner-entered p95 latency and failed-request thresholds. These dynamic runners have hard request/time bounds, no credentials, and require an authorized target window plus a separate staging/test confirmation. Schemathesis can invoke methods declared in the OpenAPI schema, so it must only be used against a safe non-production API.
- Emit allow-listed JSON application logs with pattern-based sensitive-value redaction and run a synthetic log canary against the Studio logger. This canary verifies the Studio's own logging boundary; it does not inspect or instrument the assessed application's logs. Redaction patterns cannot guarantee detection of every secret format.
- Record run metadata and input hashes in the append-only audit ledger.
- Link into the existing read-only repository audit, deterministic source detectors, findings, gates, and evidence-pack exports.
- Run an owner-authorized OWASP ZAP passive baseline or explicitly confirmed active assessment. Both are limited to the supplied HTTPS host/path and bounded crawl. Active assessment is restricted to an attested staging/test target, low attack strength, one thread per host, a three-minute cap, and no authentication. Normalized findings, scan mode, ZAP version, and ledger references appear in the assessment.
- Run an optional AI triage step over at most 30 normalized, masked scan findings through the existing multi-provider gateway, Security & Privacy role, zero-LLM control, and per-run model-call budget. The model cannot contact the target; its output is labeled advisory and is not counted as evidence.

The backend container image bundles the CLI tools and Playwright Chromium. Rebuild and publish the backend image after changing the tool pins; deployment must pull the newly published image before these framework controls become available. The running image's catalog reports actual executable availability. Creating an assessment plan records the web target but does not contact it. Dynamic framework runs require explicit owner authorization, an unexpired scope, and a separate staging/test attestation. Active ZAP and Schemathesis can affect application state or availability; the latter may invoke methods from the API schema. No database data extraction or production load test is implemented. CMMI artifacts are traceable readiness evidence, not an independent appraisal or a claim of Level 5 compliance.

## Run locally with Docker Compose

1. Copy `.env.example` to `.env` and replace every placeholder with unique values. Generate `ZAP_API_KEY` as a long random secret and keep `.env` private. The ZAP API is only reachable on the private Compose network and is not published to the host.
2. Start the services:

   ```sh
   docker compose up --build
   ```

3. Open `http://localhost:8080`.

MongoDB is not published to the host and is isolated on an internal database network that the ZAP container does not join. The application connects with a database-scoped account; the MongoDB root account is reserved for initialization. `EDGE_SIGNING_SECRET` must be stable across restarts and at least 32 random bytes. `CORS_ORIGINS` should list only the trusted browser origins when deployed. Add an LLM key only if you intend to enable model calls.

## Docker Hub publishing

The GitHub Actions workflow builds both images on pushes and pull requests, then publishes on pushes to `main`, version tags (`v*.*.*`), or a manually dispatched run. Configure these repository Actions secrets before publishing:

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN` (a Docker Hub access token with write permission)

Images are published as `DOCKERHUB_USERNAME/governance-ai-studio-backend` and `DOCKERHUB_USERNAME/governance-ai-studio-frontend`. Version tags and commit SHA tags are emitted; `latest` is emitted from `main`. The two Dockerfiles can also be built locally from the repository root.

## Safety and assurance boundary

The platform is intended for assessments authorized by the system owner. Submitting a URL is not permission to test it. The backend rejects non-HTTPS targets, embedded credentials, query strings, local hostnames, and targets resolving to non-public IP addresses. It serializes scans, limits crawls to five levels, 50 child links per page, and two minutes, and restricts findings to the exact host/path. Active mode additionally requires an explicit staging/test attestation and uses LOW attack strength, one thread per host, and a three-minute cap. Repeat runs are limited to one per assessment per ten minutes; scanner version and findings are recorded in the audit ledger. The scanner has no published port and cannot connect directly to MongoDB. DNS rebinding and redirects remain deployment-level risks; production use should add outbound firewall/egress policy. Active scans can still alter application state or affect availability; these controls do not make unauthorized testing permissible. No database data extraction or production load test is implemented.

The workbook's IV&V process, artifact register, stage gates, traceability, metrics, agent independence, and high-maturity evidence principles are design inputs. Formal maturity is determined at organizational appraisal; generated documents are supporting evidence, not certification.

## Development checks

Run the deterministic planning unit checks with:

```sh
cd backend
python -m unittest discover -s tests -p 'test_studio_planning_unit.py'
```

The integration suites in `backend/tests` target a running preview deployment and are not all self-contained local tests.
