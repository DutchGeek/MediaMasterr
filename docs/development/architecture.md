# Architecture

MediaMasterr is a FastAPI application with a small number of long-lived runtime
components:

- the API server
- the APScheduler schedule runner
- the in-process background worker
- the database and service layer

## Process Model

The app starts as one process and then initializes the main subsystems:

1. Load settings and connect to the database.
2. Bootstrap enabled media-service clients.
3. Start the scheduler.
4. Start the background worker loops.
5. Serve the API and frontend assets.

This keeps deployment constrained to one app process that manages both scheduled work and
queued background jobs.

## Request Flow

- The frontend talks to the FastAPI backend.
- Routes validate input, read or update the database, and call service helpers.
- Long-running or retryable work is placed onto the background job queue.
- The worker claims queued jobs and runs them in-process.

## Scheduler

The scheduler stores task definitions in the database and mirrors enabled tasks
into APScheduler jobs.

- Cron and interval tasks are supported.
- Manual tasks are present in the UI but are not scheduled.
- Main-server-dependent tasks stay disabled until a main media server exists.
- Task changes are persisted first, then reflected in the live scheduler.

## Background Worker

The worker polls for queued jobs and executes them one at a time per worker
loop.

- Idle polling backs off to reduce churn.
- Job claims are durable so stale jobs can be reset on startup.
- The worker handles service toggles, task runs, and file-ops jobs.

## Data Flow

MediaMasterr uses the database as the source of truth for:

- general settings
- service configuration
- task schedules
- reclaim candidates
- requests and protected media
- reclaim history and background job records

Media metadata is synced from connected services and then used to drive candidate
scanning, deletion routing, and UI indicators.

## Extension Points

- `backend/api/routes/` for HTTP endpoints
- `backend/tasks/` for domain workflows
- `backend/services/` for external integrations
- `backend/core/worker.py` for queue processing behavior
- `backend/scheduler.py` for scheduled task behavior

## MIE Correlation Pipeline

The Media Intelligence Engine correlation pipeline is implemented in:

- `backend/services/mie/correlation_service.py`
- `backend/services/mie/correlation_engine.py`
- `backend/services/mie/correlation_models.py`

Request flow:

1. Resolve one local media subject (`movie` or `series`).
2. Build a per-request correlation context.
3. Run provider modules in sequence.
4. Merge provider contributions into one graph response.

Current provider modules:

- identity provider
- request provider (Overseerr)
- ARR provider (Radarr/Sonarr refs)
- torrent provider (qBittorrent + computed state)
- filesystem provider
- artwork provider
- timeline provider
- health provider

The public contract is exposed at `GET /api/mie/media/{media_id}/graph` and is
designed to remain stable for UI and automation consumers.

## Operations Graph Consumer Pipeline

Operations intelligence is now layered on top of correlation graphs:

- `backend/services/mie/operations_engine.py`
- `backend/services/mie/issue_detector.py`
- `backend/services/mie/issue_rules.py`

Request flow:

1. Load media assets and request graph snapshots through correlation service.
2. Evaluate issue rules from graph-only signals.
3. Aggregate health, confidence, graph summary, and timeline highlights.
4. Expose enriched operations workspace payloads without duplicating provider logic.

Downloads lifecycle intelligence is implemented in:

- `backend/services/mie/downloads_intelligence.py`

This service:

1. Scans configured downloads roots from filesystem index entries.
2. Correlates objects to active torrents and identity graph evidence.
3. Assigns exactly one lifecycle classification per object.
4. Emits explainable cleanup classifications and recommendations.

No automatic deletion is performed in this phase; the service classifies and
recommends only.

## Design Constraints

- Safety defaults matter more than automation.
- Candidate state must remain auditable.
- Deletion should route through the most specific service available.
- Main-server-dependent workflows must fail closed when the main server is absent.

