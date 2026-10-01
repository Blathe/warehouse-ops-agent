# Using the MCP server from Claude Desktop

1. Seed a database with a fixed "now" (from `backend/`):

   ```
   python -m uv run seed-db --as-of 2026-06-01T13:00
   ```

2. Add the server to Claude Desktop's config (Settings → Developer → Edit Config, or
   `%APPDATA%\Claude\claude_desktop_config.json` on Windows), using the same time for
   `WAREHOUSE_AS_OF` so "the last 24 hours" means the seeded day:

   ```json
   {
     "mcpServers": {
       "warehouse-ops": {
         "command": "python",
         "args": [
           "-m", "uv",
           "--directory", "F:/Workspace/python/warehouse-ops-agent/backend",
           "run", "--no-sync", "python", "-m", "warehouse_ops.mcp_server"
         ],
         "env": { "WAREHOUSE_AS_OF": "2026-06-01T13:00" }
       }
     }
   }
   ```

   `--no-sync` plus `python -m` (instead of the `warehouse-mcp` script) matters on
   Windows: a running `warehouse-mcp.exe` is locked, and every `uv run` / `uv sync`
   would then fail trying to reinstall it.

   Use forward slashes in the path: JSON treats a single backslash as an escape
   character, so `F:\Workspace` makes the whole file invalid.

3. Restart Claude Desktop and try:
   - "Any short picks in zone A today?"
   - "Which pick faces need replenishing, and where's the stock?"
   - "Where is SKU <code> stocked?"

Every call is recorded in the `tool_call_log` table.
