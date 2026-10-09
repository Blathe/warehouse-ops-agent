"""The Claude models the chat can use, and the request settings each one needs.

Models differ in which request options they accept: server-side fallbacks are only
offered for the Opus/Sonnet 5.x models (not Haiku 5.5), so those options are set per model.
"""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

# On a safety decline, the API re-runs the request on a fallback model it picks.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ModelOption(BaseModel):
    id: str
    label: str
    input_per_mtok: float  # USD per million input tokens
    output_per_mtok: float  # USD per million output tokens


@dataclass(frozen=True)
class _Settings:
    option: ModelOption
    effort: str | None  # None = don't send output_config
    fallbacks: bool


_MODELS = [
    _Settings(
        ModelOption(
            id="claude-opus-5-5", label="Claude Opus 5.5", input_per_mtok=4, output_per_mtok=20
        ),
        effort="medium",
        fallbacks=True,
    ),
    _Settings(
        ModelOption(
            id="claude-sonnet-5-5", label="Claude Sonnet 5.5", input_per_mtok=2, output_per_mtok=10
        ),
        effort="medium",
        fallbacks=True,
    ),
    _Settings(
        ModelOption(
            id="claude-haiku-5-5", label="Claude Haiku 5.5", input_per_mtok=0.1, output_per_mtok=0.5
        ),
        effort="medium",
        fallbacks=False,
    ),
]

DEFAULT_MODEL = "claude-opus-5-5"
MODEL_OPTIONS = [m.option for m in _MODELS]
_BY_ID = {m.option.id: m for m in _MODELS}


def is_supported(model: str) -> bool:
    return model in _BY_ID


def request_options(model: str) -> dict[str, Any]:
    """Model-specific keyword arguments for ``client.beta.messages.create``."""
    settings = _BY_ID[model]
    options: dict[str, Any] = {}
    if settings.effort:
        options["output_config"] = {"effort": settings.effort}
    if settings.fallbacks:
        options["betas"] = [FALLBACK_BETA]
        options["fallbacks"] = "default"
    return options
