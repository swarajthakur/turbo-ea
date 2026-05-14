"""Unit + DB tests for the demo Security & Compliance seeder.

Pure-Python tests check that the curated CVE / Compliance data structures
reference valid regulations, valid lifecycle states, and only target cards
that actually exist in the NexaTech base demo set — guarding against the
most common bug (renaming a card in ``seed_demo.py`` without updating
``seed_demo_security.py``).

A small DB-backed test rounds out the suite: it inserts the demo cards the
seeder targets, runs the seeder twice, asserts the row counts and the
idempotency skip.
"""

from __future__ import annotations

import pytest

from app.services.seed_demo import APPLICATIONS, IT_COMPONENTS
from app.services.seed_demo_security import (
    COMPLIANCE_FINDINGS,
    CVE_FINDINGS,
    seed_security_demo_data,
)
from app.services.turbolens_security import COMPLIANCE_LIFECYCLE_STATES
from tests.conftest import create_card

# Hand-mirroring the Literal in ``schemas/turbolens.py`` (deliberately
# duplicated so this test fails when someone forgets to update the seed
# after extending the lifecycle).
_VALID_CVE_STATUSES = frozenset({"open", "acknowledged", "in_progress", "mitigated", "accepted"})

# Built-in regulation keys registered by ``seed_metamodel`` (see seed.py).
_BUILTIN_REGULATIONS = frozenset({"eu_ai_act", "gdpr", "nis2", "dora", "soc2", "iso27001"})


# ---------------------------------------------------------------------------
# Card-name compatibility — no DB required
# ---------------------------------------------------------------------------


def _demo_card_names() -> set[str]:
    """Names of every Application + IT Component in ``seed_demo.py``."""
    return {a["name"] for a in APPLICATIONS} | {c["name"] for c in IT_COMPONENTS}


def test_every_cve_card_name_exists_in_demo_set() -> None:
    demo = _demo_card_names()
    missing = {f["card_name"] for f in CVE_FINDINGS} - demo
    assert not missing, (
        f"CVE_FINDINGS references card names that don't exist in seed_demo.py "
        f"Applications/ITComponents: {sorted(missing)}"
    )


