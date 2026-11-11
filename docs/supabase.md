# Supabase authentication and private workspaces

The browser app uses Supabase Auth for Google and email/password sign-in, and Supabase Postgres
for its channels, conversations, tasks, asset metadata, checkpoints and agent memory. The React
app talks to the Python backend on the same origin. Tokens are stored in HttpOnly cookies;
frontend JavaScript never receives provider tokens, a database password or a service-role key.

## Configuration

Keep credentials in the Git-ignored `.env.supabase` file. Compose reads this file at runtime;
it must not be included in an image or frontend build. `.env` still holds the local Compose
UID/GID/socket settings and can be kept for the unauthenticated native development app.

Required server settings:

```dotenv
DESIGN_AGENT_AUTH_REQUIRED=1
DESIGN_AGENT_APP_URL=http://127.0.0.1:8765
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_PUBLISHABLE_KEY=your-publishable-key
DATABASE_URL=postgresql://your-server-role:your-password@your-session-pooler:5432/postgres?sslmode=verify-full&sslrootcert=config/supabase-ca.crt
```

Also set the model and its key as described in [Models](models.md). Use a direct database
connection, or the **session** pooler on port 5432 for IPv4-only Docker networks. Transaction
pooling cannot be used: workspace isolation relies on session-scoped `search_path`.
Download the provider's public CA certificate from Database Settings. The checked-in
`config/supabase-ca.crt` is a public certificate, not a credential. Verify both the server
certificate and hostname; do not disable verification to work around a connection error.

The initial server role is provisioned by
[`202611110001_private_workspace_role.sql`](../supabase/migrations/202611110001_private_workspace_role.sql).
It generates a password inside the database and keeps it in Supabase Vault; no password is
embedded in the migration. An operator supplies its connection URL to the server's protected
runtime environment. This role can create private schemas but has no superuser, role-management,
database-creation or RLS-bypass privileges. It must never be used in browser code.

## Google sign-in

In Google Cloud, create a **Web application** OAuth client for the app with this authorized
redirect URI (replace the project ref):

```text
https://your-project.supabase.co/auth/v1/callback
```

In Supabase Authentication → Sign In / Providers → Google, enable the provider and enter the
Google client ID and client secret. Only basic profile/email sign-in is needed. The secret
belongs in Supabase's provider configuration, not in React or this repository.

Set Supabase Auth's Site URL to the exact `DESIGN_AGENT_APP_URL` origin and allow this app
redirect URL:

```text
http://127.0.0.1:8765/api/auth/callback
```

These are different callbacks: Google returns to Supabase, which returns to the Python app.
The app uses a random PKCE verifier in an HttpOnly cookie and exchanges the short-lived code on
the server. It always redirects to its own root after authentication. If the Google OAuth app
is in Testing, add the intended test accounts in Google Cloud's Audience settings. Publishing
the OAuth app is separate from deploying this local application.

## Email sign-in

Email/password sign-up asks the person to confirm their email before entering a workspace.
The confirmation link must be opened in the browser that initiated sign-up (PKCE). After
confirmation, sign in using the email and password. Failed login messages do not disclose
whether an address exists, and invalid input responses do not echo passwords.

Configure Supabase's email delivery for the intended audience. Its built-in sender has delivery
and recipient restrictions; use an appropriate SMTP provider before inviting general users.
The app does not disable confirmation to bypass delivery configuration.

## Isolation and existing data

The server obtains the identity from Supabase's verified user endpoint, never `X-Person` or a
workspace ID from the client. Each user gets:

- A private Postgres schema `user_<uuid_without_dashes>`, including its own web store and
  LangGraph checkpoints/memory. RLS is enabled and public/anon/authenticated schema access is
  revoked. These schemas are not exposed through the public Data API. The trusted backend
  selects the schema from the verified identity and owns its tables.
- A separate runtime, live-event hub, brand shelf and file directory under
  `workspace/accounts/<uuid_without_dashes>/`. Files remain on the server's persistent disk;
  Supabase holds their metadata. Back up this directory as well as the database.
- Two initial empty channels and only their own person record plus the agent. There is no
  identity-switch menu. Local repository research and shared trace-reading tools are disabled.

Existing SQLite databases, conversations and files are left unchanged in their original local
folders. They are not imported into new accounts or made accessible through the authenticated
app. No account, including the first signup, automatically claims legacy data.

## Operations and verification

```bash
docker compose up -d --build --wait
curl --fail http://127.0.0.1:8765/healthz
# Must return 401 without a session:
curl -i http://127.0.0.1:8765/api/session
docker compose logs --tail=100 app
```

The server fails at startup if authentication configuration or the database connection is
missing; it never falls back to an unauthenticated app or SQLite in this mode. OAuth callback
query strings are excluded from access logs. Mutations require the configured origin, auth
attempts are rate-limited, cookies are SameSite=Lax (and Secure on HTTPS), and responses block
framing and sensitive API caching. Live streams reconnect periodically to revalidate sessions.

Keep this Compose deployment on localhost: it still controls the host's Docker daemon. Run
one app worker. Each signed-in user's runtime is kept until server shutdown; this local setup
is not a deployment recipe for a large public service. For frontend development on Vite's
port 5178, change the app origin and allowed Supabase callback consistently.

Run `uv run pytest -q` for offline tests. The Postgres integration suite is opt-in via
`TEST_DATABASE_URL`; it creates and removes randomly named, test-owned schemas, and checks
cross-user channel/thread/file denial, event isolation, SQL parameter binding, durability and
agent memory isolation. It does not send email or create Auth users.
