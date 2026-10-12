"""CLI tests: schedule/start/ping/done/list/watchdog via Click's CliRunner."""

from __future__ import annotations

from click.testing import CliRunner

from cronmon.cli import cli


def _run(db_path, *args, expect_zero=True):
    runner = CliRunner()
    result = runner.invoke(cli, ["--db", str(db_path), *args])
    if expect_zero:
        assert result.exit_code == 0, result.output + result.exception or ""
    return result


class TestCli:
    def test_schedule_creates_job_and_list_shows_it(self, tmp_path):
        db = tmp_path / "c.db"
        _run(db, "schedule", "Backup", "--cron", "0 2 * * *", "--max-duration", "60")
        out = _run(db, "list").output
        assert "Backup" in out

    def test_duplicate_schedule_updates(self, tmp_path):
        db = tmp_path / "c.db"
        _run(db, "schedule", "Backup", "--cron", "0 2 * * *")
        _run(db, "schedule", "Backup", "--max-duration", "120")
        out = _run(db, "list").output
        assert "max=120" in out

    def test_start_ping_done_flow(self, tmp_path):
        db = tmp_path / "c.db"
        _run(db, "schedule", "Backup", "--cron", "0 2 * * *")
        _run(db, "start", "Backup", "--client-run-id", "k1")
        _run(db, "ping", "Backup")
        done = _run(db, "done", "Backup", "--status", "ok").output
        assert "status 'ok'" in done

    def test_done_fail_creates_alert(self, tmp_path):
        db = tmp_path / "c.db"
        _run(db, "schedule", "Backup")
        _run(db, "start", "Backup")
        out = _run(db, "done", "Backup", "--status", "fail").output
        assert "Raised alert" in out

    def test_unknown_job_starting_exits_nonzero(self, tmp_path):
        db = tmp_path / "c.db"
        result = _run(db, "start", "Ghost", expect_zero=False)
        assert result.exit_code == 1
        assert "Unknown job" in result.output

    def test_watchdog_sweep_over_duration(self, tmp_path):
        from datetime import timedelta

        db_path = tmp_path / "w.db"
        _run(db_path, "schedule", "Long", "--max-duration", "10")
        # Open a run that started 5 minutes ago (overdue for max-duration=10s),
        # reusing the global engine but reconfigured onto the same file store.
        from cronmon.database import init_db
        from cronmon.models import Job, Run, now_utc

        session = init_db(str(db_path), seed=False)
        job = session.query(Job).filter(Job.name == "Long").first()
        session.add(Run(job_id=job.id, started_at=now_utc() - timedelta(minutes=5)))
        session.commit()
        session.close()

        out = _run(db_path, "watchdog").output
        assert "new alert" in out
        from cronmon.models import Alert

        session = init_db(str(db_path), seed=False)
        try:
            job = session.query(Job).filter(Job.name == "Long").first()
            assert (
                session.query(Alert)
                .filter(Alert.job_id == job.id, Alert.type == "over_duration")
                .count()
                == 1
            )
        finally:
            session.close()

    def test_init_prints_key(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["--db", str(tmp_path / "k.db"), "init"])
        assert result.exit_code == 0
        assert "API key:" in result.output

    def test_start_dedupes_by_client_run_id(self, tmp_path):
        db = tmp_path / "c.db"
        _run(db, "schedule", "Backup")
        first = _run(db, "start", "Backup", "--client-run-id", "same").output
        _run(db, "done", "Backup", "--status", "ok")
        _run(db, "start", "Backup", "--client-run-id", "same")
        assert "Started run" in first