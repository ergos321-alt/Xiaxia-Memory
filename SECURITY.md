# Security

- Never commit `.env`, credentials, bearer tokens, or provider keys. Load secrets from server-side environment variables or secure runtime configuration.
- Use unique, high-entropy bearer tokens. Keep Supabase service-role credentials server-side only.
- Memory databases, vector stores, and exports can contain highly personal relationship history. Keep production stores private and never publish real memory exports or backups.
- The current `/mcp` route does not enforce inbound bearer authentication. The API's bearer check protects MCP-to-API calls, not access to the MCP endpoint itself. Deploy this route only behind trusted access control until a separate security change adds inbound authentication.
- Do not include credentials or private memory content in public issues. Use GitHub private vulnerability reporting when enabled, or contact the maintainer privately through GitHub.
