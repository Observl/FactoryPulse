"""Editable local configuration; no credentials or executable handler paths."""
import json
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .agent_registry import REGISTRY

class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    max_rounds: int = Field(default=4, ge=1, le=8)
    max_calls_per_round: int = Field(default=5, ge=1, le=8)
    max_tokens: int = Field(default=1200, ge=256, le=2400)
    total_timeout_seconds: int = Field(default=60, ge=5, le=90)
    disabled_tools: list[str] = Field(default_factory=list)
    tool_timeout_seconds: int = Field(default=15, ge=1, le=60)
    read_retries: int = Field(default=1, ge=0, le=2)
    max_input_tokens: int = Field(default=32000, ge=2000, le=64000)
    max_run_cost_usd: float = Field(default=0.50, gt=0, le=100)
    input_usd_per_million: float = Field(default=10, ge=0, le=1000)
    output_usd_per_million: float = Field(default=30, ge=0, le=1000)

    @field_validator("disabled_tools")
    @classmethod
    def known_tools(cls, values):
        if set(values) - REGISTRY.keys():
            raise ValueError("disabled_tools 包含未注册工具")
        return values

def load_config():
    path = Path(__file__).resolve().parent.parent / "config" / "agent.json"
    return AgentConfig.model_validate(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else AgentConfig()
