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

## Profile and preferences

Settings opens the Profile tab for signed-in users. Preferences has its own link at `/settings/preferences`.

Settings → Profile lets signed-in users edit a project display name and avatar, see their primary email, and save account-wide first and last names and a unique sign-in username. Usernames are case-insensitive. Password sign-in accepts either the verified email address or the saved username. A Google account can set its first
password here and then sign in with the same email using either method. Email/password accounts
and Google accounts with an existing password must confirm their current password to update it.

Settings → Preferences lists the configured providers, models and supported effort levels for chat.
Saved choices apply to subsequent chat turns in the private workspace. A picture with an explicit
model selection keeps that selection. Choose Workspace default to use the operator’s settings.

## Projects, members and activity

Organization shows the permanent project ID and a separate address based on the organization name.
For example, **Design House** opens at `http://design-house.localhost:8765` in local Compose.
If an address is taken, Studio adds a number such as `design-house-2`. Renaming an organization
updates its address. Previous names and UUID links still lead to the same project. Sign in at the root Studio address. A new owner names their organization
and lands on their personal project. Returning users land on their last visited project if
they still have access, or their personal project otherwise. Existing navigation history
helps select the first destination after an upgrade.

Opening a project bookmark or invitation preserves the original destination through password
sign-in, signup confirmation, and Google sign-in. An invited user reviews the invitation
before gaining access and skips personal organization setup. Studio uses a browser-bound,
one-time handoff valid for 60 seconds. Project cookies are host-only and opaque. The root
handles credential refresh, and signing out revokes the browser’s linked project sessions.

For a custom HTTPS origin, configure wildcard DNS and TLS for the project subdomains,
forward the original Host header, and allow the **root** Studio callback in Supabase Auth.

Owners invite members by email in Organization settings. Each email links to a review page on
the inviting project’s hostname. The recipient signs in with the invited email and chooses
**Accept invitation** to open the project. Opening the link alone grants no access. The owner
can also choose **Copy invite link** from a pending invitation’s actions. If mail delivery
fails, the invitation stays pending and the same link can be shared. Pending invitations
also appear in the recipient’s Organization settings after sign-in. Members can access the
project’s channels, files, and agent tools. Owners can revoke pending invitations and remove members. Access is checked on
every project request. Removing someone closes project event streams so clients reauthorize.
A member’s personal workspace remains available at the base Studio address.

For local email testing, start Studio with the Mailpit override:

```bash
docker compose -f compose.yaml -f compose.mailpit.yaml up -d --build --wait
```

Open the test inbox at `http://127.0.0.1:18025`. Mailpit captures Studio invitations locally.
Supabase continues to handle its own sign-in and verification mail.

For delivery to real recipients, use the base Compose file, set a public HTTPS Studio origin,
and configure `DESIGN_AGENT_SMTP_HOST`, `DESIGN_AGENT_SMTP_PORT` (default 587),
`DESIGN_AGENT_SMTP_FROM`, and your relay’s `DESIGN_AGENT_SMTP_USERNAME` and
`DESIGN_AGENT_SMTP_PASSWORD` in the app’s private environment. STARTTLS is enabled by default
and required for SMTP credentials. Use a From address verified by your mail provider.

The server maintains the private Postgres schema `studio_directory` for account handles,
workspace-to-schema mappings, invitations and project activity. Back it up alongside project schemas. Logs records verified
actors for API mutations, navigation and supported device-preference changes from this version
onward. Use the actor filter or page through older entries. Audit rows store the action, time,
status and actor identity. Select a row to see the event ID, timestamp and recorded action. New events include response time, and successful membership changes also identify the affected member. Passwords, message bodies and URL query strings are excluded.

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

- A private Postgres schema such as `ws_42` for a new workspace, including its own web store and
  LangGraph checkpoints/memory. RLS is enabled and public/anon/authenticated schema access is
  revoked. These schemas are not exposed through the public Data API. The trusted backend
  resolves the authorized project owner through `studio_directory.workspaces` and owns its tables.
- A separate runtime, live-event hub, brand shelf and file directory under
  `workspace/accounts/<uuid_without_dashes>/`. Root Compose keeps registered file bytes in
  private [MinIO S3 storage](minio.md); Supabase holds their metadata. Back up MinIO, the
  database and local working data.
- Two initial empty channels and only their own person record plus the agent. There is no
  identity-switch menu. Local repository research is opt-in for an individual verified account. Shared trace-reading tools are disabled.

In the Supabase Table Editor, open **studio_directory → workspaces** to look up a project's
`organization_name`, `owner_id`, and `schema_name`. The name can be blank until the owner
sets it. Renaming the organization updates this label. The numeric ID is stable and can have
gaps. Project URLs, invitations, disk paths and MinIO keys continue to use the owner UUID.

On startup the backend registers existing `user_<uuid_without_dashes>` schemas owned by the
application database role, including projects without account-directory profiles. Their data
and table names stay in place. New projects receive `ws_<id>` on first access. Back up the
directory alongside workspace schemas. To run the additive backfill ahead of a rollout, use
`python -m design_agent.surfaces.web.workspace_directory` with the application database role.
An immediate second run reports zero registrations. Upgrade all web instances sharing a database before
allowing new workspace creation. Older servers derive the legacy name directly and cannot
route to a numeric schema, so rolling back after a numeric workspace exists requires a
directory-aware release.

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

### Local repository suggestions

An operator can enable repository autocomplete for a specific private account. On the computer
with the repositories, export their relative folder names into a catalog named for the account's
verified Supabase user UUID. Use a dedicated catalog directory outside the served web assets.

```bash
mkdir -p "$HOME/.local/share/design-agent/repo-catalogs"
uv run python -m design_agent.surfaces.web.research_catalog "$HOME/Projects" \
  "$HOME/.local/share/design-agent/repo-catalogs/<user-uuid>.json"
```

Mount the catalog directory read-only in the app container and set
`DESIGN_AGENT_RESEARCH_CATALOG_DIR` to its container path. The app user needs read access.
Add `--also-scan <folder>` for each additional root. Give each root a distinct folder name so
checkouts with the same name can be distinguished in the picker. Rerun the export to pick up
renamed, added or removed repositories. The picker searches names
and relative paths, including worktrees, up to two directories below the scan root. Use the
arrow keys and Enter or click a suggestion. This enables discovery for the catalog owner.
To enable provider research for one verified user, set `DESIGN_AGENT_RESEARCH_OWNER_ID` to their
Supabase UUID and `DESIGN_AGENT_RESEARCH_READER_CONTAINER` to an operator-controlled Docker
container with Python, Git, and this branch's source installed. Mount the scan roots read-only
there and set its `DESIGN_AGENT_RESEARCH_ROOTS` to the same comma-separated root paths used to
export the catalog. For linked worktrees, also make their Git metadata available at the original
paths. The reader runs with networking disabled and needs no provider keys or Docker socket.

Configure the chosen provider in the app environment with `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`
or `MOONSHOT_API_KEY`. A person can select up to eight repositories, add notes or previous
answers, and attach UTF-8 text, Markdown, CSV, JSON, RST or log files (64 KB per file).
Starting a run sends bounded excerpts from committed source and the supplied material to
the selected provider. Results and attachments stay in the account’s research frame.
Private runs use provider APIs. Choose the model and effort for the selected provider when starting research. Kimi offers instant and thinking modes. Follow-up questions inherit the conversation’s selection. The native single-user flow uses the installed coding-agent CLI.
