# Deploy the browser app on Railway

The [Railway definition](../.railway/railway.ts) runs React and FastAPI together as the `web` service. Supabase supplies authentication and Postgres. The private `minio` service stores uploads, generated files and recordings in its versioned `incredible-files` bucket on the `minio-data` volume. The web service has a separate `workspace` volume for editable brand packs, logos, fonts and working files. Each service runs one replica and mounts its own volume at `/data`. Rendering runs in per-thread containers on a dedicated Docker machine.

## Where production settings live

Use the **production** environment in Railway. Under **web → Variables**, set the values below. Seal the database URL, provider keys and runner private key after entering them. Keep their recovery copies in your team's password manager. The IaC uses `preserve()` for externally supplied values. The web service references the limited application credentials on `minio`. Keep production values out of Git, frontend variables, image build arguments, screenshots and PR jobs. Use separate credentials, Supabase projects, runners and storage for staging and production. [Railway variables](https://docs.railway.com/variables) · [IaC variable reference](https://docs.railway.com/infrastructure-as-code/reference)

| Web service variables | What to supply |
| --- | --- |
| `DESIGN_AGENT_APP_URL` | The canonical public HTTPS origin, e.g. `https://studio.example.com`. |
| `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` | The matching environment's Supabase project URL and publishable key. |
| `DATABASE_URL` | The app role's direct or session-pooler Postgres URL on port 5432. Use `sslmode=verify-full&sslrootcert=/app/config/supabase-ca.crt` and confirm the CA matches the project. The transaction pooler breaks session-scoped workspace isolation. |
| `DESIGN_AGENT_MODEL`, `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` | Set a supported `provider:model` and the corresponding provider key. Set the OpenAI key if enabling Codex research. Only configure providers you intend to use. |
| `DOCKER_HOST`, `DESIGN_AGENT_SANDBOX_IMAGE` | The runner's reachable `tcp://hostname:2376` endpoint and the preloaded image tag or digest matching this release. |
| `RUNNER_CA_PEM`, `RUNNER_CERT_PEM`, `RUNNER_KEY_PEM` | Multiline CA, Docker client certificate and client private key. The daemon's own private key stays on the runner. |
| `DESIGN_AGENT_S3_*` | Configured in IaC. The web service connects to `http://minio.railway.internal:9000` using path-style S3 requests and the application credentials below. |

Use the same application access key when rotating its secret, then redeploy MinIO followed by web. If changing the access key ID, revoke the old MinIO user after verifying the new one.

Under **minio → Variables**, supply these four values once per environment. Generate independent random passwords, seal them, and save recovery copies in the team password manager.

| MinIO service variables | Purpose |
| --- | --- |
| `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | Administrator credentials for initializing and maintaining the bucket. Only MinIO receives these. |
| `DESIGN_AGENT_S3_ACCESS_KEY`, `DESIGN_AGENT_S3_SECRET_KEY` | Distinct application user and secret. Web receives references to this pair and can read and write objects under `accounts/*`. |

MinIO starts on loopback to create the bucket, enable versioning, disable anonymous access and apply the [application policy](../deploy/minio/app-policy.json). After initialization it opens port 9000 on Railway's private network. Leave public domains and TCP proxies disabled for MinIO. The browser downloads files through the authenticated web API. [Railway private networking](https://docs.railway.com/networking/private-networking)

For invitation email or additional providers, add the corresponding variable names to the IaC using `preserve()` and supply their values on the service. Google OAuth credentials belong in Supabase's provider settings. [Supabase setup](supabase.md) · [Model settings](models.md)

## First deployment

1. Use a clean checkout of a reviewed commit containing this configuration. Choose regions before provisioning. The defaults are US East (Virginia), 5 GiB for the web workspace and 10 GiB for MinIO objects and their versions. Place them near your Supabase project and runner. Size MinIO for media retention and monitor its free space.
2. Set up a dedicated Docker Engine on a machine reachable from the Railway web service. Require mutual TLS, restrict ingress to the service's network or allowed egress addresses and reserve the daemon for this environment. Docker client credentials grant administrative access to that machine. Build the sandbox there from the same checkout, e.g. `docker build -t design-agent-sandbox:release sandbox/`. Configure the web service to use that tag. [Docker daemon access](https://docs.docker.com/engine/security/protect-access/)
3. Provision a separate Supabase project per environment. Apply the [private workspace role migration](../supabase/migrations/202611110001_private_workspace_role.sql) as an administrator and configure Auth providers, the Site URL and callback allowlist. Allow the base origin's `/api/auth/callback` and each permitted project subdomain's callback. For project invitations and sharing, attach both the base and wildcard domains to the web service and complete Railway's DNS and TLS verification. [Supabase setup](supabase.md) · [Railway domains](https://docs.railway.com/networking/domains/working-with-domains)
4. Create or select a dedicated Railway project and its staging environment. From the repository root run `railway link`, verify the environment with `railway status`, then run `railway config plan`. Review both services, their volumes, cost and any removals. If an environment already has a managed bucket with files, keep that resource until you have copied the objects to MinIO, verified their keys and checksums and tested authenticated downloads. After approval, run `railway config apply`. This provisions resources. The config leaves source selection to the release operator.
5. Set the MinIO credentials and deploy the clean checkout with `railway up --service minio`. Wait for its readiness check, then set the web variables and run `railway up --service web` from the same checkout. The launcher prepares the mounted volume as root, drops to the image's `agent` user, writes the TLS files into a private temporary directory, then starts the web server on Railway's assigned port. Packaged workspace tools stay available under `/app/workspace/tools`.
6. Confirm `GET /healthz` returns 200 with `authentication: supabase` and an anonymous `GET /api/session` returns 401. Sign in, upload and reopen a file, confirm a second account cannot access it, and repeat after redeploy. Exercise a sandbox render with approved staging credentials. Startup checks Postgres and the bucket. A green health check alone does not exercise a render.
7. For production, verify the target environment again, review a fresh plan, set production credentials and deploy the **same tested commit**. A single mounted volume can cause a short interruption during replacement. Schedule backups for Supabase and both volumes, and copy versioned MinIO objects to an independent backup destination. Budget for security updates to the pinned MinIO build before production. See the [MinIO operations guide](minio.md). Test restore in staging. To roll back code, redeploy the previous tested commit and compatible runner image. Review database and file compatibility before restoring state.

HyperFrames Studio currently returns a loopback editor URL. Hosted users can access delivered files, but opening the interactive editor remotely requires an authenticated preview proxy. Keep editor ports private.

Private repository research requires an explicit owner, a per-owner catalog on the persistent volume, and a read-only repository reader on the runner. A Railway deployment cannot discover laptop checkouts. Provision only approved repositories and follow the existing reader and catalog setup before enabling this feature. [Repository research setup](supabase.md#local-repository-suggestions)

[Railway infrastructure as code](https://docs.railway.com/infrastructure-as-code) · [Volumes](https://docs.railway.com/volumes)
