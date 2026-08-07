"""
Tests that `growth-engine run` reports failure through its exit code.

execute_scheduled_slot() converts every exception into a {"status": "failed"}
dict, so without an explicit sys.exit the CLI returns 0 and GitHub Actions
reports a green run even when nothing was posted.
"""
from argparse import Namespace

import pytest

from main import cmd_growth_engine


def _run_args():
    return Namespace(ge_command="run", slot=None, dry_run=False)


def _patch_slot_result(mocker, result):
    return mocker.patch(
        "core.growth_engine.execute_scheduled_slot", return_value=result
    )


class TestExitCode:
    def test_failed_slot_exits_nonzero(self, mocker):
        """A swallowed exception must still fail the workflow"""
        _patch_slot_result(mocker, {"status": "failed", "error": "upload rejected"})

        with pytest.raises(SystemExit) as exit_info:
            cmd_growth_engine(_run_args())

        assert exit_info.value.code == 1

    def test_successful_slot_exits_zero(self, mocker):
        _patch_slot_result(
            mocker,
            {"status": "success", "url": "https://youtu.be/x", "video_id": "x",
             "title": "t"},
        )

        cmd_growth_engine(_run_args())

    @pytest.mark.parametrize("status", ["suppressed", "dry_run"])
    def test_non_failure_statuses_exit_zero(self, mocker, status):
        """Suppression and dry runs are deliberate outcomes, not errors"""
        _patch_slot_result(mocker, {"status": status, "message": "skipped"})

        cmd_growth_engine(_run_args())
