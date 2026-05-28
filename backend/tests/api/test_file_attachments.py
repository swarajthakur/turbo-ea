"""Integration tests for the file-attachment endpoints.

These tests require a PostgreSQL test database and an HTTP test client.
"""

from __future__ import annotations

import pytest

from app.core.permissions import VIEWER_PERMISSIONS
from tests.conftest import (
    auth_headers,
    create_card,
    create_card_type,
    create_role,
    create_user,
)


@pytest.fixture
async def file_env(db):
    """Prerequisite data shared by all file-attachment tests."""
    await create_role(db, key="admin", label="Admin", permissions={"*": True})
    await create_role(db, key="viewer", label="Viewer", permissions=VIEWER_PERMISSIONS)
    admin = await create_user(db, email="admin@test.com", role="admin")
    viewer = await create_user(db, email="viewer@test.com", role="viewer")
    await create_card_type(db, key="Application", label="Application")
    card = await create_card(db, card_type="Application", name="Test Card", user_id=admin.id)
    return {"admin": admin, "viewer": viewer, "card": card}


# -------------------------------------------------------------------
# POST /cards/{card_id}/file-attachments  (upload)
# -------------------------------------------------------------------


class TestUploadFile:
    async def test_admin_can_upload_pdf(self, client, db, file_env):
        admin = file_env["admin"]
        card = file_env["card"]

        resp = await client.post(
            f"/api/v1/cards/{card.id}/file-attachments",
            files={"file": ("test.pdf", b"fake-pdf-content", "application/pdf")},
            headers=auth_headers(admin),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "test.pdf"
        assert data["mime_type"] == "application/pdf"
        assert data["size"] == len(b"fake-pdf-content")
        assert "id" in data

    async def test_rejects_disallowed_mime_type(self, client, db, file_env):
        admin = file_env["admin"]
        card = file_env["card"]

        resp = await client.post(
            f"/api/v1/cards/{card.id}/file-attachments",
            files={"file": ("malware.exe", b"bad-content", "application/x-msdownload")},
            headers=auth_headers(admin),
        )
        assert resp.status_code == 400

    async def test_viewer_cannot_upload(self, client, db, file_env):
        viewer = file_env["viewer"]
        card = file_env["card"]

        resp = await client.post(
            f"/api/v1/cards/{card.id}/file-attachments",
            files={"file": ("test.pdf", b"fake-pdf-content", "application/pdf")},
            headers=auth_headers(viewer),
        )
        assert resp.status_code == 403

    async def test_upload_blocked_when_disabled_by_admin(self, client, db, file_env):
        """When the admin toggle is off, POST /file-attachments returns 403."""
        admin = file_env["admin"]
        card = file_env["card"]

        # First upload succeeds (feature defaults to enabled).
        ok_resp = await client.post(
            f"/api/v1/cards/{card.id}/file-attachments",
            files={"file": ("before.pdf", b"before-bytes", "application/pdf")},
            headers=auth_headers(admin),
        )
        assert ok_resp.status_code == 201
        existing_id = ok_resp.json()["id"]

        # Admin disables the feature.
        toggle_resp = await client.patch(
            "/api/v1/settings/file-uploads-enabled",
            json={"enabled": False},
            headers=auth_headers(admin),
        )
        assert toggle_resp.status_code == 200

        # Subsequent uploads are rejected.
        blocked_resp = await client.post(
            f"/api/v1/cards/{card.id}/file-attachments",
            files={"file": ("after.pdf", b"after-bytes", "application/pdf")},
            headers=auth_headers(admin),
        )
        assert blocked_resp.status_code == 403
        assert "disabled" in blocked_resp.json()["detail"].lower()

        # Listing existing attachments still works (admins must be able to
        # audit and clean up after disabling).
        list_resp = await client.get(
            f"/api/v1/cards/{card.id}/file-attachments",
            headers=auth_headers(admin),
        )
        assert list_resp.status_code == 200
        assert any(f["id"] == existing_id for f in list_resp.json())

        # Downloading existing attachments still works.
        dl_resp = await client.get(
            f"/api/v1/file-attachments/{existing_id}/download",
            headers=auth_headers(admin),
        )
        assert dl_resp.status_code == 200

        # Deleting existing attachments still works.
        del_resp = await client.delete(
            f"/api/v1/file-attachments/{existing_id}",
            headers=auth_headers(admin),
        )
        assert del_resp.status_code == 204


# -------------------------------------------------------------------
# GET /cards/{card_id}/file-attachments  (list)
# -------------------------------------------------------------------


class TestListFiles:
    async def test_list_returns_uploaded_files(self, client, db, file_env):
        admin = file_env["admin"]
        card = file_env["card"]

        # Upload two files
        await client.post(
            f"/api/v1/cards/{card.id}/file-attachments",
            files={"file": ("a.pdf", b"content-a", "application/pdf")},
            headers=auth_headers(admin),
        )
        await client.post(
            f"/api/v1/cards/{card.id}/file-attachments",
            files={"file": ("b.txt", b"content-b", "text/plain")},
            headers=auth_headers(admin),
        )

        resp = await client.get(
            f"/api/v1/cards/{card.id}/file-attachments",
            headers=auth_headers(admin),
        )
        assert resp.status_code == 200
        names = [f["name"] for f in resp.json()]
        assert "a.pdf" in names
        assert "b.txt" in names

    async def test_viewer_can_list(self, client, db, file_env):
        viewer = file_env["viewer"]
        card = file_env["card"]

        resp = await client.get(
            f"/api/v1/cards/{card.id}/file-attachments",
            headers=auth_headers(viewer),
        )
        assert resp.status_code == 200


# -------------------------------------------------------------------
# GET /file-attachments/{id}/download
# -------------------------------------------------------------------


class TestDownloadFile:
    async def test_admin_can_download(self, client, db, file_env):
        admin = file_env["admin"]
        card = file_env["card"]

        upload_resp = await client.post(
            f"/api/v1/cards/{card.id}/file-attachments",
            files={"file": ("doc.pdf", b"pdf-bytes-here", "application/pdf")},
            headers=auth_headers(admin),
        )
        attachment_id = upload_resp.json()["id"]

        resp = await client.get(
            f"/api/v1/file-attachments/{attachment_id}/download",
            headers=auth_headers(admin),
        )
        assert resp.status_code == 200
        assert resp.content == b"pdf-bytes-here"
        assert resp.headers["content-type"] == "application/pdf"
        assert "doc.pdf" in resp.headers.get("content-disposition", "")

    async def test_viewer_can_download(self, client, db, file_env):
        admin = file_env["admin"]
        viewer = file_env["viewer"]
        card = file_env["card"]

        upload_resp = await client.post(
            f"/api/v1/cards/{card.id}/file-attachments",
            files={"file": ("report.txt", b"text-data", "text/plain")},
            headers=auth_headers(admin),
        )
        attachment_id = upload_resp.json()["id"]

        resp = await client.get(
            f"/api/v1/file-attachments/{attachment_id}/download",
            headers=auth_headers(viewer),
        )
        assert resp.status_code == 200

    async def test_download_with_non_latin1_filename(self, client, db, file_env):
        # Regression: filenames containing characters outside Latin-1 (Cyrillic,
        # CJK, emoji) must not crash the response serializer with HTTP 500.
        admin = file_env["admin"]
        card = file_env["card"]
        unicode_name = "отчёт 报告 🚀.pdf"

        upload_resp = await client.post(
            f"/api/v1/cards/{card.id}/file-attachments",
            files={"file": (unicode_name, b"unicode-bytes", "application/pdf")},
            headers=auth_headers(admin),
        )
        assert upload_resp.status_code == 201
        attachment_id = upload_resp.json()["id"]

        resp = await client.get(
            f"/api/v1/file-attachments/{attachment_id}/download",
            headers=auth_headers(admin),
        )
        assert resp.status_code == 200
        assert resp.content == b"unicode-bytes"

        from urllib.parse import quote

        disposition = resp.headers.get("content-disposition", "")
        assert 'filename="' in disposition
        assert f"filename*=UTF-8''{quote(unicode_name, safe='')}" in disposition


# -------------------------------------------------------------------
# DELETE /file-attachments/{id}
# -------------------------------------------------------------------


class TestDeleteFile:
    async def test_admin_can_delete(self, client, db, file_env):
        admin = file_env["admin"]
        card = file_env["card"]

        upload_resp = await client.post(
            f"/api/v1/cards/{card.id}/file-attachments",
            files={"file": ("delete_me.pdf", b"doomed", "application/pdf")},
            headers=auth_headers(admin),
        )
        attachment_id = upload_resp.json()["id"]

        resp = await client.delete(
            f"/api/v1/file-attachments/{attachment_id}",
            headers=auth_headers(admin),
        )
        assert resp.status_code == 204

        # Verify it's gone
        get_resp = await client.get(
            f"/api/v1/file-attachments/{attachment_id}/download",
            headers=auth_headers(admin),
        )
        assert get_resp.status_code == 404

    async def test_viewer_cannot_delete(self, client, db, file_env):
        admin = file_env["admin"]
        viewer = file_env["viewer"]
        card = file_env["card"]

        upload_resp = await client.post(
            f"/api/v1/cards/{card.id}/file-attachments",
            files={"file": ("protected.pdf", b"safe", "application/pdf")},
            headers=auth_headers(admin),
        )
        attachment_id = upload_resp.json()["id"]

        resp = await client.delete(
            f"/api/v1/file-attachments/{attachment_id}",
            headers=auth_headers(viewer),
        )
        assert resp.status_code == 403
