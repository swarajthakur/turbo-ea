"""Unit tests for the artifact-import write tools.

These mirror the patterns in ``test_server.py`` — fake the auth token, mock
the ``TurboEAClient`` HTTP shim, invoke the tool function directly, and
assert (a) the right path and JSON body were forwarded and (b) the JSON
response flows back through ``_fmt``.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from turbo_ea_mcp import server


@pytest.fixture
def fake_token(monkeypatch):
    """Pretend a user is logged in so tool auth checks pass."""
    monkeypatch.setattr(server, "_stdio_token", "test-token")
    yield "test-token"


def _patched_post(payload):
    mock = AsyncMock(return_value=payload)
    return patch.object(server.TurboEAClient, "post", mock), mock


def _patched_put(payload):
    mock = AsyncMock(return_value=payload)
    return patch.object(server.TurboEAClient, "put", mock), mock


def _patched_get(payload):
    mock = AsyncMock(return_value=payload)
    return patch.object(server.TurboEAClient, "get", mock), mock


def _parse(s: str) -> dict | list:
    return json.loads(s)


# ── create_cards_bulk ──────────────────────────────────────────────────────


class TestCreateCardsBulk:
    @pytest.mark.asyncio
    async def test_dry_run_default(self, fake_token):
        patcher, mock = _patched_post(
            {
                "results": [
                    {"row_index": 0, "status": "created", "id": "card-1"},
                ],
                "created": 1,
                "failed": 0,
                "dry_run": True,
            }
        )
        with patcher:
            out = await server.create_cards_bulk(
                cards=[{"row_index": 0, "type": "Application", "name": "Test App"}]
            )
        mock.assert_awaited_once()
        args, kwargs = mock.call_args
        assert args[0] == "/cards/bulk-create"
        assert kwargs["json"]["dry_run"] is True
        assert _parse(out)["dry_run"] is True

    @pytest.mark.asyncio
    async def test_commit(self, fake_token):
        patcher, mock = _patched_post(
            {"results": [], "created": 0, "failed": 0, "dry_run": False}
        )
        with patcher:
            await server.create_cards_bulk(
                cards=[{"row_index": 0, "type": "Application", "name": "X"}],
                dry_run=False,
            )
        _, kwargs = mock.call_args
        assert kwargs["json"]["dry_run"] is False
        assert kwargs["json"]["cards"][0]["name"] == "X"

    @pytest.mark.asyncio
    async def test_single_row(self, fake_token):
        patcher, mock = _patched_post({"results": [], "created": 0, "failed": 0})
        with patcher:
            await server.create_cards_bulk(
                cards=[
                    {
                        "row_index": 7,
                        "type": "Application",
                        "name": "Single",
                        "attributes": {"businessCriticality": "high"},
                    }
                ],
                dry_run=False,
            )
        _, kwargs = mock.call_args
        cards = kwargs["json"]["cards"]
        assert len(cards) == 1
        assert cards[0]["attributes"] == {"businessCriticality": "high"}

    @pytest.mark.asyncio
    async def test_backend_validation_error_surfaces(self, fake_token):
        # Backend reports per-row failure for unknown type — the tool just
        # passes the payload through.
        patcher, mock = _patched_post(
            {
                "results": [
                    {
                        "row_index": 0,
                        "status": "failed",
                        "error": "Unknown card type: App",
                    }
                ],
                "created": 0,
                "failed": 1,
                "dry_run": True,
            }
        )
        with patcher:
            out = await server.create_cards_bulk(
                cards=[{"row_index": 0, "type": "App", "name": "Bad"}]
            )
        data = _parse(out)
        assert data["failed"] == 1
        assert "Unknown card type" in data["results"][0]["error"]


# ── resolve_card_refs ──────────────────────────────────────────────────────


class TestResolveCardRefs:
    @pytest.mark.asyncio
    async def test_pass_through(self, fake_token):
        patcher, mock = _patched_post(
            {
                "results": [
                    {
                        "row": 0,
                        "column": "parent",
                        "status": "resolved",
                        "id": "card-9",
                    }
                ]
            }
        )
        with patcher:
            out = await server.resolve_card_refs(
                refs=[
                    {
                        "row": 0,
                        "column": "parent",
                        "type": "BusinessCapability",
                        "ref": "Sales / CRM",
                    }
                ]
            )
        mock.assert_awaited_once()
        args, kwargs = mock.call_args
        assert args[0] == "/cards/resolve-refs"
        assert kwargs["json"]["refs"][0]["ref"] == "Sales / CRM"
        assert _parse(out)["results"][0]["id"] == "card-9"


# ── upsert_relations_bulk ──────────────────────────────────────────────────


class TestUpsertRelationsBulk:
    @pytest.mark.asyncio
    async def test_upsert_dry_run(self, fake_token):
        patcher, mock = _patched_post(
            {
                "results": [{"row_index": 0, "status": "upserted", "relation_id": "r1"}],
                "upserted": 1,
                "deleted": 0,
                "failed": 0,
                "dry_run": True,
            }
        )
        with patcher:
            out = await server.upsert_relations_bulk(
                operations=[
                    {
                        "row_index": 0,
                        "type": "uses",
                        "source": {"id": "src-uuid"},
                        "target": {"id": "tgt-uuid"},
                    }
                ]
            )
        _, kwargs = mock.call_args
        assert kwargs["json"]["dry_run"] is True
        assert _parse(out)["upserted"] == 1

    @pytest.mark.asyncio
    async def test_delete(self, fake_token, monkeypatch):
        # Delete is gated behind MCP_ALLOW_RELATION_DELETE; flip it on for
        # this happy-path forwarding test (the guardrail rejection path
        # has its own test).
        monkeypatch.setattr(server, "MCP_ALLOW_RELATION_DELETE", True)
        patcher, mock = _patched_post(
            {
                "results": [{"row_index": 0, "status": "deleted"}],
                "upserted": 0,
                "deleted": 1,
                "failed": 0,
                "dry_run": False,
            }
        )
        with patcher:
            await server.upsert_relations_bulk(
                operations=[
                    {
                        "row_index": 0,
                        "action": "delete",
                        "type": "uses",
                        "source": {"id": "s"},
                        "target": {"id": "t"},
                    }
                ],
                dry_run=False,
            )
        _, kwargs = mock.call_args
        assert kwargs["json"]["operations"][0]["action"] == "delete"

    @pytest.mark.asyncio
    async def test_type_mismatch_surfaces(self, fake_token):
        # Backend rejects per-row when source.type doesn't match the
        # relation type's expected source.
        patcher, mock = _patched_post(
            {
                "results": [
                    {
                        "row_index": 0,
                        "status": "failed",
                        "error": "Source type 'X' does not match relation type's expected source 'Application'",
                    }
                ],
                "upserted": 0,
                "deleted": 0,
                "failed": 1,
                "dry_run": True,
            }
        )
        with patcher:
            out = await server.upsert_relations_bulk(
                operations=[
                    {
                        "row_index": 0,
                        "type": "uses",
                        "source": {"type": "X", "name": "Bad", "parent_path": []},
                        "target": {"id": "t"},
                    }
                ]
            )
        assert "does not match" in _parse(out)["results"][0]["error"]


# ── create_diagram ─────────────────────────────────────────────────────────


class TestCreateDiagram:
    @pytest.mark.asyncio
    async def test_dry_run_short_circuits(self, fake_token):
        # Dry-run never calls the backend.
        patcher, mock = _patched_post({"id": "should-not-be-called"})
        xml = '<mxGraphModel><object cardId="11111111-2222-3333-4444-555555555555"/></mxGraphModel>'
        with patcher:
            out = await server.create_diagram(name="My Diag", drawio_xml=xml)
        mock.assert_not_called()
        data = _parse(out)
        assert data["dry_run"] is True
        assert data["would_create"]["extracted_card_refs_from_xml"] == [
            "11111111-2222-3333-4444-555555555555"
        ]

    @pytest.mark.asyncio
    async def test_commit_passes_xml(self, fake_token):
        patcher, mock = _patched_post({"id": "diag-1", "name": "My Diag"})
        xml = "<mxGraphModel/>"
        with patcher:
            await server.create_diagram(
                name="My Diag",
                drawio_xml=xml,
                description="…",
                linked_card_ids=["c1"],
                dry_run=False,
            )
        args, kwargs = mock.call_args
        assert args[0] == "/diagrams"
        assert kwargs["json"]["data"]["xml"] == xml
        assert kwargs["json"]["card_ids"] == ["c1"]
        assert kwargs["json"]["type"] == "free_draw"


# ── import_bpmn ────────────────────────────────────────────────────────────


class TestImportBpmn:
    @pytest.mark.asyncio
    async def test_find_existing_then_save_dry_run(self, fake_token, monkeypatch):
        get_payloads = iter(
            [
                {
                    "items": [
                        {"id": "bp-1", "name": "Order to Cash", "parent_id": None}
                    ],
                    "total": 1,
                }
            ]
        )
        get_mock = AsyncMock(side_effect=lambda *a, **kw: next(get_payloads))
        put_mock = AsyncMock(
            return_value={"version": 2, "element_count": 7, "dry_run": True}
        )
        post_mock = AsyncMock()  # must not be called (existing card)
        with (
            patch.object(server.TurboEAClient, "get", get_mock),
            patch.object(server.TurboEAClient, "put", put_mock),
            patch.object(server.TurboEAClient, "post", post_mock),
        ):
            out = await server.import_bpmn(
                business_process_name="Order to Cash",
                bpmn_xml="<bpmn:definitions/>",
            )
        post_mock.assert_not_called()
        put_args, put_kwargs = put_mock.call_args
        assert put_args[0] == "/bpm/processes/bp-1/diagram"
        assert put_kwargs["json"]["dry_run"] is True
        data = _parse(out)
        assert data["business_process_id"] == "bp-1"
        assert data["diagram_result"]["element_count"] == 7

    @pytest.mark.asyncio
    async def test_create_new_passes_description_through(self, fake_token):
        """When the card doesn't exist and the agent provides description /
        attributes, the new BusinessProcess card lands with them."""
        get_mock = AsyncMock(return_value={"items": [], "total": 0})
        post_mock = AsyncMock(
            return_value={
                "results": [{"row_index": 0, "status": "created", "id": "bp-new"}],
                "created": 1,
                "failed": 0,
                "dry_run": False,
            }
        )
        put_mock = AsyncMock(
            return_value={"version": 1, "element_count": 3, "dry_run": False}
        )
        with (
            patch.object(server.TurboEAClient, "get", get_mock),
            patch.object(server.TurboEAClient, "post", post_mock),
            patch.object(server.TurboEAClient, "put", put_mock),
        ):
            await server.import_bpmn(
                business_process_name="New Process",
                bpmn_xml="<bpmn:definitions/>",
                description="Order intake to shipment",
                attributes={"processType": "Core"},
                dry_run=False,
            )
        _, post_kwargs = post_mock.call_args
        card_row = post_kwargs["json"]["cards"][0]
        assert card_row["description"] == "Order intake to shipment"
        assert card_row["attributes"] == {"processType": "Core"}

    @pytest.mark.asyncio
    async def test_create_new_falls_back_to_bpmn_documentation(self, fake_token):
        """When the agent omits a description, the tool seeds it from the
        BPMN's <bpmn:process><bpmn:documentation> child if present."""
        get_mock = AsyncMock(return_value={"items": [], "total": 0})
        post_mock = AsyncMock(
            return_value={
                "results": [{"row_index": 0, "status": "created", "id": "bp-new"}],
                "created": 1,
                "failed": 0,
                "dry_run": False,
            }
        )
        put_mock = AsyncMock(
            return_value={"version": 1, "element_count": 0, "dry_run": False}
        )
        bpmn = (
            '<bpmn:definitions xmlns:bpmn="http://example/">'
            '<bpmn:process id="P1" name="X">'
            "  <bpmn:documentation>Auto-extracted process docs.</bpmn:documentation>"
            "</bpmn:process>"
            "</bpmn:definitions>"
        )
        with (
            patch.object(server.TurboEAClient, "get", get_mock),
            patch.object(server.TurboEAClient, "post", post_mock),
            patch.object(server.TurboEAClient, "put", put_mock),
        ):
            await server.import_bpmn(
                business_process_name="X", bpmn_xml=bpmn, dry_run=False
            )
        _, post_kwargs = post_mock.call_args
        assert (
            post_kwargs["json"]["cards"][0]["description"]
            == "Auto-extracted process docs."
        )

    @pytest.mark.asyncio
    async def test_existing_card_warns_when_description_supplied(
        self, fake_token
    ):
        """Description/attributes passed against a card that already exists
        are ignored (no mutation of pre-existing cards) — but the response
        flags this so the agent can tell the user."""
        get_mock = AsyncMock(
            return_value={
                "items": [{"id": "bp-1", "name": "OnSale", "parent_id": None}],
                "total": 1,
            }
        )
        put_mock = AsyncMock(
            return_value={"version": 1, "element_count": 5, "dry_run": False}
        )
        post_mock = AsyncMock()
        with (
            patch.object(server.TurboEAClient, "get", get_mock),
            patch.object(server.TurboEAClient, "put", put_mock),
            patch.object(server.TurboEAClient, "post", post_mock),
        ):
            out = await server.import_bpmn(
                business_process_name="OnSale",
                bpmn_xml="<bpmn:definitions/>",
                description="trying to set a description",
                attributes={"processType": "Core"},
                dry_run=False,
            )
        post_mock.assert_not_called()  # no card created
        data = _parse(out)
        assert "warning" in data
        assert "description" in data["warning"]
        assert "attributes" in data["warning"]

    @pytest.mark.asyncio
    async def test_commit_response_signals_committed_true(self, fake_token):
        get_mock = AsyncMock(
            return_value={
                "items": [{"id": "bp-1", "name": "X", "parent_id": None}],
                "total": 1,
            }
        )
        put_mock = AsyncMock(
            return_value={"version": 1, "element_count": 2, "dry_run": False}
        )
        with (
            patch.object(server.TurboEAClient, "get", get_mock),
            patch.object(server.TurboEAClient, "put", put_mock),
        ):
            out = await server.import_bpmn(
                business_process_name="X",
                bpmn_xml="<bpmn:definitions/>",
                dry_run=False,
            )
        data = _parse(out)
        assert data["committed"] is True
        assert "next_action" not in data  # only on dry-run

    @pytest.mark.asyncio
    async def test_dry_run_response_signals_not_committed(self, fake_token):
        get_mock = AsyncMock(
            return_value={
                "items": [{"id": "bp-1", "name": "X", "parent_id": None}],
                "total": 1,
            }
        )
        put_mock = AsyncMock(
            return_value={"version": 1, "element_count": 2, "dry_run": True}
        )
        with (
            patch.object(server.TurboEAClient, "get", get_mock),
            patch.object(server.TurboEAClient, "put", put_mock),
        ):
            out = await server.import_bpmn(
                business_process_name="X", bpmn_xml="<bpmn:definitions/>"
            )
        data = _parse(out)
        assert data["committed"] is False
        assert "NOT" in data["next_action"]

    @pytest.mark.asyncio
    async def test_create_new_dry_run_skips_diagram_step(self, fake_token):
        # No matching BusinessProcess card — in dry-run, we preview the
        # would-be card create but skip step 3 (no card_id to attach to).
        get_mock = AsyncMock(return_value={"items": [], "total": 0})
        post_mock = AsyncMock(
            return_value={
                "results": [
                    {"row_index": 0, "status": "created", "id": "would-be-id"}
                ],
                "created": 1,
                "failed": 0,
                "dry_run": True,
            }
        )
        put_mock = AsyncMock()  # must not be called
        with (
            patch.object(server.TurboEAClient, "get", get_mock),
            patch.object(server.TurboEAClient, "post", post_mock),
            patch.object(server.TurboEAClient, "put", put_mock),
        ):
            out = await server.import_bpmn(
                business_process_name="Brand New Process",
                bpmn_xml="<bpmn:definitions/>",
            )
        put_mock.assert_not_called()
        data = _parse(out)
        assert data["dry_run"] is True
        assert data["would_create_business_process"] is True

    @pytest.mark.asyncio
    async def test_multi_match_refuses(self, fake_token):
        get_mock = AsyncMock(
            return_value={
                "items": [
                    {"id": "bp-a", "name": "Order to Cash", "parent_id": "p1"},
                    {"id": "bp-b", "name": "Order to Cash", "parent_id": "p2"},
                ],
                "total": 2,
            }
        )
        with patch.object(server.TurboEAClient, "get", get_mock):
            out = await server.import_bpmn(
                business_process_name="Order to Cash",
                bpmn_xml="<bpmn:definitions/>",
            )
        data = _parse(out)
        assert data["error"] == "ambiguous_business_process"
        assert len(data["candidates"]) == 2

    @pytest.mark.asyncio
    async def test_commit_create_then_save(self, fake_token):
        get_mock = AsyncMock(return_value={"items": [], "total": 0})
        post_mock = AsyncMock(
            return_value={
                "results": [
                    {"row_index": 0, "status": "created", "id": "new-bp-id"}
                ],
                "created": 1,
                "failed": 0,
                "dry_run": False,
            }
        )
        put_mock = AsyncMock(
            return_value={"version": 1, "element_count": 5, "dry_run": False}
        )
        with (
            patch.object(server.TurboEAClient, "get", get_mock),
            patch.object(server.TurboEAClient, "post", post_mock),
            patch.object(server.TurboEAClient, "put", put_mock),
        ):
            out = await server.import_bpmn(
                business_process_name="Brand New Process",
                bpmn_xml="<bpmn:definitions/>",
                dry_run=False,
            )
        # Both steps fired.
        post_mock.assert_awaited_once()
        put_mock.assert_awaited_once()
        put_args, _ = put_mock.call_args
        assert put_args[0] == "/bpm/processes/new-bp-id/diagram"
        data = _parse(out)
        assert data["business_process_id"] == "new-bp-id"
        assert data["business_process_created"] is True


