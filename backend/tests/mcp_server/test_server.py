"""End-to-end tool tests through a real MCP client connected in-process."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from mcp.client import Client
from sqlalchemy import Engine
from sqlmodel import Session, select

from tests.conftest import AS_OF, make_memory_engine
from warehouse_ops.db.models import ToolCallLog
from warehouse_ops.db.seed import seed_database
from warehouse_ops.mcp_server.server import create_server

pytestmark = pytest.mark.anyio  # run the async tests on asyncio


@pytest.fixture(scope="module")
def engine() -> Engine:
    # Own database, because these tests write to tool_call_log.
    engine = make_memory_engine()
    seed_database(engine, seed=42, as_of=AS_OF)
    return engine


@pytest.fixture
async def client(engine: Engine) -> AsyncIterator[Client]:
    async with Client(create_server(engine, now=lambda: AS_OF)) as client:
        yield client


async def call(client: Client, tool: str, args: dict[str, Any]) -> Any:
    result = await client.call_tool(tool, args)
    assert not result.is_error, result.content
    assert result.structured_content is not None
    return result.structured_content


async def test_tools_are_listed_as_read_only(client: Client) -> None:
    tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {"list_short_picks", "find_stock", "list_replenishment_needs"}
    for tool in tools.values():
        assert tool.description
        assert tool.annotations is not None and tool.annotations.read_only_hint


def _formats(schema: Any) -> list[str]:
    """Every "format" keyword anywhere in a JSON schema."""
    if isinstance(schema, dict):
        found = [schema["format"]] if isinstance(schema.get("format"), str) else []
        return found + [f for value in schema.values() for f in _formats(value)]
    if isinstance(schema, list):
        return [f for item in schema for f in _formats(item)]
    return []


async def test_schemas_do_not_declare_date_time_format(client: Client) -> None:
    # Naive local times would fail strict clients' "date-time" (RFC 3339) validation.
    for tool in (await client.list_tools()).tools:
        assert "date-time" not in _formats(tool.input_schema), tool.name
        assert "date-time" not in _formats(tool.output_schema), tool.name


async def test_since_accepts_local_time(client: Client) -> None:
    rows = (await call(client, "list_short_picks", {"since": "2026-05-30T06:00"}))["result"]
    assert rows


async def test_list_short_picks(client: Client) -> None:
    rows = (await call(client, "list_short_picks", {"zone": "A"}))["result"]
    assert rows and all(r["zone"] == "A" for r in rows)


async def test_find_stock(client: Client) -> None:
    needs = (await call(client, "list_replenishment_needs", {}))["result"]
    sku_code = needs[0]["sku_code"]
    report = await call(client, "find_stock", {"sku_code": sku_code})
    assert report["sku"]["sku_code"] == sku_code
    assert report["pick_face"]["location"] == needs[0]["location"]


async def test_unknown_sku_is_a_tool_error(client: Client) -> None:
    result = await client.call_tool("find_stock", {"sku_code": "00000"})
    assert result.is_error
    assert "No SKU with code '00000'" in str(result.content)


async def test_invalid_zone_is_rejected(client: Client) -> None:
    result = await client.call_tool("list_replenishment_needs", {"zone": "Z"})
    assert result.is_error


async def test_calls_are_logged(client: Client, engine: Engine) -> None:
    await client.call_tool("find_stock", {"sku_code": "00000"})
    await call(client, "list_replenishment_needs", {"zone": "B"})

    with Session(engine) as session:
        logs = session.exec(select(ToolCallLog)).all()
    last_two = logs[-2:]
    assert [log.tool for log in last_two] == ["find_stock", "list_replenishment_needs"]
    assert last_two[0].result_summary.startswith("error: No SKU")
    assert last_two[1].result_summary.endswith("results")
    assert '"zone": "B"' in last_two[1].args_json
    assert all(log.ts == AS_OF for log in last_two)
