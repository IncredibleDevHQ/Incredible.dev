"""Typed process settings. Every value comes from the environment or `.env`; secrets never print."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RuntimeName = Literal["local", "mda", "self_hosted"]
SandboxChoice = Literal["auto", "mda", "langsmith", "docker", "host"]
PaperMode = Literal["off", "local", "bridged"]
SlackTransport = Literal["socket_mode", "http"]
CacheTtl = Literal["5m", "1h", "off"]

DEFAULT_MODEL_SPEC = "anthropic:claude-opus-5-5"
SAMPLE_BRAND = Path("examples/brands/example-studio")
DEFAULT_SANDBOX_IMAGE = "design-agent-sandbox:local"


class ModelSpec(BaseModel):
    """A parsed `provider:model` string. `langsmith:provider/model` selects the optional gateway."""

    model_config = ConfigDict(frozen=True)

    provider: str
    model: str

    @classmethod
    def parse(cls, raw: str, *, setting: str = "DESIGN_AGENT_MODEL") -> ModelSpec:
        provider, sep, model = raw.strip().partition(":")
        if not sep or not provider.strip() or not model.strip():
            raise ValueError(f"{setting} must look like 'provider:model', got {raw!r}")
        return cls(provider=provider.strip().lower(), model=model.strip())

    @property
    def via_gateway(self) -> bool:
        return self.provider == "langsmith"

    @property
    def upstream(self) -> ModelSpec:
        """The provider and model behind a gateway spec (`langsmith:anthropic/x` -> anthropic:x)."""
        if not self.via_gateway:
            return self
        provider, sep, model = self.model.partition("/")
        if not sep or not provider or not model:
            raise ValueError("a gateway model must look like 'langsmith:provider/model'")
        return ModelSpec(provider=provider.lower(), model=model)

    def __str__(self) -> str:
        return f"{self.provider}:{self.model}"


def _alias(*names: str) -> AliasChoices:
    return AliasChoices(*names)


class Settings(BaseSettings):
    """Process configuration. One instance per process entry; the assembly never reads os.environ."""

    model_config = SettingsConfigDict(
        env_prefix="DESIGN_AGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),
        populate_by_name=True,
    )

    # Models
    model: str = DEFAULT_MODEL_SPEC
    model_effort: str | None = None
    """Lead effort; unset uses the registry default for the model (`high` for Claude 5)."""
    helper_model: str | None = None
    look_model: str | None = None
    tool_selector_model: str | None = None
    learning_model: str | None = None
    """A cheaper model for the post-job review (`learn_from_job`); unset uses a low-effort helper."""
    model_base_url: str | None = None
    model_api_key_env: str | None = None
    """Name of the env var holding the key for a compatible endpoint at `model_base_url`."""
    helper_effort_cap: str | None = None
    """Caps every helper's effort (for example `xhigh`) for cost control."""
    model_timeout_seconds: float = Field(default=600.0, gt=0)
    """Stall ceiling for one model call: a call that never returns is worse than one that fails."""
    cache_ttl: CacheTtl = "1h"
    helper_cache_ttl: CacheTtl = "5m"

    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=_alias("ANTHROPIC_API_KEY")
    )
    openai_api_key: SecretStr | None = Field(
        default=None, validation_alias=_alias("OPENAI_API_KEY")
    )
    google_api_key: SecretStr | None = Field(
        default=None, validation_alias=_alias("GOOGLE_API_KEY")
    )
    langsmith_api_key: SecretStr | None = Field(
        default=None, validation_alias=_alias("LANGSMITH_API_KEY")
    )
    langsmith_gateway_api_key: SecretStr | None = Field(
        default=None, validation_alias=_alias("LANGSMITH_GATEWAY_API_KEY")
    )

    # Runtime and the designer's computer
    runtime: RuntimeName = "local"
    sandbox: SandboxChoice = "auto"
    sandbox_snapshot: str | None = None
    sandbox_image: str = DEFAULT_SANDBOX_IMAGE
    sandbox_vcpus: int = Field(default=8, ge=1, le=64)
    sandbox_mem_gib: int = Field(default=16, ge=1, le=256)
    sandbox_fs_gib: int = Field(default=16, ge=2, le=512)
    sandbox_idle_ttl_seconds: int = Field(default=600, ge=60)
    sandbox_egress_allow: str = ""
    """Comma-separated hosts the sandbox may reach at run time; everything else is denied."""
    max_parallel_builders: int = Field(default=3, ge=1, le=16)
    job_budget_usd: float | None = Field(default=None, gt=0)
    workspace_root: Path = Path("workspace")

    # Brand
    brand_path: Path = Path("workspace/brand")
    private_fonts_dir: Path = Path("private-fonts")

    # Media providers (host tools; keys never enter the sandbox)
    image_model: str = "gpt-image-2.5-flare"
    elevenlabs_api_key: SecretStr | None = Field(
        default=None, validation_alias=_alias("ELEVENLABS_API_KEY")
    )
    groq_api_key: SecretStr | None = Field(default=None, validation_alias=_alias("GROQ_API_KEY"))
    exa_api_key: SecretStr | None = Field(default=None, validation_alias=_alias("EXA_API_KEY"))

    # Paper
    paper_mode: PaperMode = Field(default="off", validation_alias=_alias("PAPER_MODE"))
    paper_mcp_url: str | None = Field(default=None, validation_alias=_alias("PAPER_MCP_URL"))
    paper_bridge_token: SecretStr | None = Field(
        default=None, validation_alias=_alias("PAPER_BRIDGE_TOKEN")
    )
    paper_brand_file_id: str | None = Field(
        default=None, validation_alias=_alias("PAPER_BRAND_FILE_ID")
    )
    paper_drafts_file_id: str | None = Field(
        default=None, validation_alias=_alias("PAPER_DRAFTS_FILE_ID")
    )
    paper_team_id: str | None = Field(default=None, validation_alias=_alias("PAPER_TEAM_ID"))
    paper_allow_deletes: bool = Field(default=False, validation_alias=_alias("PAPER_ALLOW_DELETES"))
    paper_allow_token_writes: bool = Field(
        default=False, validation_alias=_alias("PAPER_ALLOW_TOKEN_WRITES")
    )
    paper_allow_reorg: bool = Field(default=False, validation_alias=_alias("PAPER_ALLOW_REORG"))
    paper_allow_generation: bool = Field(
        default=False, validation_alias=_alias("PAPER_ALLOW_GENERATION")
    )

    # Behavior switches
    enable_progress: bool = True
    enable_footer: bool = True
    enable_steering: bool = True
    trace_host: str | None = None
    """LangSmith UI host for the footer's trace link (for example https://smith.langchain.com).
    Unset, the footer has no link: a trace URL names the workspace, project and run."""
    enable_learning: bool = True
    enable_traces: bool = True
    """`list_traces` and `read_trace`: the agent reads every thread's traces in its own LangSmith
    project with the host's credentials. Turn off where people must not see each other's requests."""
    template_telemetry: bool = True
    """Every run's trace names the template and its version (`ls_template`), so LangChain can count
    deployments of this repository. Nothing about the deployment or its people."""
    enable_tool_clearing: bool = False
    """Server-side clearing of old tool results in helpers' requests (Anthropic only)."""
    timezone: str = "UTC"
    """IANA zone for the date note when the channel does not say whose zone a turn is in."""
    mcp_max_tools: int = Field(default=8, ge=1, le=64)
    """For models without native tool search: MCP tools a selector may expose per call."""

    # MDA Slack appearance
    # MDA's own rule for a Slack app name; checked here so a bad name fails before a deploy does.
    slack_name: str = Field(
        default="Content Studio",
        max_length=35,
        pattern=r"^[A-Za-z0-9_.](?:[A-Za-z0-9 _.\-]*[A-Za-z0-9_.])?$",
    )
    slack_description: str = Field(
        default="On-brand design and motion from a chat thread.", max_length=139
    )
    slack_background_color: str | None = None
    slack_trigger_on_all_messages: bool = False
    slack_allow_bot_triggers: bool = False

    # Self-hosted
    slack_bot_token: SecretStr | None = Field(
        default=None, validation_alias=_alias("SLACK_BOT_TOKEN")
    )
    slack_app_token: SecretStr | None = Field(
        default=None, validation_alias=_alias("SLACK_APP_TOKEN")
    )
    slack_signing_secret: SecretStr | None = Field(
        default=None, validation_alias=_alias("SLACK_SIGNING_SECRET")
    )
    slack_transport: SlackTransport = Field(
        default="socket_mode", validation_alias=_alias("SLACK_TRANSPORT")
    )
    database_url: SecretStr | None = Field(default=None, validation_alias=_alias("DATABASE_URL"))
    api_tokens: SecretStr | None = None
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8080, ge=1, le=65535)

    live_tests: bool = False

    @field_validator(
        "model_effort",
        "helper_effort_cap",
        "helper_model",
        "look_model",
        "tool_selector_model",
        "learning_model",
        "model_base_url",
        "model_api_key_env",
        "sandbox_snapshot",
        "slack_background_color",
        "trace_host",
        "paper_mcp_url",
        "paper_brand_file_id",
        "paper_drafts_file_id",
        "paper_team_id",
        "job_budget_usd",
        "anthropic_api_key",
        "openai_api_key",
        "google_api_key",
        "langsmith_api_key",
        "langsmith_gateway_api_key",
        "elevenlabs_api_key",
        "groq_api_key",
        "exa_api_key",
        "paper_bridge_token",
        "slack_bot_token",
        "slack_app_token",
        "slack_signing_secret",
        "database_url",
        "api_tokens",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def lead_model(self) -> ModelSpec:
        return ModelSpec.parse(self.model)

    def role_model(self, role: Literal["helper", "look", "tool_selector", "learning"]) -> ModelSpec:
        """A role's model, defaulting to the lead's."""
        raw = getattr(self, f"{role}_model")
        if raw is None:
            return self.lead_model()
        return ModelSpec.parse(raw, setting=f"DESIGN_AGENT_{role.upper()}_MODEL")

    def egress_allowlist(self) -> tuple[str, ...]:
        return tuple(h.strip() for h in self.sandbox_egress_allow.split(",") if h.strip())

    def api_token_map(self) -> dict[str, str]:
        """`token:caller,token:caller` as a lookup. Values stay in memory only."""
        if self.api_tokens is None:
            return {}
        result: dict[str, str] = {}
        for pair in self.api_tokens.get_secret_value().split(","):
            token, sep, caller = pair.strip().partition(":")
            if sep and token and caller:
                result[token] = caller
        return result

    def resolved_brand_path(self, root: Path) -> Path:
        """The active brand pack: the configured folder when it has a pack, else the sample brand."""
        configured = self.brand_path if self.brand_path.is_absolute() else root / self.brand_path
        if (configured / "brand.toml").is_file():
            return configured
        return root / SAMPLE_BRAND


def project_root(start: Path | None = None) -> Path:
    """The repository root: the nearest ancestor holding `instructions.md` and `skills/`."""
    here = (start or Path(__file__)).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "instructions.md").is_file() and (candidate / "skills").is_dir():
            return candidate
    return Path.cwd()
