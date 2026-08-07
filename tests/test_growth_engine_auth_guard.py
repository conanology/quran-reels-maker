"""
Tests the pre-flight YouTube auth check in execute_scheduled_slot.

Without it, a dead refresh token reaches get_authenticated_service(), which
falls back to an interactive OAuth flow and blocks forever on a headless
runner - burning the full 180 minute job timeout instead of failing fast.
"""
import pytest

from core.growth_engine import execute_scheduled_slot


@pytest.fixture
def not_suppressed(mocker):
    return mocker.patch(
        "core.growth_engine.is_publishing_suppressed", return_value=False
    )


@pytest.fixture
def dead_credentials(mocker):
    return mocker.patch(
        "youtube.auth.check_authentication_status",
        return_value={"status": "not_authenticated", "message": "no token"},
    )


class TestAuthPreflight:
    def test_dead_credentials_fail_before_any_work(
        self, mocker, not_suppressed, dead_credentials
    ):
        """Must bail out before rendering, not after a three hour render"""
        mecca_time = mocker.patch("core.growth_engine.get_mecca_time")

        result = execute_scheduled_slot(slot_name="morning_short", dry_run=False)

        assert result["status"] == "failed"
        assert "not authenticated" in result["error"].lower()
        mecca_time.assert_not_called()

    def test_expired_credentials_are_allowed_through(
        self, mocker, not_suppressed
    ):
        """'expired' refreshes on use, so it must not block a run"""
        mocker.patch(
            "youtube.auth.check_authentication_status",
            return_value={"status": "expired", "message": "will refresh"},
        )
        mocker.patch("core.growth_engine.get_mecca_time", side_effect=RuntimeError("reached"))

        with pytest.raises(RuntimeError, match="reached"):
            execute_scheduled_slot(slot_name="morning_short", dry_run=False)

    def test_dry_run_skips_the_auth_check(self, mocker, not_suppressed):
        """Dry runs never upload, so they must work without credentials"""
        auth = mocker.patch("youtube.auth.check_authentication_status")

        result = execute_scheduled_slot(slot_name="morning_short", dry_run=True)

        assert result["status"] == "dry_run"
        auth.assert_not_called()
