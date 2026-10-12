"""Cron-expression parser unit tests."""

from __future__ import annotations

from datetime import datetime

import pytest

from cronmon.crontab import CronExpr, next_fire


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


class TestCronMatch:
    def test_wildcard_matches_every_minute(self):
        expr = CronExpr("* * * * *")
        assert expr.matches(_dt("2026-07-15T10:00:00"))
        assert expr.matches(_dt("2026-07-15T23:59:00"))

    def test_specific_minutes_and_hours(self):
        expr = CronExpr("30 2 * * *")  # 02:30 daily
        assert expr.matches(_dt("2026-07-15T02:30:00"))
        assert not expr.matches(_dt("2026-07-15T02:31:00"))
        assert not expr.matches(_dt("2026-07-15T03:30:00"))

    def test_lists_and_ranges(self):
        expr = CronExpr("0,15,30,45 9-17 * * 1-5")
        assert expr.matches(_dt("2026-07-15T10:15:00"))  # Wed (dow 3)
        assert not expr.matches(_dt("2026-07-11T10:15:00"))  # Sat (dow 6)

    def test_step_values(self):
        expr = CronExpr("*/5 * * * *")
        assert expr.matches(_dt("2026-07-15T10:05:00"))
        assert not expr.matches(_dt("2026-07-15T10:06:00"))

    def test_sunday_zero(self):
        # cron dow 0 = Sunday. 2026-07-19 is a Sunday.
        expr = CronExpr("0 0 * * 0")
        assert expr.matches(_dt("2026-07-19T00:00:00"))
        assert not expr.matches(_dt("2026-07-20T00:00:00"))  # Monday


class TestNextFire:
    def test_next_fire_same_day_forward(self):
        expr = CronExpr("0 * * * *")  # every hour on the hour
        # 10:15 -> next fire 11:00
        nxt = expr.next_fire(_dt("2026-07-15T10:15:00"))
        assert nxt == _dt("2026-07-15T11:00:00")

    def test_prev_fire_step_back(self):
        expr = CronExpr("0 * * * *")
        prev = expr.prev_fire(_dt("2026-07-15T10:00:00"))
        assert prev == _dt("2026-07-15T09:00:00")

    def test_next_fire_rolls_over_day(self):
        expr = CronExpr("0 2 * * *")
        nxt = expr.next_fire(_dt("2026-07-15T03:00:00"))
        assert nxt == _dt("2026-07-16T02:00:00")

    def test_invalid_expression_raises(self):
        with pytest.raises(ValueError):
            CronExpr("0 2 * *")  # only 4 fields
        with pytest.raises(ValueError):
            CronExpr("99 * * * *")  # out of range minute
        with pytest.raises(ValueError):
            CronExpr("1-2-3 * * * *")  # malformed

    def test_next_fire_convenience(self):
        assert next_fire("*/10 * * * *", _dt("2026-07-15T10:03:00")) == _dt(
            "2026-07-15T10:10:00"
        )