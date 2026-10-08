"""A refusal a caller can act on.

Both write services refuse requests for the same kind of reason — a state the rule does not allow, a
value nothing accepts, a row that is not the caller's — and every refusal carries an HTTP status and a
message the interface shows as-is. One type rather than one per service, because the routers' job is
identical for both: map it to a response and keep the subject's cookie on it.

Carried as an exception rather than returned because every caller up the stack has to do the same
thing with it, and a return value is the one a later edit forgets to check.
"""


class Refused(Exception):
    """A refusal with the status and the message the caller should see."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
