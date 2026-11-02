"""The `design-agent` command line."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import click

from design_agent.config import Settings, project_root


def _root() -> Path:
    return project_root(Path.cwd())


def _docker() -> str:
    found = shutil.which("docker")
    if found is None:
        raise click.ClickException("Docker is not installed or not on PATH.")
    return found


@click.group()
@click.version_option(package_name="design-agent")
def main() -> None:
    """On-brand design and motion from a chat thread."""


@main.command()
def demo() -> None:
    """Render the sample brand's launch card in three sizes with a scripted model (no keys)."""
    from design_agent.demo import demo_main

    sys.exit(demo_main(_root()))


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def doctor(as_json: bool) -> None:
    """Check configuration, brand, sandbox and model setup without printing secrets."""
    from design_agent.doctor import doctor_main

    sys.exit(doctor_main(_root(), as_json=as_json))


@main.command()
@click.argument("request")
@click.option("--thread", "thread_id", default=None, help="Continue a thread by id.")
@click.option(
    "--no-wait",
    is_flag=True,
    help="Return after the first reply. Background work stops when the command exits.",
)
@click.option(
    "--file",
    "files",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Attach a file (repeatable); it lands in the sandbox's /workspace/attachments/.",
)
def ask(request: str, thread_id: str | None, no_wait: bool, files: tuple[Path, ...]) -> None:
    """Run one request with your configured model; finals land in workspace/out/<thread>/.

    Threads persist in workspace/state/, so --thread continues one. While helpers, renders or
    check-ins the request started are running, the command stays open and prints each update.
    """
    thread = thread_id or f"cli-{uuid.uuid4().hex[:8]}"
    sys.exit(asyncio.run(_ask(_root(), request, thread, wait=not no_wait, files=files)))


async def _ask(
    root: Path, request: str, thread: str, *, wait: bool, files: tuple[Path, ...] = ()
) -> int:
    from langchain_core.messages import AIMessage

    from design_agent.doctor import missing_model_key
    from design_agent.harness.meter import Meter
    from design_agent.runtime.local import build_local_runtime, final_text
    from design_agent.runtime.persistence import open_persistence, workspace_of
    from design_agent.tools.mcp import load_mcp_tools, servers_for_runtime
    from design_agent.tools.paper import PaperPolicy, admit_paper_tools

    settings = Settings()
    if needed := missing_model_key(settings):
        click.echo(
            f"{needed} is not set, so the model cannot be reached. Set it with "
            f"`uv run design-agent config set {needed}=…`, or try `uv run design-agent demo`, "
            "which needs no keys.",
            err=True,
        )
        return 2
    servers = servers_for_runtime(root, settings, "local")
    loaded = await load_mcp_tools(servers)
    for name, reason in loaded.failed.items():
        click.echo(
            f"MCP server {name} is unavailable this run ({reason}); the rest works.", err=True
        )
    servers = [s for s in servers if s.name not in loaded.failed]
    loaded.tools = admit_paper_tools(loaded.tools, PaperPolicy.from_settings(settings))
    meter = Meter()
    async with open_persistence(settings, workspace_of(settings, root)) as (checkpointer, store):
        runtime = build_local_runtime(
            settings,
            root,
            checkpointer=checkpointer,
            store=store,
            replies=lambda _thread, text: click.echo(f"\n{text}"),
            mcp_servers=servers,
            mcp_tools=loaded.tools,
        )
        await runtime.waker.restore(thread)  # check-ins this thread missed while nothing ran
        if files:
            placed = await runtime.attach(thread, [(f.name, f.read_bytes()) for f in files])
            request = request + "\n\nAttached: " + ", ".join(placed)
        try:
            added = []
            async for update in runtime.stream(request, thread_id=thread):
                for value in update.values():
                    for message in (
                        (value or {}).get("messages", []) if isinstance(value, dict) else []
                    ):
                        added.append(message)
                        if isinstance(message, AIMessage):
                            for call in message.tool_calls:
                                click.echo(f"  · {call['name']}", err=True)
            click.echo(final_text(added))
            if wait and runtime.busy():
                click.echo(
                    "\nBackground work is running; waiting for it (Ctrl-C stops it, its files stay).",
                    err=True,
                )
                await runtime.settle()
        except Exception as error:  # noqa: BLE001 - one line for the person; the thread is saved
            click.echo(
                f"The run stopped ({type(error).__name__}). The thread is saved: continue it with "
                f"--thread {thread}; `uv run design-agent doctor` checks the setup.",
                err=True,
            )
            return 1
        finally:
            await runtime.services.aclose()
            if runtime.binding.runner is not None:
                runtime.binding.runner.stop_all()
            spent = meter.summary(thread)
            meter.close()
            if spent.calls:
                click.echo(
                    f"cost: about ${spent.usd:.2f} at list prices ({spent.calls} model calls, "
                    f"{spent.hit_ratio:.0%} of input read from cache)",
                    err=True,
                )
        folder = runtime.out_dir / thread
        if folder.is_dir():
            for path in sorted(folder.iterdir()):
                click.echo(f"  {path}")
        click.echo(f"(thread {thread}; continue with --thread {thread})")
    return 0


