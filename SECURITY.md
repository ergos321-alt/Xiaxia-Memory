# Security

- Never commit `.env`, credentials, bearer tokens, or provider keys. Load secrets from server-side environment variables or secure runtime configuration.
- Use unique, high-entropy bearer tokens. Keep Supabase service-role credentials server-side only.
- Memory databases, vector stores, and exports can contain highly personal relationship history. Keep production stores private and never publish real memory exports or backups.
- Do not include credentials or private memory content in public issues. Use GitHub private vulnerability reporting when enabled, or contact the maintainer privately through GitHub.