# ── Unauthenticated paths ──────────────────────────────────────────────────


class TestGuardrails:
    """Per-call caps, kill switch, delete rejection."""

    @pytest.mark.asyncio
    async def test_cards_batch_over_cap_rejected(self, fake_token, monkeypatch):
        monkeypatch.setattr(server, "MCP_MAX_CARDS_PER_CALL", 3)
        rows = [
            {"row_index": i, "type": "Application", "name": f"A{i}"} for i in range(4)
        ]
        post_mock = AsyncMock()  # must not be called
        with patch.object(server.TurboEAClient, "post", post_mock):
            out = await server.create_cards_bulk(cards=rows)
        post_mock.assert_not_called()
        data = _parse(out)
        assert data["error"] == "batch_too_large"
        assert data["cap"] == 3
        assert data["received"] == 4

    @pytest.mark.asyncio
    async def test_cards_batch_at_cap_passes(self, fake_token, monkeypatch):
        monkeypatch.setattr(server, "MCP_MAX_CARDS_PER_CALL", 3)
        rows = [
            {"row_index": i, "type": "Application", "name": f"A{i}"} for i in range(3)
        ]
        patcher, mock = _patched_post({"results": [], "created": 0, "failed": 0})
        with patcher:
            await server.create_cards_bulk(cards=rows, dry_run=False)
        mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_relations_batch_over_cap_rejected(self, fake_token, monkeypatch):
        monkeypatch.setattr(server, "MCP_MAX_RELATIONS_PER_CALL", 1)
        ops = [
            {
                "row_index": i,
                "type": "uses",
                "source": {"id": f"s{i}"},
                "target": {"id": f"t{i}"},
            }
            for i in range(2)
        ]
        post_mock = AsyncMock()
        with patch.object(server.TurboEAClient, "post", post_mock):
            out = await server.upsert_relations_bulk(operations=ops)
        post_mock.assert_not_called()
        data = _parse(out)
        assert data["error"] == "batch_too_large"

    @pytest.mark.asyncio
    async def test_relations_delete_action_rejected(self, fake_token, monkeypatch):
        # MCP_ALLOW_RELATION_DELETE defaults to False — verify rejection.
        monkeypatch.setattr(server, "MCP_ALLOW_RELATION_DELETE", False)
        ops = [
            {
                "row_index": 0,
                "type": "uses",
                "source": {"id": "s"},
                "target": {"id": "t"},
            },
            {
                "row_index": 1,
                "action": "delete",
                "type": "uses",
                "source": {"id": "s"},
                "target": {"id": "t"},
            },
        ]
        post_mock = AsyncMock()
        with patch.object(server.TurboEAClient, "post", post_mock):
            out = await server.upsert_relations_bulk(operations=ops)
        post_mock.assert_not_called()
        data = _parse(out)
        assert data["error"] == "delete_action_disabled"
        assert data["rejected_rows"] == [1]

    @pytest.mark.asyncio
    async def test_relations_delete_allowed_when_flag_on(
        self, fake_token, monkeypatch
    ):
        monkeypatch.setattr(server, "MCP_ALLOW_RELATION_DELETE", True)
        ops = [
            {
                "row_index": 0,
                "action": "delete",
                "type": "uses",
                "source": {"id": "s"},
                "target": {"id": "t"},
            }
        ]
        patcher, mock = _patched_post(
            {"results": [], "upserted": 0, "deleted": 1, "failed": 0}
        )
        with patcher:
            await server.upsert_relations_bulk(operations=ops, dry_run=False)
        mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_writes_disabled_blocks_all_write_tools(
        self, fake_token, monkeypatch
    ):
        monkeypatch.setattr(server, "MCP_WRITES_ENABLED", False)
        post_mock = AsyncMock()
        put_mock = AsyncMock()
        get_mock = AsyncMock()
        with (
            patch.object(server.TurboEAClient, "post", post_mock),
            patch.object(server.TurboEAClient, "put", put_mock),
            patch.object(server.TurboEAClient, "get", get_mock),
        ):
            for out in [
                await server.create_cards_bulk(cards=[]),
                await server.upsert_relations_bulk(operations=[]),
                await server.create_diagram(name="X", drawio_xml="<x/>"),
                await server.import_bpmn(
                    business_process_name="X", bpmn_xml="<bpmn:definitions/>"
                ),
            ]:
                assert _parse(out)["error"] == "writes_disabled"
        post_mock.assert_not_called()
        put_mock.assert_not_called()
        get_mock.assert_not_called()

    def test_origin_header_added_on_post(self):
        from turbo_ea_mcp.api_client import TurboEAClient

        client = TurboEAClient("test-token")
        headers = client._headers()
        assert headers["X-Turbo-EA-Origin"] == "mcp"
        assert headers["Authorization"] == "Bearer test-token"


