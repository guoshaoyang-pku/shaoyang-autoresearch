# Codex proxy

Small HTTP server that adapts **OpenAI Responses API** requests (what `codex` sends to `wire_api = "responses"`) to a **Chat Completions** upstream.

## Configure

1. Copy `../keys.example.json` to `../keys.json` and set `codex_proxy.upstream_base_url` and `codex_proxy.bearer_token`, **or** export:
   - `CODEX_PROXY_UPSTREAM_URL` — URL whose path is the prefix before `/chat/completions`
   - `CODEX_PROXY_API_KEY` — sent as `Authorization: Bearer` and `api-key`
2. From repo root: `./proxy/start_proxy.sh`
3. Point `~/.codex/config.toml` at `http://127.0.0.1:4002` (see `codex_config.example.toml`).

Health check: `curl -fsS http://127.0.0.1:4002/`