@main.group()
def brand() -> None:
    """Validate and inspect the active brand pack."""


@brand.command("validate")
@click.option("--path", "path", type=click.Path(path_type=Path), default=None)
def brand_validate(path: Path | None) -> None:
    from design_agent.brand.schema import BrandPackError, load_brand_pack

    root = _root()
    target = path or Settings().resolved_brand_path(root)
    try:
        pack = load_brand_pack(target, project_root=root)
    except BrandPackError as error:
        click.echo(str(error), err=True)
        sys.exit(1)
    click.echo(
        f"{pack.brand.name}: valid ({len(pack.tokens.design.palette())} colors, fonts {', '.join(pack.required_families())})"
    )


@brand.command("css")
@click.option("--path", "path", type=click.Path(path_type=Path), default=None)
def brand_css(path: Path | None) -> None:
    """Regenerate tokens.css from tokens.json."""
    from design_agent.brand.schema import load_brand_pack, render_tokens_css

    root = _root()
    target = path or Settings().resolved_brand_path(root)
    pack = load_brand_pack(target, project_root=root)
    (target / "tokens.css").write_text(render_tokens_css(pack))
    click.echo(f"wrote {target / 'tokens.css'}")


@brand.command("show")
def brand_show() -> None:
    from design_agent.brand.schema import load_brand_pack

    root = _root()
    pack = load_brand_pack(Settings().resolved_brand_path(root), project_root=root)
    click.echo(
        json.dumps(
            {
                "name": pack.brand.name,
                "root": str(pack.root),
                "formats": [f.slug for f in pack.brand.formats],
                "fonts": pack.required_families(),
            },
            indent=2,
        )
    )


@main.command()
def serve() -> None:
    """Run the self-hosted HTTP API (DESIGN_AGENT_API_HOST:DESIGN_AGENT_API_PORT)."""
    import uvicorn

    from design_agent.surfaces.api.app import create_app

    settings = Settings()
    uvicorn.run(
        create_app(_root(), settings),
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
    )


@main.group()
def config() -> None:
    """Show and change settings in .env without printing secrets."""


@config.command("show")
@click.option("--json", "as_json", is_flag=True)
def config_show(as_json: bool) -> None:
    from design_agent.envfile import view

    rows = view(_root())
    if as_json:
        click.echo(json.dumps(rows, indent=2))
        return
    for row in rows:
        state = row["value"] if row["value"] else "-"
        click.echo(f"{row['name']:40} {state}")


@config.command("set")
@click.argument("pairs", nargs=-1, required=True)
def config_set(pairs: tuple[str, ...]) -> None:
    """Set KEY=VALUE pairs (known keys only; the file stays private to you)."""
    from design_agent.envfile import EnvFileError, write_env

    updates = {}
    for pair in pairs:
        name, sep, value = pair.partition("=")
        if not sep:
            click.echo(f"{pair}: use KEY=VALUE", err=True)
            sys.exit(2)
        updates[name.strip()] = value
    try:
        changed = write_env(_root(), updates)
    except EnvFileError as error:
        click.echo(str(error), err=True)
        sys.exit(1)
    click.echo("Set " + ", ".join(changed) + " in .env.")


