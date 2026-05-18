"""Integration tests for the local-account password reset flow.

Covers ``POST /auth/forgot-password``, ``GET /auth/validate-reset-token``,
and ``POST /auth/reset-password``. Key invariants:

- Anti-enumeration: ``forgot-password`` always returns ``{"ok": True}``,
  even when the email is unknown / belongs to an SSO-only user / SMTP is
  unconfigured.
- A reset token is only generated when ALL conditions hold (existing user,
  local password, active account, SMTP configured).
- Tokens expire after one hour and are single-use (cleared on consumption).
- Resetting the password clears any account lockout (the user proved they
  control the inbox).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.core.security import verify_password
from app.models.user import User
from tests.conftest import create_user


def _patch_smtp_on():
    """Patch the email_service config check so the endpoint thinks SMTP is up."""
    return patch("app.api.v1.auth.email_service._is_configured", return_value=True)


def _patch_smtp_off():
    return patch("app.api.v1.auth.email_service._is_configured", return_value=False)


class TestForgotPassword:
    async def test_unknown_email_returns_ok_no_token(self, client, db):
        """Unknown email → 200 success, no DB row mutated."""
        with _patch_smtp_on():
            resp = await client.post(
                "/api/v1/auth/forgot-password",
                json={"email": "nobody@example.com"},
            )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    async def test_local_user_smtp_on_persists_token(self, client, db):
        user = await create_user(db, email="local@test.com", role="member")
        await db.commit()

        with _patch_smtp_on():
            with patch(
                "app.api.v1.auth.email_service.send_email",
                new=AsyncMock(return_value=True),
            ) as mock_send:
                resp = await client.post(
                    "/api/v1/auth/forgot-password",
                    json={"email": "local@test.com"},
                )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        await db.refresh(user)
        assert user.password_reset_token is not None
        assert len(user.password_reset_token) >= 32
        assert user.password_reset_expires_at is not None
        # Should expire ~1 hour from now (allow ±5 min slack for clock skew).
        delta = user.password_reset_expires_at - datetime.now(timezone.utc)
        assert timedelta(minutes=55) < delta < timedelta(minutes=65)

        mock_send.assert_awaited_once()
        sent_to = mock_send.await_args.args[0]
        assert sent_to == "local@test.com"
        subject = mock_send.await_args.args[1]
        assert "Reset" in subject

    async def test_sso_only_user_no_token_no_email(self, client, db):
        """SSO-only accounts (password_hash is None) get nothing — but still 200."""
        from app.models.user import User as UserModel

        sso_user = UserModel(
            email="sso@test.com",
            display_name="SSO Only",
            password_hash=None,
            role="member",
            is_active=True,
            auth_provider="sso",
            sso_subject_id="ext-1",
        )
        db.add(sso_user)
        await db.flush()
        await db.commit()

        with _patch_smtp_on():
            with patch(
                "app.api.v1.auth.email_service.send_email",
                new=AsyncMock(return_value=True),
            ) as mock_send:
                resp = await client.post(
                    "/api/v1/auth/forgot-password",
                    json={"email": "sso@test.com"},
                )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        await db.refresh(sso_user)
        assert sso_user.password_reset_token is None
        assert sso_user.password_reset_expires_at is None
        mock_send.assert_not_awaited()

    async def test_smtp_not_configured_no_email_still_ok(self, client, db):
        user = await create_user(db, email="local2@test.com", role="member")
        await db.commit()

        with _patch_smtp_off():
            with patch(
                "app.api.v1.auth.email_service.send_email",
                new=AsyncMock(return_value=False),
            ) as mock_send:
                resp = await client.post(
                    "/api/v1/auth/forgot-password",
                    json={"email": "local2@test.com"},
                )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        await db.refresh(user)
        # No token written when SMTP isn't there — there'd be no way to deliver it.
        assert user.password_reset_token is None
        mock_send.assert_not_awaited()

    async def test_inactive_user_no_token(self, client, db):
        user = await create_user(db, email="inactive@test.com", role="member")
        user.is_active = False
        await db.commit()

        with _patch_smtp_on():
            with patch(
                "app.api.v1.auth.email_service.send_email",
                new=AsyncMock(return_value=True),
            ) as mock_send:
                resp = await client.post(
                    "/api/v1/auth/forgot-password",
                    json={"email": "inactive@test.com"},
                )
        assert resp.status_code == 200
        await db.refresh(user)
        assert user.password_reset_token is None
        mock_send.assert_not_awaited()

    async def test_empty_email_returns_ok(self, client, db):
        with _patch_smtp_on():
            resp = await client.post("/api/v1/auth/forgot-password", json={"email": ""})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


class TestValidateResetToken:
    async def test_invalid_token_returns_404(self, client, db):
        resp = await client.get("/api/v1/auth/validate-reset-token", params={"token": "bogus"})
        assert resp.status_code == 404

    async def test_empty_token_returns_404(self, client, db):
        # Empty token query param.
        resp = await client.get("/api/v1/auth/validate-reset-token", params={"token": ""})
        assert resp.status_code == 404

    async def test_expired_token_returns_404(self, client, db):
        user = await create_user(db, email="expired@test.com", role="member")
        user.password_reset_token = "expired-token-abc123"
        user.password_reset_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()

        resp = await client.get(
            "/api/v1/auth/validate-reset-token",
            params={"token": "expired-token-abc123"},
        )
        assert resp.status_code == 404

    async def test_valid_token_returns_email(self, client, db):
        user = await create_user(db, email="valid@test.com", role="member")
        user.password_reset_token = "valid-token-xyz789"
        user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        await db.commit()

        resp = await client.get(
            "/api/v1/auth/validate-reset-token",
            params={"token": "valid-token-xyz789"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"email": "valid@test.com"}


class TestResetPassword:
    async def _seed_token(self, db, *, email="reset@test.com", token="reset-token-1"):
        user = await create_user(db, email=email, role="member")
        user.password_reset_token = token
        user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        user.failed_login_attempts = 4
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=10)
        await db.commit()
        return user

    async def test_happy_path_updates_hash_and_clears_token(self, client, db):
        await self._seed_token(db)

        resp = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": "reset-token-1", "password": "BrandNewPass1"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        row = (await db.execute(select(User).where(User.email == "reset@test.com"))).scalar_one()
        # Token and expiry cleared.
        assert row.password_reset_token is None
        assert row.password_reset_expires_at is None
        # New password works.
        assert verify_password("BrandNewPass1", row.password_hash)
        # Lockout state cleared as a side effect.
        assert row.failed_login_attempts == 0
        assert row.locked_until is None

    async def test_weak_password_400(self, client, db):
        await self._seed_token(db, email="weak@test.com", token="weak-token")

        resp = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": "weak-token", "password": "short"},
        )
        assert resp.status_code == 400

    async def test_unknown_token_404(self, client, db):
        resp = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": "no-such-token", "password": "BrandNewPass1"},
        )
        assert resp.status_code == 404

    async def test_expired_token_404(self, client, db):
        user = await create_user(db, email="expired2@test.com", role="member")
        user.password_reset_token = "expired-2"
        user.password_reset_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()

        resp = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": "expired-2", "password": "BrandNewPass1"},
        )
        assert resp.status_code == 404

    async def test_token_is_single_use(self, client, db):
        await self._seed_token(db, email="single@test.com", token="single-use")

        first = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": "single-use", "password": "BrandNewPass1"},
        )
        assert first.status_code == 200

        second = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": "single-use", "password": "OtherPass1234"},
        )
        assert second.status_code == 404
