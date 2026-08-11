# tyk-dup-listen-path-checker

A standalone Python CLI that connects directly to a Tyk Dashboard's REST API
and reports any APIs that share the same effective route — i.e. the same
`(domain, listen_path)` pair. Two APIs bound to the same route is a common
source of "why is my traffic going to the wrong API" bugs, and it's easy to
introduce by accident (cloned APIs, copy-pasted OAS imports, a domain field
left blank on two different APIs).

This tool exists for people who don't have an MCP client set up and just want
`pip install`/`uv run` + a Dashboard API key to get an answer — no MCP
server, no Tyk-provided tooling required.

## Requirements

- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/)** — this project's package/dependency
  manager. Everything below (`uv sync`, `uv run`, ...) is a single
  self-contained tool; it also downloads a matching Python for you if you
  don't already have 3.11+ installed.
- **git**, to clone the repo.
- Network access to a Tyk Dashboard, and a Dashboard API key with at least
  read access to APIs (**Dashboard → User Profile → API Access
  Credentials**).

## Installation

**1. Install uv** (skip if you already have it):

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# or via pipx / pip, if you'd rather not run the install script
pipx install uv
```

Verify it's on your PATH:

```bash
uv --version
```

**2. Clone the repo:**

```bash
git clone <this-repo-url>
cd tyk-dup-listen-path-checker
```

**3. Install dependencies** (uv creates a `.venv` and installs everything
from `uv.lock`, including dev/test tooling):

```bash
uv sync --dev
```

That's it — no separate `pip install`, no manually creating a virtualenv.
`uv run <command>` (used throughout this README) automatically runs inside
that `.venv`.

<details>
<summary>Don't want to install uv? Use pip instead</summary>

A `requirements.txt` (generated from `uv.lock` via `uv export`) is included
for this case:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

This still runs the same locked dependency versions as the `uv` path. Once
installed, replace `uv run tyk-dup-check` with plain `tyk-dup-check` in every
example below.

</details>

## Configuration

Credentials can be provided either via a `.env` file or CLI flags (or a mix
of both — see [Execution modes](#execution-modes) below).

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Required | Description |
|---|---|---|
| `TYK_DASHBOARD_URL` | Yes* | Base URL of your Tyk Dashboard, no trailing slash — e.g. `https://dashboard.your-company.com`. |
| `TYK_DASHBOARD_API_KEY` | Yes* | Dashboard API key for a user with read access to APIs. Found under **Dashboard → User Profile → API Access Credentials**. |

\* Required unless supplied instead via `--dashboard-url` / `--api-key`.

`.env` is gitignored — never commit real credentials.

## Running it

```bash
uv run tyk-dup-check
```

## Execution modes

Credentials resolve per-field, CLI flag first, `.env`/environment as
fallback — so you can mix sources (e.g. keep `TYK_DASHBOARD_URL` in `.env`
and pass a one-off `--api-key` for a rotated key):

```bash
# 1. Environment / .env only
uv run tyk-dup-check

# 2. CLI flags only (no .env needed at all)
uv run tyk-dup-check \
  --dashboard-url https://dashboard.your-company.com \
  --api-key tyk-abc123...

# 3. Mixed — .env supplies the URL, flag overrides the key
uv run tyk-dup-check --api-key tyk-rotated-key...
```

Note: passing `--api-key` on the command line puts the key in your shell
history and process list (`ps`). For anything beyond a quick one-off, prefer
`.env`.

## CLI reference

```
uv run tyk-dup-check --help
```

