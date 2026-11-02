# Paper hosted worker (experimental recipe)

A recipe, not a supported mode: nothing in Design Agent wires it up by default. Use it only when a
team wants an always-on Paper session a deployed agent can reach without anyone's laptop being
open. Bridged mode in front of a person's own Paper Desktop ([paper.md](paper.md)) is simpler and
should be the first choice. When Paper ships a hosted or remote MCP, use that instead and retire
this.

## Shape

One always-on Linux machine with a persistent disk runs:

1. a virtual display (Xvfb);
2. Paper Desktop on that display, signed in once by a person on the team;
3. `design-agent paper-bridge` on `127.0.0.1`, in front of Desktop's local MCP;
4. a TLS tunnel or reverse proxy you own, forwarding one hostname to the bridge.

The agent runs in Bridged mode against that hostname, exactly as it would against a laptop.

## Steps

1. **Machine.** A small Linux VM or long-lived container with a persistent disk (Paper's sign-in
   lives there), no other workloads, and inbound traffic limited to the tunnel.
2. **Display and Desktop.** Install Xvfb and Paper Desktop, and run Desktop on the virtual display
   (`Xvfb :99 &` then `DISPLAY=:99 <paper desktop>`). Paper does not document Linux Desktop support;
   check that it runs and that `~/.paper/bin/paper mcp` answers before going further.
3. **Sign in once.** Attach a VNC server to the display bound to `127.0.0.1`, reach it over SSH
   port forwarding, and let a person on the team sign in to Paper themselves, pick the team, and
   open the drafts file. Then stop the VNC server. Do not script the sign-in or pass credentials to
   the machine.
4. **Bridge.** Set `PAPER_BRIDGE_TOKEN` (32+ random bytes), `PAPER_DRAFTS_FILE_ID`,
   `PAPER_BRAND_FILE_ID` and `PAPER_TEAM_ID` in the bridge's `.env`, then run
   `uv run design-agent paper-bridge --allow-host <your hostname>`.
5. **Supervise.** Run the display, Desktop and the bridge as supervised services (systemd units or
   your process manager) that restart on failure and start in that order at boot.
6. **Tunnel.** Point your tunnel's hostname at `127.0.0.1:29980` over HTTPS.
7. **Agent.** `PAPER_MODE=bridged`, `PAPER_MCP_URL=https://<your hostname>/mcp`, and the token as
   `PAPER_BRIDGE_TOKEN` (self-hosted) or the `paper-bridge` workspace connection (MDA).

## Caveats

- **Unsupported platform.** Linux Paper Desktop is not documented by Paper and may break on any
  update; pin and test Desktop updates before rolling them out.
- **One identity for everyone.** Every run acts as the signed-in account, so give it access to the
  team's working files only. `PAPER_TEAM_ID` keeps calls inside one team; the brand file stays
  read-only either way.
- **Shared Desktop state.** All runs share one Desktop, its open file and its active page. The
  agent passes `fileId` and `pageId` on every call for this reason; avoid tools that change what
  Desktop has open.
- **The session is a credential.** The worker's disk holds a signed-in Paper session: back it up
  like a secret, never copy it elsewhere, and rebuild rather than clone the machine. Losing the
  disk means signing in again; a session that expires needs a person to sign in again the same way.
- **Plan limits.** Paper's MCP call limits apply to the signed-in account's plan, shared by every
  run.
- **Tool drift.** Paper's tool names are not a stable contract yet. The bridge logs a tool the
  policy admits but Desktop no longer offers; only that tool stops working.
