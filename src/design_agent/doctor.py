"""`design-agent doctor`: explain what is configured and what is missing, never print a secret."""

from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from design_agent.brand.schema import BrandPackError, load_brand_pack
from design_agent.config import Settings
from design_agent.models.factory import Role, resolve_model
from design_agent.models.registry import ModelConfigurationError, ToolDisclosure

Status = Literal["ok", "warn", "fail"]
PACKAGES = (
    "deepagents",
    "langchain",
    "langgraph",
    "langchain-anthropic",
    "langchain-openai",
)
PROVIDER_KEYS = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "google_genai": "google_api_key",
}


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str


def _check_python() -> Check:
    ok = sys.version_info >= (3, 11)
    return Check("python", "ok" if ok else "fail", f"{platform.python_version()} (3.11+ required)")


def _check_packages() -> Check:
    versions = []
    for name in PACKAGES:
        try:
            versions.append(f"{name} {importlib.metadata.version(name)}")
        except importlib.metadata.PackageNotFoundError:
            return Check("packages", "fail", f"{name} is not installed; run `uv sync`")
    return Check("packages", "ok", ", ".join(versions))


def _check_models(settings: Settings) -> list[Check]:
    checks: list[Check] = []
    roles: tuple[Role, ...] = ("lead", "helper", "look")
    for role in roles:
        try:
            resolved = resolve_model(settings, role)
        except (ModelConfigurationError, ValueError) as error:
            checks.append(Check(f"model:{role}", "fail", str(error)))
            continue
        caps = resolved.caps
        note = (
            "registered"
            if caps.verified
            else "not in the registry: portable path, no provider features assumed"
        )
        disclosure = (
            "native tool search"
            if caps.disclosure is ToolDisclosure.PROVIDER_NATIVE
            else "portable tool selector"
        )
        checks.append(
            Check(
                f"model:{role}",
                "ok" if caps.verified else "warn",
                f"{resolved.spec} effort={resolved.effort or 'default'} ({note}; {disclosure})",
            )
        )
    spec = settings.lead_model()
    provider = spec.upstream.provider if spec.via_gateway else spec.provider
    if spec.via_gateway:
        has_key = (
            settings.langsmith_gateway_api_key is not None or settings.langsmith_api_key is not None
        )
        checks.append(
            Check(
                "model:key",
                "ok" if has_key else "warn",
                "LangSmith Gateway key " + ("set" if has_key else "missing"),
            )
        )
    elif field := PROVIDER_KEYS.get(provider):
        has_key = getattr(settings, field) is not None
        name = field.upper()
        checks.append(
            Check(
                "model:key",
                "ok" if has_key else "warn",
                f"{name} {'set' if has_key else 'missing: `demo` works without it, `ask` does not'}",
            )
        )
    return checks


def missing_model_key(settings: Settings) -> str | None:
    """The setting the lead model needs and lacks, or None (the CLI checks this before a turn)."""
    for check in _check_models(settings):
        if check.name == "model:key" and check.status != "ok":
            return (
                check.detail.split(" ")[0]
                if not check.detail.startswith("LangSmith")
                else "LANGSMITH_GATEWAY_API_KEY"
            )
    return None


def _check_brand(settings: Settings, root: Path) -> Check:
    path = settings.resolved_brand_path(root)
    try:
        pack = load_brand_pack(path, project_root=root)
    except BrandPackError as error:
        return Check("brand", "fail", "; ".join(error.problems[:6]))
    sample = "sample brand" if "examples/brands" in str(path) else "your brand"
    return Check(
        "brand",
        "ok",
        f"{pack.brand.name} ({sample}, {path.relative_to(root) if path.is_relative_to(root) else path}); fonts: {', '.join(pack.required_families())}",
    )


def _check_sandbox(settings: Settings) -> Check:
    if settings.sandbox == "host":
        return Check(
            "sandbox", "warn", "host mode: renderers run on this machine (development only)"
        )
    from design_agent.runtime.sandbox.docker import DockerSandboxRunner

    available, reason = DockerSandboxRunner(image=settings.sandbox_image).available()
    return Check(
        "sandbox",
        "ok" if available else "fail",
        f"Docker image {settings.sandbox_image}" if available else reason,
    )


def _check_node() -> Check:
    node = shutil.which("node")
    return Check(
        "node",
        "ok" if node else "warn",
        "host Node found (gate unit tests)"
        if node
        else "Node not on PATH: gate unit tests skip; the sandbox has its own Node",
    )


def _check_mcp(root: Path) -> Check:
    from design_agent.tools.mcp import McpConfigError, declared_servers

    try:
        servers = declared_servers(root)
    except McpConfigError as error:
        return Check("mcp", "fail", f"config/mcp.toml: {error}")
    if not servers:
        return Check("mcp", "ok", "no MCP servers declared")
    unset = [s.name for s in servers if s.headers_env and s.headers(dict(os.environ)) is None]
    names = ", ".join(s.name for s in servers)
    return Check(
        "mcp",
        "warn" if unset else "ok",
        f"{names}" + (f"; missing credentials for {', '.join(unset)}" if unset else ""),
    )


def run_checks(settings: Settings, root: Path) -> list[Check]:
    return [
        _check_python(),
        _check_packages(),
        *_check_models(settings),
        _check_brand(settings, root),
        _check_sandbox(settings),
        _check_node(),
        _check_mcp(root),
    ]


def doctor_main(root: Path, *, as_json: bool = False) -> int:
    try:
        settings = Settings()
    except Exception as error:  # noqa: BLE001 - pydantic errors carry field names, not values
        print(f"configuration error: {type(error).__name__}: {str(error).splitlines()[0]}")
        return 1
    checks = run_checks(settings, root)
    if as_json:
        print(json.dumps([asdict(c) for c in checks], indent=2))
    else:
        marks = {"ok": "ok  ", "warn": "warn", "fail": "FAIL"}
        for check in checks:
            print(f"[{marks[check.status]}] {check.name:14} {check.detail}")
    return 1 if any(c.status == "fail" for c in checks) else 0