| Flag | Default | Description |
|---|---|---|
| `--dashboard-url <str>` | — (falls back to `TYK_DASHBOARD_URL`) | Overrides the Dashboard URL from the environment. |
| `--api-key <str>` | — (falls back to `TYK_DASHBOARD_API_KEY`) | Overrides the API key from the environment. |
| `--include-internal` | off | Also check APIs marked `internal: true`. These don't bind a real gateway route by default, so they're normally excluded from duplicate checks and reported separately as "skipped". |
| `--match-mode <mode>` | `domain-and-path` | See [Match modes](#match-modes) below. |
| `--format <table\|json\|csv>` | `table` | Output format. |
| `--output <path>` | — (stdout) | Write output to a file instead of printing it. |
| `--help` | — | Show usage and exit. |

**Exit codes:** `0` if no duplicates were found, `1` if duplicates were found
*or* if the run failed (bad credentials, unreachable Dashboard, etc.) — handy
for CI: treat any non-zero exit as "investigate."

## Match modes

Two APIs only genuinely collide if requests can actually reach both of them
at the same route, which depends on domain handling:

- **`domain-and-path`** (default, strict): flags APIs only when both
  `domain` *and* `listen_path` match exactly. An empty/disabled domain is
  treated as the Dashboard's default domain, so two default-domain APIs on
  the same path still collide. APIs on genuinely different explicit domains
  do not.
- **`listen-path-only`** (loose): flags any APIs sharing a `listen_path`,
  regardless of domain. This catches things strict mode intentionally
  misses — e.g. Tyk's overlapping `{?:host1|host2}` multi-domain templates,
  where the same path is reachable through more than one hostname pattern.

```bash
uv run tyk-dup-check --match-mode listen-path-only
```

## Output formats

### `table` (default) — human-readable, printed via rich

```bash
uv run tyk-dup-check
```

```
         Duplicate routes (match mode: domain-and-path)
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ Domain          ┃ Listen path ┃ API name             ┃ API ID ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ api.example.com │ /dp-oauth/  │ DEP OAuth v1         │ api10  │
│                 │             │ DEP OAuth v2 (draft) │ api11  │
│                 │             │                      │        │
└─────────────────┴─────────────┴──────────────────────┴────────┘
Found 1 duplicate route group(s) across 3 APIs.
```

If any APIs were skipped as internal/non-routable, a line like
`Skipped 2 internal/non-routable API(s) (use --include-internal to check
them too).` is appended.

### `json` — for scripting/CI

```bash
uv run tyk-dup-check --format json --output dupes.json
```

```json
{
  "total_apis": 3,
  "match_mode": "domain-and-path",
  "duplicate_groups": [
    {
      "domain": "api.example.com",
      "listen_path": "/dp-oauth/",
      "apis": [
        {
          "name": "DEP OAuth v1",
          "api_id": "api10",
          "mongo_id": "000000000000000000000010",
          "domain": "api.example.com"
        },
        {
          "name": "DEP OAuth v2 (draft)",
          "api_id": "api11",
          "mongo_id": "000000000000000000000011",
          "domain": "api.example.com"
        }
      ]
    }
  ],
  "skipped_internal": []
}
```

`duplicate_groups[].domain` is `null` when a group spans multiple domains
(only possible under `--match-mode listen-path-only`) — each entry under
`apis` still carries its own accurate `domain`.

### `csv` — for spreadsheets

```bash
uv run tyk-dup-check --format csv --output dupes.csv
```

```csv
domain,listen_path,api_name,api_id,mongo_id
api.example.com,/dp-oauth/,DEP OAuth v1,api10,000000000000000000000010
api.example.com,/dp-oauth/,DEP OAuth v2 (draft),api11,000000000000000000000011
```

## Example usage

```bash
# Basic check against the Dashboard configured in .env
uv run tyk-dup-check

# One-off run against a different Dashboard, no .env needed
uv run tyk-dup-check --dashboard-url https://dashboard.staging.internal --api-key $STAGING_KEY

# Loose mode: catch cross-domain / multi-host-template collisions too
uv run tyk-dup-check --match-mode listen-path-only

# Include internal APIs in the check
uv run tyk-dup-check --include-internal

# Machine-readable output piped to a file, for CI gating
uv run tyk-dup-check --format json --output dupes.json
if [ $? -ne 0 ]; then echo "duplicate routes found — see dupes.json"; fi
```

## Troubleshooting

If the Dashboard can't be reached, the CLI classifies the failure and prints
concrete next steps rather than a raw stack trace, e.g.:

```
╭─────────────────────── Could not reach Tyk Dashboard ────────────────────────╮
│ No network route to 'host.docker.internal'.                                  │
│                                                                                │
│ Possible causes / things to check:                                           │
│   • Confirm the Dashboard is actually reachable from here, e.g.              │
│     curl -I http://host.docker.internal:3000.                                │
│   • Check whether a VPN or firewall is blocking the route.                   │
│   • 'host.docker.internal' only routes to the host automatically on Docker   │
│     Desktop (macOS/Windows). On Linux/plain Docker Engine it typically       │
│     needs the container started with                                        │
│     --add-host=host.docker.internal:host-gateway (add this to runArgs in     │
│     devcontainer.json) — or use the host's LAN/bridge IP instead.            │
╰────────────────────────────────────────────────────────────────────────────╯
```

Similar tailored messages cover DNS failures, connection refused, TLS/SSL
errors, and timeouts. A rejected API key (HTTP 401/403) is reported
separately and isn't retried, since paging through more requests wouldn't
fix bad credentials.

## Development

```bash
uv sync --dev                 # install deps (also runs automatically via postCreateCommand)
uv run pytest                 # run tests
uv run pytest --cov           # run tests with coverage
uv run ruff check . --fix     # lint
uv run mypy src               # type-check
```

## Layout

```
src/tyk_dup_checker/
  client.py     Tyk Dashboard API client (auth, pagination, retries)
  models.py     Dataclasses: ApiSummary, DuplicateGroup
  detector.py   Grouping/duplicate-detection logic (pure functions, no I/O)
  report.py     Console (rich table), JSON, and CSV renderers
  __main__.py   Typer CLI entrypoint, wires client -> detector -> report
tests/
  fixtures/     Small sample Dashboard API JSON payloads
  test_*.py
```

## License

MIT — see [LICENSE](LICENSE).