@config.command("generate")
@click.argument("names", nargs=-1, required=True)
def config_generate(names: tuple[str, ...]) -> None:
    """Fill random secrets (DESIGN_AGENT_API_TOKENS, PAPER_BRIDGE_TOKEN, POSTGRES_PASSWORD)."""
    from design_agent.envfile import EnvFileError, generate

    try:
        changed = generate(_root(), list(names))
    except EnvFileError as error:
        click.echo(str(error), err=True)
        sys.exit(1)
    click.echo(
        ("Generated " + ", ".join(changed) + " in .env.")
        if changed
        else "Already set; nothing changed."
    )


@main.group("eval")
def eval_group() -> None:
    """The design eval set: list tasks, run them against a model, write a report."""


@eval_group.command("list")
def eval_list() -> None:
    from design_agent.evals.runner import EVAL_ROOT
    from design_agent.evals.tasks import load_tasks

    tasks = load_tasks(_root() / EVAL_ROOT / "tasks.json")
    for task in tasks.tasks:
        needs = f"  needs {', '.join(task.needs)}" if task.needs else ""
        click.echo(
            f"{task.id:22} {task.kind:10} ${task.budget.usd:<5g} {task.budget.minutes:g} min{needs}"
        )


@eval_group.command("run")
@click.option(
    "--model",
    "models",
    multiple=True,
    help="provider:model; repeat for a matrix (default: DESIGN_AGENT_MODEL).",
)
@click.option("--task", "task_ids", multiple=True, help="Task ids (default: all).")
@click.option("--out", "out", type=click.Path(path_type=Path), default=None, help="Report folder.")
@click.option("--yes", is_flag=True, help="Run without asking (the budget is still printed).")
def eval_run(
    models: tuple[str, ...], task_ids: tuple[str, ...], out: Path | None, yes: bool
) -> None:
    """Run tasks with real models and the Docker sandbox. Spends model and media money."""
    import time as _time

    from design_agent.evals.runner import EVAL_ROOT, copy_task_files, run_task, write_report
    from design_agent.evals.tasks import load_tasks

    root = _root()
    tasks = load_tasks(root / EVAL_ROOT / "tasks.json")
    chosen = [t for t in tasks.tasks if not task_ids or t.id in task_ids]
    matrix = list(models) or [Settings().model]
    budget = sum(t.budget.usd for t in chosen) * len(matrix)
    click.echo(
        f"{len(chosen)} task(s) x {len(matrix)} model(s); budget up to about ${budget:.0f} in model and media spend."
    )
    if not yes and not click.confirm("Run them now?"):
        sys.exit(1)
    out_root = out or root / "workspace" / "out" / f"eval-{_time.strftime('%Y%m%d-%H%M%S')}"

    async def run_all() -> list:  # type: ignore[type-arg]
        results = []
        for model in matrix:
            for task in chosen:
                click.echo(f"{model} · {task.id} …")
                result = await run_task(
                    task,
                    root,
                    model,
                    out_root / model.replace(":", "_").replace("/", "_"),
                    set_brand=tasks.brand,
                )
                click.echo(
                    f"  {result.status} in {result.seconds / 60:.1f} min, ~${result.usd:.2f} {result.note}"
                )
                results.append(result)
        return results

    results = asyncio.run(run_all())
    for folder in out_root.glob("*"):
        if (folder / "files").is_dir():
            copy_task_files(folder)
    click.echo(f"Report: {write_report(results, tasks, out_root) / 'README.md'}")


@main.command(
    "paper-bridge",
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
        "help_option_names": [],
    },
)
@click.pass_context
def paper_bridge(ctx: click.Context) -> None:
    """Serve this machine's Paper Desktop to a remote agent behind a bearer token (`--help`)."""
    from design_agent.paper_bridge.__main__ import main as bridge_main

    sys.exit(bridge_main(list(ctx.args)))


