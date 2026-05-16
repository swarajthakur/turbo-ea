"""Bulk-operation endpoints for compliance findings.

PATCH /security/compliance-findings/bulk — bulk decision update.
DELETE /security/compliance-findings/bulk — bulk delete.

Both endpoints share the gate (``compliance.manage``, admin
role by default) and the per-row partial-success contract: invalid /
not-found / risk-tracked rows go into ``skipped`` instead of failing
the whole batch.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.core.permissions import VIEWER_PERMISSIONS
from app.models.risk import Risk
from app.models.turbolens import (
    TurboLensAnalysisRun,
    TurboLensComplianceFinding,
)
from tests.conftest import auth_headers, create_role, create_user


@pytest.fixture
async def env(db):
    await create_role(db, key="admin", label="Admin", permissions={"*": True})
    await create_role(db, key="viewer", label="Viewer", permissions=VIEWER_PERMISSIONS)
    admin = await create_user(db, email="admin@test.com", role="admin")
    viewer = await create_user(db, email="viewer@test.com", role="viewer")

    run = TurboLensAnalysisRun(
        id=uuid.uuid4(),
        analysis_type="compliance",
        status="completed",
        started_at=datetime.now(timezone.utc),
        created_by=admin.id,
    )
    db.add(run)
    await db.flush()
    return {"admin": admin, "viewer": viewer, "run_id": run.id}


async def _make_finding(
    db,
    run_id: uuid.UUID,
    *,
    decision: str = "new",
    risk_id: uuid.UUID | None = None,
    article: str = "Art. 6",
) -> TurboLensComplianceFinding:
    row = TurboLensComplianceFinding(
        id=uuid.uuid4(),
        run_id=run_id,
        regulation="gdpr",
        regulation_article=article,
        card_id=None,
        scope_type="landscape",
        category="test",
        requirement="Requirement text.",
        status="non_compliant",
        severity="high",
        gap_description="Gap.",
        evidence=None,
        remediation=None,
        ai_detected=False,
        finding_key=f"k-{uuid.uuid4().hex}",
        decision=decision,
        risk_id=risk_id,
    )
    db.add(row)
    await db.flush()
    return row


async def _make_risk(db) -> uuid.UUID:
    risk = Risk(
        id=uuid.uuid4(),
        reference=f"R-{uuid.uuid4().hex[:6]}",
        title="Test risk",
        category="compliance",
        source_type="manual",
        initial_probability="medium",
        initial_impact="medium",
        initial_level="medium",
        status="identified",
    )
    db.add(risk)
    await db.flush()
    return risk.id


class TestBulkDelete:
    async def test_admin_deletes_multiple(self, client, db, env):
        a = await _make_finding(db, env["run_id"])
        b = await _make_finding(db, env["run_id"])
        await db.commit()

        r = await client.request(
            "DELETE",
            "/api/v1/compliance/compliance-findings/bulk",
            json={"ids": [str(a.id), str(b.id)]},
            headers=auth_headers(env["admin"]),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["updated"] == 2
        assert body["skipped"] == []

        # Both rows are actually gone.
        for row_id in (a.id, b.id):
            assert await db.get(TurboLensComplianceFinding, row_id) is None

    async def test_missing_id_reported_in_skipped(self, client, db, env):
        a = await _make_finding(db, env["run_id"])
        await db.commit()
        ghost = uuid.uuid4()

        r = await client.request(
            "DELETE",
            "/api/v1/compliance/compliance-findings/bulk",
            json={"ids": [str(a.id), str(ghost)]},
            headers=auth_headers(env["admin"]),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["updated"] == 1
        assert body["skipped"] == [{"id": str(ghost), "reason": "not_found"}]

    async def test_viewer_forbidden(self, client, db, env):
        a = await _make_finding(db, env["run_id"])
        await db.commit()

        r = await client.request(
            "DELETE",
            "/api/v1/compliance/compliance-findings/bulk",
            json={"ids": [str(a.id)]},
            headers=auth_headers(env["viewer"]),
        )
        assert r.status_code == 403
        # Row untouched.
        assert await db.get(TurboLensComplianceFinding, a.id) is not None

    async def test_empty_ids_is_a_noop(self, client, db, env):
        r = await client.request(
            "DELETE",
            "/api/v1/compliance/compliance-findings/bulk",
            json={"ids": []},
            headers=auth_headers(env["admin"]),
        )
        assert r.status_code == 200
        assert r.json() == {"updated": 0, "skipped": []}


class TestBulkDecision:
    async def test_admin_transitions_multiple(self, client, db, env):
        a = await _make_finding(db, env["run_id"], decision="new")
        b = await _make_finding(db, env["run_id"], decision="new")
        await db.commit()

        r = await client.patch(
            "/api/v1/compliance/compliance-findings/bulk",
            json={
                "ids": [str(a.id), str(b.id)],
                "decision": "in_review",
                "review_note": "batch review",
            },
            headers=auth_headers(env["admin"]),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["updated"] == 2
        assert body["skipped"] == []

        await db.refresh(a)
        await db.refresh(b)
        assert a.decision == b.decision == "in_review"
        assert a.review_note == "batch review"
        assert a.reviewed_by == env["admin"].id

    async def test_skips_illegal_transitions_per_row(self, client, db, env):
        # "verified" cannot go straight to "accepted" — only "in_review".
        legal = await _make_finding(db, env["run_id"], decision="new")
        illegal = await _make_finding(db, env["run_id"], decision="verified")
        await db.commit()

        r = await client.patch(
            "/api/v1/compliance/compliance-findings/bulk",
            json={
                "ids": [str(legal.id), str(illegal.id)],
                "decision": "in_review",
            },
            headers=auth_headers(env["admin"]),
        )
        assert r.status_code == 200
        body = r.json()
        # "new" → "in_review" allowed; "verified" → "in_review" allowed too.
        assert body["updated"] == 2

        # Now try a transition only one row can take: "new" → "mitigated"
        # is illegal (must go via in_review first); "in_review" → "mitigated" is fine.
        await db.refresh(legal)  # now in_review
        await db.refresh(illegal)  # now in_review
        # Reset one to "new" to engineer a skip.
        legal.decision = "new"
        await db.commit()

        r = await client.patch(
            "/api/v1/compliance/compliance-findings/bulk",
            json={
                "ids": [str(legal.id), str(illegal.id)],
                "decision": "mitigated",
            },
            headers=auth_headers(env["admin"]),
        )
        body = r.json()
        assert body["updated"] == 1
        assert body["skipped"] == [{"id": str(legal.id), "reason": "illegal_transition"}]

    async def test_skips_risk_tracked_rows(self, client, db, env):
        risk_id = await _make_risk(db)
        risk_tracked = await _make_finding(
            db, env["run_id"], decision="risk_tracked", risk_id=risk_id
        )
        plain = await _make_finding(db, env["run_id"], decision="new")
        await db.commit()

        r = await client.patch(
            "/api/v1/compliance/compliance-findings/bulk",
            json={
                "ids": [str(risk_tracked.id), str(plain.id)],
                "decision": "in_review",
            },
            headers=auth_headers(env["admin"]),
        )
        body = r.json()
        assert body["updated"] == 1
        assert body["skipped"] == [{"id": str(risk_tracked.id), "reason": "risk_tracked"}]

    async def test_accepted_requires_review_note(self, client, db, env):
        a = await _make_finding(db, env["run_id"], decision="new")
        await db.commit()

        r = await client.patch(
            "/api/v1/compliance/compliance-findings/bulk",
            json={"ids": [str(a.id)], "decision": "accepted"},
            headers=auth_headers(env["admin"]),
        )
        assert r.status_code == 400
        # Row untouched.
        await db.refresh(a)
        assert a.decision == "new"

    async def test_viewer_forbidden(self, client, db, env):
        a = await _make_finding(db, env["run_id"], decision="new")
        await db.commit()

        r = await client.patch(
            "/api/v1/compliance/compliance-findings/bulk",
            json={"ids": [str(a.id)], "decision": "in_review"},
            headers=auth_headers(env["viewer"]),
        )
        assert r.status_code == 403
        await db.refresh(a)
        assert a.decision == "new"
