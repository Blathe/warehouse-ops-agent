"""What a Claude request costs, from the per-model rates in ``MODEL_OPTIONS``.

Prompt caching isn't used, so input plus output tokens is the whole bill. If caching is
added, cache reads and writes need their own rates here.
"""

from warehouse_ops.agent.models import MODEL_OPTIONS


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    option = next(m for m in MODEL_OPTIONS if m.id == model)
    return (input_tokens * option.input_per_mtok + output_tokens * option.output_per_mtok) / 1e6
