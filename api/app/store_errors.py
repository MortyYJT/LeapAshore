class AdvisorThreadRevisionConflictError(RuntimeError):
    """Raised when an advisor thread compare-and-swap observes a newer revision."""

    def __init__(
        self,
        thread_id: str,
        expected_revision: int | None,
        actual_revision: int | None,
    ) -> None:
        self.thread_id = thread_id
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        super().__init__(
            f"advisor thread {thread_id} revision conflict: "
            f"expected {expected_revision}, actual {actual_revision}"
        )
