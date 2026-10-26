# GoodJob local n8n

The job records will live in the GoodJob Supabase project. This Docker volume
stores n8n's own configuration, credentials and workflow execution state.

## Start

```powershell
docker compose -f compose.n8n.yaml up -d
```

Open http://localhost:5678 and create the local owner account. Keep the password
private. Under Settings > Instance-level MCP, enable MCP access. Copy the OAuth
server URL; for this installation it should be:

```text
http://localhost:5678/mcp-server/http
```

The installed n8n version uses the older MCP settings screen, so it may not show
the newer Connect a client dialog described in the latest n8n documentation.

## Connect Codex with OAuth

After MCP is enabled:

```powershell
codex mcp add n8n --url http://localhost:5678/mcp-server/http
codex mcp login n8n
```

Complete authorization in the browser. Do not paste tokens into chat. Verify
that n8n tools are available in the chat before treating the connection as ready.
If needed, refresh the MCP connection or reopen the Codex chat after login.

## Stop without deleting data

```powershell
docker compose -f compose.n8n.yaml stop
```

The pre-existing container named `n8n` has been preserved separately. Its empty
Windows bind mount could not be written by the container, so this project uses a
Docker-managed volume instead. Do not use `down -v` unless you intend to delete
the new n8n configuration and credentials.

References:
- https://docs.n8n.io/connect/connect-to-n8n-mcp-server/
- https://docs.n8n.io/connect/connect-to-n8n-mcp-server/mcp-client-examples/
