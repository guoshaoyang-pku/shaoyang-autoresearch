# Codex Backend Recipe (verified 2026-05-02 on <your-gpu-host>)

## TL;DR

This is the **only** backend for cursor_manager's in-loop LLMs (manager,
worker, reviewer-sim). The legacy `cursor-agent` backend has been removed
because remote GPU hosts cannot run Cursor at all and cross-platform tokens
do not migrate. Cross-API-model adversarial review is now achieved by giving
each role a different codex profile -- e.g. one profile maps to Claude-Opus,
another to GPT-5.5 -- in `~/.codex/config.toml`.

## Verified working invocation

```bash
codex exec \
  --skip-git-repo-check \   # else codex may auto-init a repo in pwd
  --color never \           # turn off ANSI escapes for clean log capture
  --profile high \          # picks ~/.codex/config.toml [profiles.high] (gpt-5.5 xhigh)
  "<prompt>" \
  < /dev/null               # MANDATORY -- otherwise codex blocks reading additional stdin
```

The `< /dev/null` is the trap that bit us during initial smoke-testing:
without it, codex prints `Reading additional input from stdin...` and waits
indefinitely. Output looks like:

```
OpenAI Codex v0.128.0 (research preview)
--------
workdir: <pwd>
model: gpt-5.5-2026-04-24
provider: custom_proxy
approval: never
sandbox: danger-full-access
reasoning effort: xhigh
reasoning summaries: none
session id: 019de44d-785e-7a81-8b68-33fc726e824e
--------
user
<your prompt>
codex
<response text>
tokens used
8,864
<final assistant message>
```

The `session id` line is the persistence hook. Capture it via regex
`session id: ([0-9a-f-]+)` and persist for later
`codex exec resume <session-id>` calls.

## Provider configuration (already deployed on <your-gpu-host>)

`~/.codex/config.toml` is configured to route through a local proxy:

```toml
model = "gpt-5.5-2026-04-24"
model_provider = "custom_proxy"
model_reasoning_effort = "xhigh"
approval_policy = "never"
sandbox_mode = "danger-full-access"

[model_providers.custom_proxy]
name = "custom upstream"
base_url = "http://localhost:4002"
api_key = "local-proxy-placeholder"        # proxy adds real upstream auth (see keys.example.json)
wire_api = "responses"

[profiles.high]
model = "gpt-5.5-2026-04-24"

[profiles.gpt54]
model = "gpt-5.4-2026-03-05"
```

Local proxy `proxy/codex_proxy.py` listens on `localhost:4002` and forwards to
your organization's Chat Completions-compatible endpoint. Run `./proxy/start_proxy.sh`
from the repository root (or keep your own launcher). Set `CODEX_PROXY_UPSTREAM_URL`,
`CODEX_PROXY_API_KEY`, or fill `keys.json` as in `keys.example.json`.

Quick health check:

```bash
curl -sS -m 5 -X POST http://localhost:4002/responses \
  -H 'Content-Type: application/json' \
  -d '{"model":"gpt-5.5-2026-04-24","input":"ping"}' | head -5
```

## Resume / session continuity

```bash
codex exec resume <session-id> --color never \
  "next instruction" \
  < /dev/null
```

Or pick the most recent automatically:

```bash
codex exec resume --last --color never "next instruction" < /dev/null
```

## How `cursor_manager` consumes codex (status: shipped 2026-05+)

1. ✅ **`config.toml`**: only `backend = "codex"` is accepted under both
   `[reviewer]` (manager) and `[worker]`; `_invoke_manager.py` and `mgr`
   reject any other value at load time. **There is no `[manager].backend`:**
   `[manager]` only stores scheduler / logging fields (`poll_interval_seconds`,
   `mode`, `log_path`, …). Use `[reviewer].profile` /
   `[worker].profile` / `[reviewer_sim].profile` to select different
   `~/.codex/config.toml [profiles.<key>]` blocks per role. The `model`
   field has been removed from the schema.

2. ✅ **`tick.sh`**: delegates to `scripts/_invoke_manager.py tick`, which
   directly issues
   ```bash
   codex exec resume <session-id> --color never -C <root> \
       "tick now (<ts>)" < /dev/null
   ```
   The `state/manager_chats.json` schema is now codex-only:
   `{<wid>: {"backend": "codex", "session_id": "<uuid>", "profile": "<key>", "created_at": "..."}}`.

3. ✅ **`kickoff.sh`**: codex-only first-turn session creation; captures
   `session id:` via regex (see `_extract_codex_session_id` in
   `scripts/_invoke_manager.py`) and writes the schema above. Self-tests
   cover both successful parse and missing-session-id failure.

4. ✅ **Worker codex backend**: `lib/codex_worker.py` is the only worker
   class. The `mgr` factory `_make_codex_worker` constructs it directly;
   the legacy `lib/local_worker.py` (cursor-agent worker) has been deleted.
   State persisted in `state/workers/<id>/codex_session.json`.

5. **Prompts**: `prompts/manager.md` references the four v2 sub-agent
   commands and reminds the manager that the entire in-loop is codex-only.
   Per-worker prompts simply note that fork-resume uses
   `codex exec resume <session-id>`.

6. **Cost knob**: profile-based reasoning effort is the primary lever.
   Configure cheap profiles (`gpt-5.5 medium`) for the manager tick and
   expensive profiles (`gpt-5.5 xhigh` or `claude-opus thinking-high`) for
   the worker. Cross-API-model adversarial review (paper §4.3) requires
   `[worker].profile != [reviewer_sim].profile` and ideally
   `[worker].profile` and `[reviewer_sim].profile` map to different model
   *families*.

## Known gotchas

- **`codex --version` is fast but `codex exec` even with trivial prompt costs
  ~9k tokens** because reasoning effort defaults to xhigh. Drop to medium for
  cheap manager-tick "are we OK?" checks.
- **Sandbox-mode `danger-full-access` is required** if the worker needs to
  write files (default `read-only` blocks any disk write).
- **`codex exec` does NOT inherit `--workspace`** from a parent process or
  config. Always pass `-C <abs-path>` explicitly.
- **Stdout mixes status header + user echo + assistant message + token count**.
  Parsing the actual response requires looking for the line after `codex\n`
  and before `tokens used`. A safer pattern is to wrap the prompt with an
  output sentinel like `Reply ending with the literal token <<<END>>>` and
  grep for it.

## Provenance of this recipe

- Smoke-tested 2026-05-02T00:08+0800 on `<your-gpu-host>` (Linux x86_64, codex CLI
  v0.128.0, local `codex` proxy on `localhost:4002`).
- One round-trip: `BANANA-CODEX-OK` returned in 12s, 8.8k tokens, proxy log
  `POST /responses HTTP/1.1 200`.
