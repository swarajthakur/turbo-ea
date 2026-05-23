"""Integration tests for the /bpm endpoints (templates, assessments)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.process_diagram import ProcessDiagram
from app.models.process_element import ProcessElement
from tests.conftest import (
    auth_headers,
    create_card,
    create_card_type,
    create_role,
    create_user,
)


@pytest.fixture
async def bpm_env(db):
    """Prerequisite data for BPM tests."""
    await create_role(db, key="admin", label="Admin", permissions={"*": True})
    await create_role(
        db,
        key="viewer",
        label="Viewer",
        permissions={
            "inventory.view": True,
            "bpm.view": True,
        },
    )
    await create_card_type(
        db,
        key="BusinessProcess",
        label="Business Process",
    )
    admin = await create_user(db, email="admin@test.com", role="admin")
    viewer = await create_user(db, email="viewer@test.com", role="viewer")
    process = await create_card(
        db,
        card_type="BusinessProcess",
        name="Order Fulfillment",
        user_id=admin.id,
    )
    return {
        "admin": admin,
        "viewer": viewer,
        "process": process,
    }


class TestBpmTemplates:
    async def test_list_templates(self, client, db, bpm_env):
        admin = bpm_env["admin"]
        resp = await client.get(
            "/api/v1/bpm/templates",
            headers=auth_headers(admin),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        keys = [t["key"] for t in data]
        assert "blank" in keys

    async def test_list_templates_has_fields(self, client, db, bpm_env):
        admin = bpm_env["admin"]
        resp = await client.get(
            "/api/v1/bpm/templates",
            headers=auth_headers(admin),
        )
        first = resp.json()[0]
        assert "key" in first
        assert "name" in first
        assert "description" in first
        assert "category" in first

    async def test_templates_require_auth(self, client, db, bpm_env):
        resp = await client.get("/api/v1/bpm/templates")
        assert resp.status_code == 401

    async def test_get_template_returns_full_bpmn_xml(self, client, db, bpm_env):
        # Regression for #581: non-blank templates must ship the full BPMN
        # XML (tasks + gateways), not silently fall back to the blank stub
        # when the bpmn_templates/ directory is missing from the image.
        admin = bpm_env["admin"]
        resp = await client.get(
            "/api/v1/bpm/templates/simple-approval",
            headers=auth_headers(admin),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["key"] == "simple-approval"
        xml = body["bpmn_xml"]
        assert "<bpmn:userTask" in xml or "<bpmn:task" in xml
        assert "<bpmn:exclusiveGateway" in xml or "<bpmn:parallelGateway" in xml


class TestProcessAssessments:
    async def test_create_assessment(self, client, db, bpm_env):
        admin = bpm_env["admin"]
        process = bpm_env["process"]
        resp = await client.post(
            f"/api/v1/bpm/processes/{process.id}/assessments",
            json={
                "assessment_date": "2026-01-15",
                "overall_score": 4,
                "efficiency": 3,
                "effectiveness": 4,
                "compliance": 5,
                "automation": 2,
                "notes": "Good process maturity",
            },
            headers=auth_headers(admin),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["overall_score"] == 4
        assert "id" in data

    async def test_list_assessments(self, client, db, bpm_env):
        admin = bpm_env["admin"]
        process = bpm_env["process"]
        # Create an assessment first
        await client.post(
            f"/api/v1/bpm/processes/{process.id}/assessments",
            json={
                "assessment_date": "2026-02-01",
                "overall_score": 3,
                "efficiency": 3,
                "effectiveness": 3,
                "compliance": 3,
                "automation": 3,
            },
            headers=auth_headers(admin),
        )

        resp = await client.get(
            f"/api/v1/bpm/processes/{process.id}/assessments",
            headers=auth_headers(admin),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        first = data[0]
        assert "efficiency" in first
        assert "effectiveness" in first
        assert "compliance" in first
        assert "automation" in first

    async def test_update_assessment(self, client, db, bpm_env):
        admin = bpm_env["admin"]
        process = bpm_env["process"]
        create_resp = await client.post(
            f"/api/v1/bpm/processes/{process.id}/assessments",
            json={
                "assessment_date": "2026-02-10",
                "overall_score": 2,
                "efficiency": 2,
                "effectiveness": 2,
                "compliance": 2,
                "automation": 2,
            },
            headers=auth_headers(admin),
        )
        a_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/v1/bpm/processes/{process.id}/assessments/{a_id}",
            json={"overall_score": 5, "notes": "Improved"},
            headers=auth_headers(admin),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "updated"

    async def test_delete_assessment(self, client, db, bpm_env):
        admin = bpm_env["admin"]
        process = bpm_env["process"]
        create_resp = await client.post(
            f"/api/v1/bpm/processes/{process.id}/assessments",
            json={
                "assessment_date": "2026-02-15",
                "overall_score": 1,
                "efficiency": 1,
                "effectiveness": 1,
                "compliance": 1,
                "automation": 1,
            },
            headers=auth_headers(admin),
        )
        a_id = create_resp.json()["id"]

        resp = await client.delete(
            f"/api/v1/bpm/processes/{process.id}/assessments/{a_id}",
            headers=auth_headers(admin),
        )
        assert resp.status_code == 204

    async def test_assessment_nonexistent_process(self, client, db, bpm_env):
        admin = bpm_env["admin"]
        fake_id = uuid.uuid4()
        resp = await client.get(
            f"/api/v1/bpm/processes/{fake_id}/assessments",
            headers=auth_headers(admin),
        )
        assert resp.status_code == 404

    async def test_delete_nonexistent_assessment(self, client, db, bpm_env):
        admin = bpm_env["admin"]
        process = bpm_env["process"]
        fake_id = uuid.uuid4()
        resp = await client.delete(
            f"/api/v1/bpm/processes/{process.id}/assessments/{fake_id}",
            headers=auth_headers(admin),
        )
        assert resp.status_code == 404


_MINIMAL_BPMN = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  id="Defs" targetNamespace="http://example.com/bpmn">
  <bpmn:process id="P1" isExecutable="true">
    <bpmn:startEvent id="Start1" name="Start" />
    <bpmn:task id="T1" name="Pick item" />
    <bpmn:endEvent id="End1" name="Done" />
  </bpmn:process>
</bpmn:definitions>
"""


