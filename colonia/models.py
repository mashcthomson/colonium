from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    QUEUED = "queued"
    TYPING = "typing"
    DONE = "done"
    AUTH_REQUIRED = "auth_required"
    TIMEOUT = "timeout"
    ERROR = "error"
    SKIPPED = "skipped"


class DesktopMode(str, Enum):
    """How Colonia isolates browser windows from your main desktop."""

    XEPHYR = "xephyr"
    WORKSPACE = "workspace"
    CURRENT = "current"


class ServiceName(str, Enum):
    CHATGPT = "chatgpt"
    CLAUDE = "claude"
    GEMINI = "gemini"
    GROK = "grok"
    PERPLEXITY = "perplexity"


DEFAULT_SERVICE_ORDER: tuple[ServiceName, ...] = (
    ServiceName.GEMINI,
    ServiceName.CLAUDE,
    ServiceName.GROK,
    ServiceName.PERPLEXITY,
    ServiceName.CHATGPT,
)


def order_services(services: list[ServiceName]) -> list[ServiceName]:
    order = {service: index for index, service in enumerate(DEFAULT_SERVICE_ORDER)}
    return sorted(services, key=lambda service: order.get(service, len(order)))


SERVICE_URLS: dict[ServiceName, str] = {
    ServiceName.GEMINI: "https://gemini.google.com",
    ServiceName.CLAUDE: "https://claude.ai/new",
    ServiceName.GROK: "https://grok.com",
    ServiceName.PERPLEXITY: "https://www.perplexity.ai",
    ServiceName.CHATGPT: "https://chatgpt.com",
}


class BrowserInstance(BaseModel):
    name: str
    cdp_port: int
    profile_dir: str
    enabled: bool = True
    pool: str = "active"  # active | reserve


class DesktopConfig(BaseModel):
    mode: DesktopMode = DesktopMode.XEPHYR
    display: str = ":20"
    workspace_index: int = 1
    width: int = 1920
    height: int = 1080
    xephyr_binary: str = "Xephyr"
    chrome_binary: str = "google-chrome"
    window_manager: str | None = None


class ColoniaConfig(BaseModel):
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".colonia")
    desktop: DesktopConfig = Field(default_factory=DesktopConfig)
    browsers: list[BrowserInstance] = Field(default_factory=list)
    default_timeout_ms: int = 300_000
    max_concurrent_browsers: int = 4
    max_concurrent_per_service: int = 2
    use_wave: bool = True
    wave_settle_ms: int = 8000

    @property
    def profiles_dir(self) -> Path:
        return self.data_dir / "profiles"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def state_dir(self) -> Path:
        return self.data_dir / "state"


class CouncilResponse(BaseModel):
    browser: str
    service: str
    model_label: str = ""
    status: TaskStatus
    text: str = ""
    url: str | None = None
    latency_ms: int = 0
    error: str | None = None
    attachments_sent: list[str] = Field(default_factory=list)
    artifacts_received: list["ArtifactRecord"] = Field(default_factory=list)


class ArtifactRecord(BaseModel):
    source: str
    name: str
    path: str
    url: str | None = None
    mime_type: str | None = None
    size_bytes: int = 0


class CouncilJobRequest(BaseModel):
    prompt: str
    session_id: str | None = None
    files: list[Path] = Field(default_factory=list)
    browsers: list[str] = Field(default_factory=lambda: ["all"])
    services: list[ServiceName] = Field(default_factory=lambda: list(DEFAULT_SERVICE_ORDER))
    fresh_chat: bool = False
    include_all_browsers: bool = False
    timeout_ms: int | None = None


class CouncilJobSummary(BaseModel):
    total_tasks: int = 0
    ok: int = 0
    failed: int = 0
    auth_required: int = 0
    skipped: int = 0


class CouncilJobResult(BaseModel):
    job_id: str
    query: str
    started_at: str
    completed_at: str | None = None
    summary: CouncilJobSummary = Field(default_factory=CouncilJobSummary)
    responses: list[CouncilResponse] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
