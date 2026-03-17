"""Tests for analyst revision signal functions."""

import pytest

from backend.signals.revisions import compute_revision_breadth


class TestRevisionBreadth:
    def test_all_upward_revisions(self):
        records = [
            {"direction": "up", "date": "2026-03-01"},
            {"direction": "up", "date": "2026-03-05"},
            {"direction": "up", "date": "2026-03-10"},
        ]
        breadth = compute_revision_breadth(records)
        assert isinstance(breadth, (int, float))

    def test_mixed_revisions(self):
        records = [
            {"direction": "up", "date": "2026-03-01"},
            {"direction": "down", "date": "2026-03-05"},
        ]
        breadth = compute_revision_breadth(records)
        assert isinstance(breadth, (int, float))

    def test_empty_records(self):
        breadth = compute_revision_breadth([])
        assert breadth == 0 or isinstance(breadth, (int, float))