class TestSaveDiagramDryRun:
    """Dry-run path used by the MCP `import_bpmn` tool."""

    async def test_dry_run_parses_but_does_not_persist(self, client, db, bpm_env):
        admin = bpm_env["admin"]
        process = bpm_env["process"]
        resp = await client.put(
            f"/api/v1/bpm/processes/{process.id}/diagram",
            json={"bpmn_xml": _MINIMAL_BPMN, "dry_run": True},
            headers=auth_headers(admin),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["dry_run"] is True
        # The parser ran and extracted elements.
        assert body["element_count"] >= 1
        # …but nothing persisted.
        diagrams = (
            (
                await db.execute(
                    select(ProcessDiagram).where(ProcessDiagram.process_id == process.id)
                )
            )
            .scalars()
            .all()
        )
        elements = (
            (
                await db.execute(
                    select(ProcessElement).where(ProcessElement.process_id == process.id)
                )
            )
            .scalars()
            .all()
        )
        assert diagrams == []
        assert elements == []

    async def test_business_process_card_accepts_description_via_bulk(self, client, db, bpm_env):
        """Regression for the empty-card report: a BusinessProcess card
        created via /cards/bulk-create with a `description` field must
        land with that description set on the card row, exactly like any
        other card type. The BPMN flow does not change card-level
        description semantics; description is a top-level column on
        `cards`, not a per-type attribute."""
        from sqlalchemy import select

        from app.models.card import Card

        admin = bpm_env["admin"]
        payload = {
            "cards": [
                {
                    "row_index": 0,
                    "type": "BusinessProcess",
                    "name": "Procure to Pay",
                    "description": "End-to-end procurement workflow.",
                    "attributes": {"processType": "Core"},
                }
            ]
        }
        resp = await client.post(
            "/api/v1/cards/bulk-create", json=payload, headers=auth_headers(admin)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["created"] == 1
        cid = body["results"][0]["id"]
        card = (await db.execute(select(Card).where(Card.id == uuid.UUID(cid)))).scalar_one()
        assert card.description == "End-to-end procurement workflow."
        assert card.attributes.get("processType") == "Core"

    async def test_commit_persists_after_dry_run(self, client, db, bpm_env):
        admin = bpm_env["admin"]
        process = bpm_env["process"]
        # Dry-run first.
        await client.put(
            f"/api/v1/bpm/processes/{process.id}/diagram",
            json={"bpmn_xml": _MINIMAL_BPMN, "dry_run": True},
            headers=auth_headers(admin),
        )
        # Then commit.
        resp = await client.put(
            f"/api/v1/bpm/processes/{process.id}/diagram",
            json={"bpmn_xml": _MINIMAL_BPMN, "dry_run": False},
            headers=auth_headers(admin),
        )
        assert resp.status_code == 200
        assert resp.json()["dry_run"] is False
        rows = (
            (
                await db.execute(
                    select(ProcessDiagram).where(ProcessDiagram.process_id == process.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
