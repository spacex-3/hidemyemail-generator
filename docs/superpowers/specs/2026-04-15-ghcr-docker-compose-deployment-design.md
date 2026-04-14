# GHCR Docker Compose Deployment Design

## Goal

Package the project as a GitHub-built Docker image published to GHCR so a VPS can deploy it with only a `docker-compose.yml` file and `docker compose up -d`, while preserving existing generated email history through a bind-mounted data directory.

## Scope

This design covers:

- Container image build for the existing web dashboard server
- GHCR publishing from GitHub Actions
- Docker Compose deployment with all runtime configuration in the compose file
- Backward-compatible persistent storage so historical `emails-*.txt` files can be migrated into Docker without format changes
- README updates documenting VPS deployment and migration steps

This design does not change:

- Core Hide My Email generation and reservation logic
- Apple authentication flow or session semantics
- Web UI behavior and account management features
- Local non-Docker usage via `python cli.py serve`

## Requirements

1. The repository must build a Linux Docker image suitable for direct VPS deployment.
2. GitHub must publish the image to GHCR as a public package.
3. The VPS deployment path must require only a `docker-compose.yml` file plus a local `data/` directory.
4. All runtime configuration used by Docker deployment must be declared in `docker-compose.yml`.
5. Existing `emails-*.txt` files must remain usable without conversion.
6. Existing local Python usage must remain backward compatible when `DATA_DIR` is not set.
7. Session files may be recreated by logging in again after migration; preserving existing session-password decryptability across machines is not required.

## Architecture

### Runtime layout

Docker deployments will use a single bind-mounted data root:

```text
./data/
├── sessions/
└── emails-<apple-id>.txt
```

The container will mount this directory at `/app/data` and set:

```text
DATA_DIR=/app/data
```

When `DATA_DIR` is present:

- session persistence lives under `/app/data/sessions`
- generated email history lives under `/app/data/emails-*.txt`

When `DATA_DIR` is absent:

- behavior remains unchanged
- sessions continue using `sessions/`
- emails continue using `emails-*.txt` in the working directory

### Storage abstraction

The codebase currently hardcodes relative paths in two places:

- `icloud/auth.py` → `SESSIONS_DIR = "sessions"`
- `main.py` → `emails-{account}.txt`

The implementation will introduce a small shared path helper so both local Python usage and Docker usage resolve storage paths consistently.

Recommended helper behavior:

- `DATA_DIR` unset → return legacy relative paths
- `DATA_DIR=/app/data` → return `/app/data/sessions` and `/app/data/emails-*.txt`

This keeps migration simple while avoiding duplicated path-building logic.

### Container entrypoint

The image will run the existing server mode only:

```bash
python cli.py serve --port 8080
```

The container does not need a process manager beyond Docker itself.

### Compose deployment model

The repository will include a reference `docker-compose.yml` that uses:

- image: `ghcr.io/spacex-3/hidemyemail-generator:latest`
- port mapping: `8080:8080`
- environment:
  - `DATA_DIR=/app/data`
- bind mount:
  - `./data:/app/data`
- restart policy:
  - `unless-stopped`

No `.env` file is required. The compose file is self-contained.

### GHCR publication

GitHub Actions will build and publish the image on pushes to `main`.

The workflow will:

1. check out the repo
2. log in to GHCR using `GITHUB_TOKEN`
3. build the image from `Dockerfile`
4. publish tags:
   - `latest`
   - commit SHA tag

Because the package is intended to be public, VPS deployment does not require `docker login`.

## Implementation Approach Options

### Option 1 — Minimal direct path edits

Change `icloud/auth.py` and `main.py` independently to read `DATA_DIR` and assemble their own paths.

**Pros**
- smallest patch
- fast to implement

**Cons**
- path logic duplicated
- easier to drift if future storage files are added

### Option 2 — Shared storage path helper (recommended)

Introduce a tiny helper module for persistent file paths and update `icloud/auth.py` and `main.py` to use it.

**Pros**
- one source of truth for storage layout
- clearer backward-compatibility logic
- easier future Docker/storage work

**Cons**
- one extra file
- slightly broader change than direct inline edits

### Option 3 — Full storage refactor

