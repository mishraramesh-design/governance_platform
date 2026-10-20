# Governance AI Studio

Governance AI Studio extends the IV&V Governance Platform into a project-scoped assurance workspace. It combines deterministic checks and evidence with optional model-assisted analysis. Independent review and accountable human gate decisions remain part of the process.

## Current capability

- Create a governed assessment plan from a GitHub URL, pasted or uploaded FRS requirements (TXT, Markdown, DOCX, PDF), an optional deployed URL, runtime logs, and a selected assessment window.
- Require an authorization attestation, named owner, approval/ticket reference, exact scope, exclusions, and expiry window before a web target can be registered.
- Extract candidate requirements with source-line references; redact recognized secrets and PII before candidate text is retained.
- Summarize runtime error, HTTP status, and security-signal counts while discarding raw log text.
- Record run metadata and input hashes in the append-only audit ledger.
- Link into the existing read-only repository audit, deterministic source detectors, findings, gates, and evidence-pack exports.
- Run a bounded unauthenticated OWASP ZAP baseline crawl after owner authorization. The scan is limited to the supplied HTTPS host/path, five crawl levels, 50 child links per page, and two minutes of crawling, followed by passive rules. Normalized findings, remediation guidance, ZAP version, and a ledger reference appear in the assessment.
- Route agent assistance through the existing multi-provider gateway, zero-LLM control, role profiles, and per-run model-call budget.

Creating an assessment plan records the web target but does not contact it. The separate ZAP baseline action requires the attested authorization owner, reference, scope, and unexpired window. It only performs unauthenticated crawl and passive rules. Active exploit-style DAST, authenticated scanning, database access tests, secret exfiltration, and load testing are not implemented. CMMI-related outputs are readiness evidence; the product does not claim a CMMI maturity level.

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

The platform is intended for assessments authorized by the system owner. Submitting a URL is not permission to test it. ZAP is configured for a bounded passive baseline only. The backend rejects non-HTTPS targets, embedded credentials, query strings, local hostnames, and targets resolving to non-public IP addresses. It serializes scans, limits each scan to five crawl levels, 50 child links per page, and two minutes of crawling, restricts findings to the exact host/path, limits repeat runs to one per assessment per ten minutes, and records scanner version and findings in the audit ledger. The scanner has no published port and cannot connect directly to MongoDB. DNS rebinding and redirects remain deployment-level risks; production use should add outbound firewall/egress policy. These controls do not make an unauthorized assessment permissible. No active exploit scan or production load test is included.

The workbook's IV&V process, artifact register, stage gates, traceability, metrics, agent independence, and high-maturity evidence principles are design inputs. Formal maturity is determined at organizational appraisal; generated documents are supporting evidence, not certification.

## Development checks

Run the deterministic planning unit checks with:

```sh
cd backend
python -m unittest discover -s tests -p 'test_studio_planning_unit.py'
```

The integration suites in `backend/tests` target a running preview deployment and are not all self-contained local tests.