@main.command("slack")
def slack_command() -> None:
    """Run the self-hosted Slack app (Socket Mode by default; see docs/self-hosting.md)."""
    from design_agent.surfaces.slack.bolt_app import serve as serve_slack

    asyncio.run(serve_slack(_root(), Settings()))


@main.group()
def sandbox() -> None:
    """Build, test and publish the designer's computer."""


@sandbox.command("build")
@click.option(
    "--platform", "platform_", default=None, help="linux/amd64 or linux/arm64 (default: this host)."
)
def sandbox_build(platform_: str | None) -> None:
    """Build the sandbox image the local Docker runner uses."""
    settings = Settings()
    args = [_docker(), "build", "-t", settings.sandbox_image, str(_root() / "sandbox")]
    if platform_:
        args[2:2] = ["--platform", platform_]
    sys.exit(subprocess.call(args))  # noqa: S603 - fixed argv


@sandbox.command("test")
def sandbox_test() -> None:
    """Run the recipe probe in a fresh container of the local image."""
    settings = Settings()
    sys.exit(
        subprocess.call(  # noqa: S603 - fixed argv
            [
                _docker(),
                "run",
                "--rm",
                "--network",
                "none",
                settings.sandbox_image,
                "/opt/design-agent/probe/probe.sh",
            ]
        )
    )


@main.group()
def skills() -> None:
    """Vendored upstream skills (HyperFrames, LangSmith, Deep Agents)."""


@skills.command("verify")
def skills_verify() -> None:
    """Fail if a vendored skill file differs from skills-lock.json."""
    from design_agent.skills_lock import verify

    result = verify(_root())
    for problem in result.problems:
        click.echo(problem, err=True)
    if not result.ok:
        sys.exit(1)
    click.echo(f"{result.files} vendored files match skills-lock.json")


