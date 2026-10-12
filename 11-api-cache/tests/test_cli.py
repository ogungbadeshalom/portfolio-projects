"""End-to-end CLI tests using Click's ``CliRunner``.

Each test targets a real temp-dir SQLite database via ``--db`` and exercises
the ``stats / list / clear / inspect`` commands for real.
"""
from __future__ import annotations

from click.testing import CliRunner

from apicache.cli import cli


def test_stats_on_empty_db(tmp_path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--db", str(tmp_path / "c.db"), "stats"])
    assert result.exit_code == 0, result.output
    assert "total_entries" in result.output
    assert "0" in result.output


def test_list_clear_inspect_flow(tmp_path) -> None:
    db = str(tmp_path / "cache.db")

    # Populate the cache with a couple of real entries first.
    import asyncio
    from apicache import APICache

    async def seed() -> None:
        c = APICache(db)
        await c.open()
        try:
            await c.set("alice", {"role": "admin"}, ttl=60, tags=["users", "admins"])
            await c.set("bob", {"role": "member"}, ttl=60, tags=["users"])
        finally:
            await c.close()

    asyncio.run(seed())

    runner = CliRunner()

    listed = runner.invoke(cli, ["--db", db, "list"])
    assert listed.exit_code == 0
    assert "alice" in listed.output
    assert "bob" in listed.output

    inspected = runner.invoke(cli, ["--db", db, "inspect", "alice"])
    assert inspected.exit_code == 0
    assert "admin" in inspected.output
    assert "users" in inspected.output

    stats = runner.invoke(cli, ["--db", db, "stats"])
    assert stats.exit_code == 0
    assert "total_entries" in stats.output
    # Verify the total_entries value line reports 2.
    total_line = next(l for l in stats.output.splitlines() if "total_entries" in l)
    assert total_line.strip().endswith("2")

    # Clear only the 'admins' tag → alice gone, bob stays.
    cleared = runner.invoke(cli, ["--db", db, "clear", "--tag", "admins"])
    assert cleared.exit_code == 0
    assert "1" in cleared.output

    listed2 = runner.invoke(cli, ["--db", db, "list"])
    assert "bob" in listed2.output
    assert "alice" not in listed2.output

    # Full clear → list reports empty.
    full = runner.invoke(cli, ["--db", db, "clear"])
    assert full.exit_code == 0
    empty = runner.invoke(cli, ["--db", db, "list"])
    assert empty.exit_code == 0
    assert "(empty)" in empty.output


def test_inspect_missing_key(tmp_path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--db", str(tmp_path / "c.db"), "inspect", "nope"])
    assert result.exit_code == 0
    assert "not found" in result.output