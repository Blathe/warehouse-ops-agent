"""The agent must never be able to decide or finish tasks (CLAUDE.md: approval is human-only)."""

from warehouse_ops.agent.tools import TOOLS


def test_the_only_write_tool_is_creating_a_proposal() -> None:
    assert {name for name, tool in TOOLS.items() if tool.writes} == {"create_replenishment_task"}


def test_no_tool_can_approve_reject_or_complete_a_task() -> None:
    forbidden = (
        "decide",
        "approve",
        "reject",
        "complete",
        "finish",
        "simulat",
        "accept",
        "recount",
        "adjust",
    )
    assert not [name for name in TOOLS if any(word in name for word in forbidden)]


def test_cycle_count_tools_only_read() -> None:
    for name in (
        "list_discrepancies",
        "get_inventory_history",
        "get_nearby_stock",
        "list_open_picks",
    ):
        assert name in TOOLS and not TOOLS[name].writes
