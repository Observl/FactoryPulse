"""Editable local configuration; no credentials or executable handler paths."""
import json
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .agent_registry import REGISTRY

class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    max_rounds: int = Field(default=8, ge=1, le=16)
    max_calls_per_round: int = Field(default=5, ge=1, le=8)
    max_tokens: int = Field(default=4096, ge=256, le=8192)
    initial_timeout_seconds: int = Field(default=30, ge=1, le=300)
    progress_extension_seconds: int = Field(default=10, ge=1, le=60)
    # Accepted only for migration from older config files; never used for budgeting.
    total_timeout_seconds: int | None = Field(default=None, ge=5, le=300, exclude=True)
    disabled_tools: list[str] = Field(default_factory=list)
    tool_timeout_seconds: int = Field(default=15, ge=1, le=60)
    read_retries: int = Field(default=1, ge=0, le=2)
    max_input_tokens: int = Field(default=96000, ge=2000, le=256000)
    max_run_cost_usd: float | None = Field(default=None, gt=0, le=100, exclude=True)
    input_usd_per_million: float | None = Field(default=None, ge=0, le=1000, exclude=True)
    output_usd_per_million: float | None = Field(default=None, ge=0, le=1000, exclude=True)

    @field_validator("disabled_tools")
    @classmethod
    def known_tools(cls, values):
        if set(values) - REGISTRY.keys():
            raise ValueError("disabled_tools 包含未注册工具")
        return values

def load_config():
    path = Path(__file__).resolve().parent.parent / "config" / "agent.json"
    return AgentConfig.model_validate(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else AgentConfig()
