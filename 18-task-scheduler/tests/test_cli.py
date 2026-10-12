"""CLI tests via Click's CliRunner against a temp file-backed store."""

from __future__ import annotations

from click.testing import CliRunner

from scheduler.cli import cli


def _invoke(db_path, *args, expect_zero=True):
    runner = CliRunner()
    result = runner.invoke(cli, ["--db", str(db_path), *args])
    if expect_zero:
        assert result.exit_code == 0, result.output or str(result.exception)
    return result


class TestCli:
    def test_schedule_and_list(self, tmp_path):
        db = tmp_path / "s.db"
        out = _invoke(db, "schedule", "send_email", "--payload", '{"to":"a@b.co"}').output
        assert "Scheduled task #1" in out or "Scheduled task" in out
        listed = _invoke(db, "list").output
        assert "send_email" in listed

    def test_schedule_cron(self, tmp_path):
        db = tmp_path / "s.db"
        _invoke(db, "schedule", "cleanup", "--cron", "0 * * * *")
        assert "cleanup" in _invoke(db, "list").output

    def test_schedule_unknown_task_fails(self, tmp_path):
        db = tmp_path / "s.db"
        result = _invoke(db, "schedule", "nope", expect_zero=False)
        assert result.exit_code == 1
        assert "Unknown task" in result.output

    def test_bad_payload_json_fails(self, tmp_path):
        db = tmp_path / "s.db"
        result = _invoke(db, "schedule", "send_email", "--payload", "not json",
                         expect_zero=False)
        assert result.exit_code == 1

    def test_show_missing_task_errors(self, tmp_path):
        db = tmp_path / "s.db"
        result = _invoke(db, "show", "999", expect_zero=False)
        assert result.exit_code == 1

    def test_tasks_lists_handlers(self, tmp_path):
        db = tmp_path / "s.db"
        out = _invoke(db, "tasks").output
        assert "send_email" in out and "fail_task" in out

    def test_dlq_empty_output(self, tmp_path):
        db = tmp_path / "s.db"
        assert "empty" in _invoke(db, "dlq").output.lower()

    def test_cancel_missing(self, tmp_path):
        db = tmp_path / "s.db"
        result = _invoke(db, "cancel", "999", expect_zero=False)
        assert result.exit_code == 1