Create a richer storage abstraction for sessions, generated emails, and future state.

**Pros**
- extensible long term

**Cons**
- unnecessary scope for this deployment goal
- higher regression risk

## Recommendation

Use **Option 2**.

It keeps the Docker change focused while avoiding scattered path rules. The code stays easy to reason about: Docker sets `DATA_DIR`, and all persistent files resolve through one helper.

## Components

### 1. Docker image definition

Add `Dockerfile` with these characteristics:

- base image: `python:3.13-slim`
- working dir: `/app`
- copy dependency metadata first, then install requirements
- copy application source
- expose port `8080`
- default command: `python cli.py serve --port 8080`

Add `.dockerignore` to exclude:

- `.git`
- `.worktrees`
- `venv`
- `__pycache__`
- `sessions`
- `data`
- generated email text files
- test caches and similar local artifacts

### 2. Persistent path helper

Add a small helper module, for example `storage_paths.py`, that provides functions such as:

- `get_data_dir()`
- `get_sessions_dir()`
- `get_emails_file(account: str)`

Behavior:

- if `DATA_DIR` unset or blank → legacy relative paths
- if `DATA_DIR` set → absolute paths beneath that directory
- create `sessions` directory lazily where needed

### 3. Application integration

Update:

- `icloud/auth.py` to use `get_sessions_dir()`
- `main.py` to use `get_emails_file(account)` for both load and append paths

This preserves the current file format and dashboard behavior.

### 4. Compose reference file

Add a repository `docker-compose.yml` that documents the target VPS usage directly.

The compose file will define all runtime settings inline and require no supplemental env file.

### 5. GitHub Actions workflow

Add `.github/workflows/docker.yml` that:

- triggers on push to `main` and optionally on manual dispatch
- sets package metadata for GHCR
- builds and pushes the Docker image
- tags `latest` and `${{ github.sha }}`

### 6. Documentation

Update `README.md` with:

- Docker / VPS deployment section
- example `docker-compose.yml`
- migration steps for copying `emails-*.txt` into `./data/`
- note that accounts can be re-added through the dashboard after migration

## Data Flow

### Fresh Docker deployment

1. User creates `docker-compose.yml`
2. User runs `docker compose up -d`
3. Docker starts container with `DATA_DIR=/app/data`
4. App reads/writes persistent files under mounted `./data`
5. User logs in through dashboard
6. Sessions are created in `./data/sessions`
7. Generated emails are appended to `./data/emails-*.txt`

### Migration from current Python deployment

1. User creates VPS `data/` directory
2. User copies existing `emails-*.txt` files into `./data/`
3. User starts Docker deployment
4. App loads historical email entries from migrated files
5. User logs in again through dashboard
6. New sessions are stored in `./data/sessions`
7. Generation continues and appends to the same migrated email files

## Error Handling

- If `DATA_DIR` points to a non-writable mount, the existing file operations will fail visibly through current error paths; README should note that `./data` must be writable.
- If no historical email files are present, startup remains valid; dashboard simply loads empty history.
- If old session files cannot be used after migration, the dashboard continues to work once the user re-authenticates.
- If the GHCR image is unavailable temporarily, deployment fails at image pull time rather than during runtime.

## Testing Strategy

1. Add unit tests for storage path resolution:
   - no `DATA_DIR` → legacy paths
   - `DATA_DIR=/app/data` → Docker paths
2. Add/adjust tests for email history loading and saving through the helper path
3. Add/adjust tests for session directory resolution if practical without external network calls
4. Build the Docker image locally to validate container startup command
5. Verify compose configuration shape by inspection and README examples

## Rollout Plan

1. Add path helper and tests
2. Update `main.py` and `icloud/auth.py` to use helper
3. Add Dockerfile, `.dockerignore`, compose file, and workflow
4. Update README with deployment + migration instructions
5. Run unit tests and a local Docker build

## Success Criteria

- Local Python execution still works without `DATA_DIR`
- Docker deployment works with `docker compose up -d`
- Historical `emails-*.txt` copied into `./data/` are visible in the dashboard after startup
- New emails append to the same migrated files
- GitHub can publish a public GHCR image from `main`
