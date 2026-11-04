# DeepResearch AI FastAPI Backend Audit

**Scope:** Existing authentication and research API modules, global exception handling, and related worker/database behavior.  
**Method:** Read-only source review; no code or runtime behavior was changed as part of the audit.  
**Overall:** Two medium-severity reliability/state-consistency findings. No confirmed cross-user research access issue was found in the inspected routes.

## Prioritized findings

| # | Severity | File | Lines | Vulnerability | Confidence |
|---|----------|------|-------|---------------|------------|
| 1 | 🟡 MEDIUM | [app/modules/research/router.py](./app/modules/research/router.py), [app/worker.py](./app/worker.py) | router.py 52–64; worker.py 121–124 | **Enqueue failure can leave job state inconsistent.** If Redis accepts an enqueue but its acknowledgment is lost, the API marks the research failed and returns 503, although the worker can still run it. The worker skips cancelled jobs but does not require the job to remain queued before starting. | 9/10 |
| 2 | 🟡 MEDIUM | [app/modules/research/services.py](./app/modules/research/services.py), [app/worker.py](./app/worker.py) | services.py 155–166, 189–228; worker.py 116–125, 404 | **Cancellation can race with worker state transitions.** A queued-job abort timeout is swallowed and cancellation is persisted, while a worker that already passed its cancelled check can continue. The completion path can then overwrite the job status with completed and emit a conflicting terminal event. | 8/10 |

### Recommended fixes

1. Make enqueueing recoverable, for example with an outbox/reconciliation mechanism. Make worker startup claim only jobs that are still queued using an atomic conditional transition. Treat uncertain enqueue outcomes as pending until reconciled.
2. Make worker startup and completion conditional state transitions under a row lock or compare-and-set. Do not report a cancellation as complete until the worker has confirmed it stopped; represent an unconfirmed abort as pending.

## Coverage notes

- **Authentication:** Register, login, refresh, logout, and current-user routes were inspected. Access-token validation checks token type, user/session association, session revocation and expiry, and active-user status. Refresh rotates the stored token hash and checks revocation, expiry, and active-user status. No specific auth logic defect was confirmed in the inspected paths.
- **Cookie deployment configuration:** The secure-cookie setting defaults to `False` and can be configured. The production setting and TLS deployment were not established in this source-only review; verify that production cookies use `Secure` and HTTPS.
- **Research ownership:** Detail, cancel, events, report, tasks, and sources routes retrieve research using both the research ID and current user's ID before returning associated data. Listing is scoped to the current user. No cross-user access issue was confirmed in these routes.
- **Pagination:** The list endpoint requires `page >= 1`, restricts `limit` to 1–100, and applies both values to a user-scoped query.
- **SSE and event IDs:** The endpoint rejects negative or non-integer `Last-Event-ID`; streaming fetches later events in ascending sequence order. Concurrent sequence allocation was inspected and no concrete race was substantiated: writers update/lock the parent research row before reading the maximum sequence, with SQLAlchemy's default autoflush. This relies on autoflush remaining enabled.
- **Schemas/statuses and exception responses:** Request/response schemas and route status declarations were inspected. Global handlers normalize application errors, validation errors, HTTP errors, and unexpected errors. Unexpected errors return a generic 500 response and are logged with server-side traceback; no client-facing leak from that handler was found.
- **Worker error details:** Worker exceptions are stored in the research job and failure-event payload. Whether those messages contain sensitive upstream data cannot be established from the inspected code; review the data sources and consider sanitizing persisted/user-streamed error text.
- **Transactions:** Auth session/token updates and cancellation/event persistence use database commits; cancellation rolls back on failure. Research creation is committed before enqueueing, and enqueue-failure handling is a separate transaction, contributing to finding 1. Worker completion commits report, sources, job status, and terminal event together.

## Files and functions reviewed

- [app/modules/auth/router.py](./app/modules/auth/router.py): register, login, refresh, logout, and current-user routes.
- [app/modules/auth/dependencies.py](./app/modules/auth/dependencies.py): current-user JWT and session validation.
- [app/modules/auth/services.py](./app/modules/auth/services.py): registration, authentication, session creation, refresh rotation, and revocation.
- [app/modules/research/router.py](./app/modules/research/router.py): create, list, detail, cancel, SSE, report, task, and source routes.
- [app/modules/research/services.py](./app/modules/research/services.py): research queries, cancellation, event persistence, and SSE event retrieval.
- [app/worker.py](./app/worker.py): job startup, completion, failure handling, and terminal event persistence.
- [app/core/exceptions.py](./app/core/exceptions.py), [app/main.py](./app/main.py): global exception handlers and registration.
- Related schemas, models, configuration, and database session setup.