@skills.command("sync-vendor")
@click.option(
    "--upstream",
    "only",
    default=None,
    help="Re-vendor one upstream (hyperframes, langsmith-skills, langchain-skills); default all.",
)
@click.option("--commit", default=None, help="That upstream's commit (default: the pinned one).")
@click.option("--release", default=None, help="Release tag the commit belongs to.")
@click.option("--check-only", is_flag=True, help="Report each upstream's newest version only.")
def skills_sync_vendor(
    only: str | None, commit: str | None, release: str | None, check_only: bool
) -> None:
    """Re-vendor upstream skills unmodified and rewrite the lock; review the diff before merging."""
    from design_agent import skills_lock

    if check_only:
        for key, pin in skills_lock.UPSTREAMS.items():
            if only is not None and key != only:
                continue
            # Tagged upstreams compare releases; branch-pinned ones compare the default branch.
            query = ("releases/latest", ".tag_name") if pin.release else ("commits/HEAD", ".sha")
            latest = subprocess.run(  # noqa: S603 - fixed argv
                [
                    shutil.which("gh") or "gh",
                    "api",
                    f"repos/{pin.repo}/{query[0]}",
                    "--jq",
                    query[1],
                ],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            pinned = f"{pin.release} ({pin.commit[:12]})" if pin.release else pin.commit[:12]
            newest = latest if pin.release else latest[:12]
            click.echo(f"{key}: pinned {pinned}; latest {newest or 'unknown'}")
        return
    try:
        lock = skills_lock.sync(_root(), only=only, commit=commit, release=release)
    except ValueError as error:
        raise click.UsageError(str(error)) from None
    folders = list(skills_lock.vendored_folders(lock))
    files = sum(len(skills_lock.locked_files(folder, entry)) for folder, entry in folders)
    excluded = sum(len(entry["excluded"]) for _, entry in folders)
    pins = ", ".join(f"{key} {up['commit'][:12]}" for key, up in lock["upstreams"].items())
    click.echo(f"vendored {len(folders)} skills, {files} files ({excluded} excluded): {pins}")


@main.command("manifest")
def manifest() -> None:
    """Print the workspace staging manifest (generated, never hand-edited)."""
    from design_agent.brand.schema import load_brand_pack
    from design_agent.workspace.manifest import build_manifest

    root = _root()
    pack = load_brand_pack(Settings().resolved_brand_path(root), project_root=root)
    click.echo(build_manifest(root, pack).to_json())


if __name__ == "__main__":
    main()


@sandbox.command("publish")
@click.option("--fs-gib", default=16, show_default=True, help="Filesystem size of the snapshot.")
@click.option("--yes", is_flag=True, help="Publish without asking.")
def sandbox_publish(fs_gib: int, yes: bool) -> None:
    """Build the computer as a LangSmith snapshot and declare it in sandbox/__init__.py."""
    from langsmith.sandbox import SandboxClient

    from design_agent.runtime.sandbox.publish import PublishError, declare_snapshot, publish

    settings = Settings()
    if settings.langsmith_api_key is None:
        click.echo(
            "LANGSMITH_API_KEY is not set; publishing needs your LangSmith workspace.", err=True
        )
        sys.exit(1)
    if not yes and not click.confirm(
        f"This builds a {fs_gib} GiB snapshot in your LangSmith workspace (sandbox time is billed). Continue?"
    ):
        sys.exit(1)
    click.echo(
        "Building the agent's computer. This takes about 10-15 minutes; leave it running. It is "
        "only the sandbox image, once per workspace: `uv run mda deploy` deploys the agent itself."
    )
    started = time.monotonic()
    client = SandboxClient(api_key=settings.langsmith_api_key.get_secret_value())
    try:
        published = publish(client, _root(), fs_gib=fs_gib, say=click.echo)
    except PublishError as error:
        click.echo(f"Not published: {error}", err=True)
        sys.exit(1)
    declare_snapshot(_root(), published.snapshot_name)
    minutes = round((time.monotonic() - started) / 60)
    click.echo(
        f"Published {published.snapshot_name} in {minutes} min; sandbox/__init__.py now declares it."
    )
    click.echo(
        f"Local and self-hosted LangSmith sandboxes: DESIGN_AGENT_SANDBOX_SNAPSHOT={published.snapshot_name}"
    )


@brand.command("init")
@click.option("--force", is_flag=True, help="Replace an existing workspace/brand/.")
def brand_init(force: bool) -> None:
    """Start your pack in workspace/brand/ from the sample brand (then edit it)."""
    import shutil

    root = _root()
    target = root / "workspace" / "brand"
    if (target / "brand.toml").exists() and not force:
        click.echo("workspace/brand/ already holds a pack; --force replaces it.", err=True)
        sys.exit(1)
    # The folder's README is tracked, and the sample's LICENSE covers only the sample's files.
    shutil.copytree(
        root / "examples" / "brands" / "example-studio",
        target,
        dirs_exist_ok=True,
        ignore=lambda folder, _names: (
            {"README.md", "LICENSE"} if Path(folder).name == "example-studio" else set()
        ),
    )
    click.echo(
        "Copied the sample brand to workspace/brand/. Replace its content with yours (its logos "
        "too); the brand-onboarding skill walks through it, and `brand validate` checks it."
    )


@main.group()
def fonts() -> None:
    """Check the brand's fonts and their licenses."""


@fonts.command("verify")
def fonts_verify() -> None:
    """Every brand font file is present with its recorded checksum and the family fonts.toml names,
    and every open font is licensed."""
    from PIL import ImageFont

    from design_agent.brand.schema import BrandPackError, load_brand_pack

    root = _root()
    problems: list[str] = []
    try:
        pack = load_brand_pack(Settings().resolved_brand_path(root), project_root=root)
        for font in pack.fonts.fonts:
            # The sandbox resolves fonts by this name (fontconfig's family[0]), so a family that
            # differs from the file's own passes the checksum and fails at render time.
            try:
                inside = ImageFont.truetype(str(pack.font_path(font, root)), 12).getname()[0]
            except OSError:
                inside = None
            if inside is not None and inside != font.family:
                problems.append(
                    f'{font.file}: fonts.toml says family "{font.family}", the file says "{inside}"'
                )
                continue
            click.echo(f"ok  {font.family:20} {font.file}")
    except BrandPackError as error:
        problems.append(str(error))
    licenses = (root / "fonts" / "LICENSES.md").read_text(encoding="utf-8")
    for path in sorted((root / "fonts").glob("*.[ot]tf")):
        if path.name not in licenses:
            problems.append(f"fonts/{path.name} is not listed in fonts/LICENSES.md")
    for problem in problems:
        click.echo(problem, err=True)
    sys.exit(1 if problems else 0)


@sandbox.command("use")
@click.argument("snapshot")
def sandbox_use(snapshot: str) -> None:
    """Use LangSmith sandboxes from a published snapshot for local and self-hosted runs."""
    from design_agent.envfile import write_env

    write_env(
        _root(), {"DESIGN_AGENT_SANDBOX": "langsmith", "DESIGN_AGENT_SANDBOX_SNAPSHOT": snapshot}
    )
    click.echo(f"Local and self-hosted runs now clone {snapshot} (DESIGN_AGENT_SANDBOX=langsmith).")


@main.group("test")
def connectivity() -> None:
    """Check connections with real calls: model, sandbox, Paper, Slack, database. Costs cents."""


@connectivity.command("model")
def test_model() -> None:
    from design_agent.models.factory import build_chat_model

    answer = asyncio.run(
        build_chat_model(Settings(), "lead").ainvoke("Reply with the single word OK.")
    )
    ok = "OK" in str(answer.content).upper()
    click.echo("model: ok" if ok else "model: answered, but not as asked")
    sys.exit(0 if ok else 1)


@connectivity.command("sandbox")
def test_sandbox() -> None:
    from design_agent.runtime.sandbox import select_binding

    binding = select_binding(Settings(), _root())
    if binding.runner is None:
        click.echo(f"sandbox: {binding.name} (no probe for this backend here)")
        return
    result = binding.runner.exec(
        "connectivity-test", "/opt/design-agent/probe/probe.sh", timeout=600
    )
    binding.runner.stop_all()
    click.echo(
        f"sandbox: {'ok' if result.exit_code == 0 else 'failed'}: {result.output.strip()[-300:]}"
    )
    sys.exit(0 if result.exit_code == 0 else 1)


@connectivity.command("paper")
def test_paper() -> None:
    from design_agent.tools.mcp import load_mcp_tools
    from design_agent.tools.paper import PaperConfigError, paper_server

    try:
        server = paper_server(Settings(), runtime="local")
    except PaperConfigError as error:
        click.echo(f"paper: {error}", err=True)
        sys.exit(1)
    if server is None:
        click.echo("paper: off")
        return
    loaded = asyncio.run(load_mcp_tools([server]))
    if loaded.failed:
        click.echo(f"paper: not reachable ({loaded.failed[server.name]})", err=True)
        sys.exit(1)
    click.echo(f"paper: ok, {len(loaded.tools)} tools")


@connectivity.command("slack")
def test_slack() -> None:
    from design_agent.surfaces.slack.client import SlackClient, SlackError

    settings = Settings()
    if settings.slack_bot_token is None:
        click.echo("slack: SLACK_BOT_TOKEN is not set (self-hosted Slack only)", err=True)
        sys.exit(1)

    async def check() -> str:
        client = SlackClient(settings.slack_bot_token.get_secret_value())  # type: ignore[union-attr]
        try:
            identity = await client.identity()
            return f"ok, bot {identity.user_id} in team {identity.team_id}"
        finally:
            await client.aclose()

    try:
        click.echo(f"slack: {asyncio.run(check())}")
    except SlackError as error:
        click.echo(f"slack: {error.code}", err=True)
        sys.exit(1)


@connectivity.command("db")
def test_db() -> None:
    from design_agent.runtime.persistence import open_persistence, workspace_of

    settings = Settings()

    async def check() -> None:
        async with open_persistence(settings, workspace_of(settings, _root())) as (_saver, store):
            await store.aput(("design_agent", "connectivity"), "ping", {"ok": True})
            await store.adelete(("design_agent", "connectivity"), "ping")

    asyncio.run(check())
    click.echo(
        "db: ok (" + ("Postgres" if settings.database_url else "SQLite in workspace/state") + ")"
    )
