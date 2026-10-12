"""Unit tests: exponential backoff + cron parser."""

from __future__ import annotations

import random
from datetime import datetime

import pytest

from scheduler import cron, retry


class TestBackoff:
    def test_exponential_growth(self):
        # attempts 0..3 -> base * 2**attempt
        delays = [retry.backoff_delay_seconds(i, base=1, max_seconds=1000, jitter=0)
                  for i in range(4)]
        assert delays == [1, 2, 4, 8]

    def test_capped_at_max(self):
        assert retry.backoff_delay_seconds(10, base=1, max_seconds=60, jitter=0) == 60
        assert retry.backoff_delay_seconds(5, base=2, max_seconds=30, jitter=0) == 30

    def test_jitter_changes_value(self):
        rng = random.Random(1)
        d0 = retry.backoff_delay_seconds(0, base=10, jitter=0.2, rng=rng)
        rng.seed(1)
        d1 = retry.backoff_delay_seconds(0, base=10, jitter=0.2, rng=rng)
        assert d0 == d1  # deterministic for a seeded RNG
        assert 0 <= d0 <= 12

    def test_is_exhausted(self):
        assert retry.is_exhausted(3, 3)
        assert not retry.is_exhausted(2, 3)

    def test_next_attempt_at_is_after_now(self):
        now = datetime(2026, 7, 15, 10, 0, 0)
        nxt = retry.next_attempt_at(1, base=1, max_seconds=10, jitter=0, now=now)
        assert nxt > now


class TestCron:
    def test_next_fire_minute(self):
        assert cron.next_fire("*/5 * * * *", datetime(2026, 7, 15, 10, 3)) == datetime(
            2026, 7, 15, 10, 5
        )

    def test_next_fire_hourly(self):
        assert cron.next_fire("0 * * * *", datetime(2026, 7, 15, 10, 15)) == datetime(
            2026, 7, 15, 11, 0
        )

    def test_next_fire_rolls_day(self):
        assert cron.next_fire("0 2 * * *", datetime(2026, 7, 15, 3, 0)) == datetime(
            2026, 7, 16, 2, 0
        )

    def test_dow_sunday_zero(self):
        # 2026-07-19 is Sunday.
        assert cron.next_fire("0 0 * * 0", datetime(2026, 7, 18, 12, 0)) == datetime(
            2026, 7, 19, 0, 0
        )

    def test_invalid_raises(self):
        with pytest.raises(cron.CronError):
            cron.next_fire("0 2 * *", datetime(2026, 7, 15, 10, 0))  # 4 fields
        with pytest.raises(cron.CronError):
            cron.next_fire("99 * * * *", datetime(2026, 7, 15, 10, 0))  # bad minute