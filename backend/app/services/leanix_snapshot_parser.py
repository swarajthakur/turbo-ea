"""Shared typed payloads for the LeanIX importer.

This module defines the dataclasses that the xlsx parser
(:mod:`leanix_xlsx_parser`), the staging service
(:mod:`leanix_migration_service`), and the apply pipeline
(:mod:`leanix_migration_apply`) all share. It is intentionally
parser-agnostic — the only producer today is the xlsx parser, but the
shape stays free of openpyxl details so other producers can be added
without rippling through the consumers.

Historical note: this file used to host a streaming gzipped/JSON
snapshot parser as well. SAP LeanIX only documents one official export
route (**Administration → Export → Full Snapshot**, which produces an
XLSX file), so the JSON paths were removed and xlsx became the single
supported format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Typed payloads
# ---------------------------------------------------------------------------


@dataclass
class FactSheet:
    leanix_id: str
    type: str  # LeanIX FS type, e.g. "Application"
    name: str
    display_name: str | None = None
    category: str | None = None  # LeanIX "subtype" equivalent
    description: str | None = None
    lifecycle: dict[str, str] = field(default_factory=dict)  # phase -> ISO date
    tags: list[str] = field(default_factory=list)  # tag ids
    parent_id: str | None = None  # resolved via relToParent / relToChild
    custom_fields: dict[str, Any] = field(default_factory=dict)
    quality_seal: str | None = None
    completion: float | None = None
    status: str | None = None  # LeanIX FS-level status (ACTIVE / ARCHIVED)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Relation:
    leanix_id: str
    type: str  # e.g. "relApplicationToITComponent"
    source_id: str
    target_id: str
    attributes: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Subscription:
    leanix_id: str
    fact_sheet_id: str
    user_email: str | None
    user_display_name: str | None
    role_name: str | None  # e.g. "Application Owner"
    role_type: str | None  # RESPONSIBLE | ACCOUNTABLE | OBSERVER
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Tag:
    leanix_id: str
    name: str
    group_name: str | None
    group_mode: str | None  # SINGLE | MULTIPLE
    color: str | None = None


@dataclass
class Document:
    leanix_id: str
    fact_sheet_id: str
    name: str
    url: str | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Comment:
    leanix_id: str
    fact_sheet_id: str
    author_email: str | None
    body: str
    created_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class UserRef:
    leanix_id: str
    email: str
    display_name: str | None = None


@dataclass
class MetamodelField:
    type_name: str  # LeanIX FS type the field is attached to
    key: str
    label: str
    data_type: str  # LeanIX STRING / SINGLE_SELECT / FACT_SHEET_REFERENCE / ...
    options: list[dict[str, Any]] = field(default_factory=list)
    translations: dict[str, str] = field(default_factory=dict)
    is_custom: bool = True  # False if it's a known LeanIX default field


@dataclass
class MetamodelType:
    name: str
    is_custom: bool
    fields: list[MetamodelField] = field(default_factory=list)
    subtypes: list[str] = field(default_factory=list)


@dataclass
class MetamodelRelationType:
    name: str
    source_type: str
    target_type: str
    label: str | None = None
    attributes_schema: list[dict[str, Any]] = field(default_factory=list)
    is_custom: bool = True


@dataclass
class LeanixSnapshot:
    version: str
    fact_sheets: list[FactSheet]
    relations: list[Relation]
    subscriptions: list[Subscription]
    tags: list[Tag]
    documents: list[Document]
    comments: list[Comment]
    users: list[UserRef]
    metamodel_types: list[MetamodelType]
    metamodel_relation_types: list[MetamodelRelationType]
    parse_errors: list[str] = field(default_factory=list)