class TestUnauthenticatedWrites:
    def test_create_cards_bulk_requires_auth(self, monkeypatch):
        monkeypatch.setattr(server, "_stdio_token", None)
        out = asyncio.run(
            server.create_cards_bulk(
                cards=[{"row_index": 0, "type": "Application", "name": "X"}]
            )
        )
        assert "Not authenticated" in out

    def test_resolve_card_refs_requires_auth(self, monkeypatch):
        monkeypatch.setattr(server, "_stdio_token", None)
        out = asyncio.run(server.resolve_card_refs(refs=[]))
        assert "Not authenticated" in out

    def test_upsert_relations_bulk_requires_auth(self, monkeypatch):
        monkeypatch.setattr(server, "_stdio_token", None)
        out = asyncio.run(
            server.upsert_relations_bulk(
                operations=[
                    {
                        "row_index": 0,
                        "type": "uses",
                        "source": {"id": "s"},
                        "target": {"id": "t"},
                    }
                ]
            )
        )
        assert "Not authenticated" in out

    def test_create_diagram_requires_auth(self, monkeypatch):
        monkeypatch.setattr(server, "_stdio_token", None)
        out = asyncio.run(server.create_diagram(name="X", drawio_xml="<x/>"))
        assert "Not authenticated" in out

    def test_import_bpmn_requires_auth(self, monkeypatch):
        monkeypatch.setattr(server, "_stdio_token", None)
        out = asyncio.run(
            server.import_bpmn(
                business_process_name="X",
                bpmn_xml="<bpmn:definitions/>",
            )
        )
        assert "Not authenticated" in out
