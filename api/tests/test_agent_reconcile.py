import asyncio

from app.agent_store.reconcile import reconcile_projection


class FakeStore:
    rows = {
        "equal": (2, "active", None),
        "old": (1, "active", None),
        "ahead": (3, "active", None),
        "mismatch": (2, "deleted", "different"),
    }

    async def get_projection(self, aggregate_id):
        from types import SimpleNamespace

        item = self.rows.get(aggregate_id)
        if item is None:
            return None
        return SimpleNamespace(aggregate_id=aggregate_id, source_revision=item[0], status=item[1], content_hash=item[2])


def test_reconciliation_reports_only_ids_revisions_and_safe_metadata() -> None:
    async def exercise() -> None:
        expected = [
            {"aggregate_id": "missing", "source_revision": 1, "status": "active"},
            {"aggregate_id": "old", "source_revision": 2, "status": "active"},
            {"aggregate_id": "ahead", "source_revision": 2, "status": "active"},
            {"aggregate_id": "mismatch", "source_revision": 2, "status": "active", "content_hash": "expected"},
            {"aggregate_id": "equal", "source_revision": 2, "status": "active"},
        ]
        report = await reconcile_projection(expected, FakeStore())
        assert (report.checked, report.missing, report.stale, report.ahead, report.metadata_mismatch) == (5, 1, 1, 1, 1)

    asyncio.run(exercise())
