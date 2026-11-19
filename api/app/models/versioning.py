"""A version on every applicant-editable row, moved by whoever changes the row.

Two devices of one account can edit the same row (`docs/product/PRD-multi-device.md`, 3.3). The
version is what lets the server refuse an update made against a row that has since changed: the
update states the version it was based on, and `app/services/versions.py` compares the two under a
lock.

The increment lives here rather than in each writer, because a writer that forgot it would leave a
change no other device can detect. Every ORM update of a versioned row with a net change adds one,
whether it came from the applicant's own routes, a recomputation, the advisor's tools or an account
merge. The increment is the SQL expression `version + 1`, so two transactions that update one row
without locking it still take two steps instead of both writing the number they read plus one.

A bulk `update()` statement bypasses mapper events and would not move the version; none of the
versioned tables is written that way.
"""

from sqlalchemy import Integer, event
from sqlalchemy.orm import Mapped, mapped_column, object_session


class Versioned:
    """Mixin: an integer `version` that starts at 1 and grows by one per change."""

    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


@event.listens_for(Versioned, "before_update", propagate=True)
def _move_the_version(mapper, connection, target) -> None:
    # `before_update` also fires for a row whose attributes were set to the values they already
    # held; a restated row has not changed, so its version stays.
    session = object_session(target)
    if session is not None and session.is_modified(target, include_collections=False):
        target.version = type(target).version + 1