def test_every_compliance_card_name_exists_in_demo_set() -> None:
    demo = _demo_card_names()
    referenced = {f["card_name"] for f in COMPLIANCE_FINDINGS if f.get("card_name")}
    missing = referenced - demo
    assert not missing, (
        f"COMPLIANCE_FINDINGS references card names that don't exist in seed_demo.py "
        f"Applications/ITComponents: {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# Regulation + lifecycle validity — no DB required
# ---------------------------------------------------------------------------


def test_every_compliance_regulation_is_built_in() -> None:
    used = {f["regulation"] for f in COMPLIANCE_FINDINGS}
    unknown = used - _BUILTIN_REGULATIONS
    assert not unknown, (
        f"COMPLIANCE_FINDINGS uses regulation keys not registered by "
        f"seed_metamodel(): {sorted(unknown)}"
    )


def test_every_cve_status_is_valid() -> None:
    for f in CVE_FINDINGS:
        assert f.get("status", "open") in _VALID_CVE_STATUSES, (
            f"CVE {f['cve_id']} has invalid status {f.get('status')!r}"
        )


def test_every_compliance_decision_is_valid() -> None:
    for f in COMPLIANCE_FINDINGS:
        decision = f.get("decision", "new")
        assert decision in COMPLIANCE_LIFECYCLE_STATES, (
            f"Compliance finding for {f.get('regulation')}/"
            f"{f.get('regulation_article')} has invalid decision "
            f"{decision!r}; must be one of {sorted(COMPLIANCE_LIFECYCLE_STATES)}"
        )


def test_required_fields_present_on_every_cve() -> None:
    required = {"card_name", "card_type", "cve_id", "vendor", "product", "severity"}
    for f in CVE_FINDINGS:
        missing = required - set(f.keys())
        assert not missing, f"CVE {f.get('cve_id')} missing fields: {sorted(missing)}"


def test_required_fields_present_on_every_compliance_finding() -> None:
    required = {"regulation", "regulation_article", "requirement", "gap_description"}
    for f in COMPLIANCE_FINDINGS:
        missing = required - set(f.keys())
        assert not missing, (
            f"Compliance finding {f.get('regulation')}/{f.get('regulation_article')} "
            f"missing fields: {sorted(missing)}"
        )


# ---------------------------------------------------------------------------
# DB-backed integration: seed + idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_inserts_findings_and_is_idempotent(db) -> None:
    """Insert the cards the seeder targets, then run the seeder twice."""
    from sqlalchemy import select

    from app.models.turbolens import (
        TurboLensAnalysisRun,
        TurboLensComplianceFinding,
        TurboLensCveFinding,
    )

    # Seed exactly the cards referenced in the security demo so the seeder
    # has somewhere to land its rows.
    referenced_cves = {f["card_name"] for f in CVE_FINDINGS}
    referenced_comp = {f["card_name"] for f in COMPLIANCE_FINDINGS if f.get("card_name")}
    name_to_type: dict[str, str] = {f["card_name"]: f["card_type"] for f in CVE_FINDINGS}
    for f in COMPLIANCE_FINDINGS:
        if f.get("card_name") and f["card_name"] not in name_to_type:
            # Compliance entries don't carry card_type; default to ITComponent
            # (all of ours fall back to that or to specific names we already
            # know are Applications).
            apps = {a["name"] for a in APPLICATIONS}
            name_to_type[f["card_name"]] = (
                "Application" if f["card_name"] in apps else "ITComponent"
            )

    for name in referenced_cves | referenced_comp:
        await create_card(db, card_type=name_to_type[name], name=name)
    await db.commit()

    # ---- first run: should insert everything ------------------------
    result = await seed_security_demo_data(db)
    assert result.get("skipped") is not True
    assert result["cve_findings"] == len(CVE_FINDINGS)
    assert result["compliance_findings"] == len(COMPLIANCE_FINDINGS)
    assert result["analysis_runs"] == 2

    cve_rows = (await db.execute(select(TurboLensCveFinding))).scalars().all()
    comp_rows = (await db.execute(select(TurboLensComplianceFinding))).scalars().all()
    run_rows = (await db.execute(select(TurboLensAnalysisRun))).scalars().all()
    assert len(cve_rows) == len(CVE_FINDINGS)
    assert len(comp_rows) == len(COMPLIANCE_FINDINGS)
    assert len(run_rows) == 2
    # Demo marker is set on the synthetic runs so we can recognise them later.
    for r in run_rows:
        assert isinstance(r.results, dict) and r.results.get("demo") is True

    # ---- second run: should be a no-op -------------------------------
    result2 = await seed_security_demo_data(db)
    assert result2 == {"skipped": True, "reason": "TurboLens findings already exist"}

    cve_rows2 = (await db.execute(select(TurboLensCveFinding))).scalars().all()
    comp_rows2 = (await db.execute(select(TurboLensComplianceFinding))).scalars().all()
    assert len(cve_rows2) == len(CVE_FINDINGS)
    assert len(comp_rows2) == len(COMPLIANCE_FINDINGS)


@pytest.mark.asyncio
async def test_seed_skips_findings_for_missing_cards(db) -> None:
    """If a referenced card isn't in the DB, that finding is silently skipped."""
    from sqlalchemy import select

    from app.models.turbolens import TurboLensComplianceFinding, TurboLensCveFinding

    # Insert only ONE of the cards the seeder targets — Nginx for CVE.
    await create_card(db, card_type="ITComponent", name="Nginx")
    await db.commit()

    result = await seed_security_demo_data(db)
    assert not result.get("skipped"), result

    # Only the Nginx CVE row should have landed.
    cve_rows = (await db.execute(select(TurboLensCveFinding))).scalars().all()
    assert len(cve_rows) == 1
    assert cve_rows[0].cve_id == "CVE-2025-91002"

    # Landscape-scoped compliance findings (card_name=None) should still land;
    # card-scoped ones whose target is missing should be skipped.
    comp_rows = (await db.execute(select(TurboLensComplianceFinding))).scalars().all()
    landscape_count = sum(1 for f in COMPLIANCE_FINDINGS if f.get("card_name") is None)
    assert len(comp_rows) == landscape_count
