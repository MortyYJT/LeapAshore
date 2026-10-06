from sqlalchemy import select

from app.models.roadmap import MaterialTemplate, RoadmapPhase


def _discard(db_session, *rows) -> None:
    """Delete the rows a test created, if they are still there.

    Called from `finally`. Every test here uses a fixed primary key, so a row left behind by an
    assertion that failed halfway would make the next run fail for the wrong reason.
    """
    db_session.rollback()
    for model, key in rows:
        row = db_session.get(model, key)
        if row is not None:
            db_session.delete(row)
    db_session.commit()


def test_phase_and_material_round_trip(db_session, require_db):
    try:
        db_session.add(
            RoadmapPhase(key="selection", title="锁定申请组合", offset_days=330, sort_order=0)
        )
        db_session.flush()
        db_session.add(
            MaterialTemplate(
                key="aca-transcript",
                phase="selection",
                title="本科成绩单",
                detail="中英文对照，需教务处盖章",
                applies_to="all",
                sort_order=0,
            )
        )
        db_session.commit()

        material = db_session.execute(
            select(MaterialTemplate).where(MaterialTemplate.key == "aca-transcript")
        ).scalar_one()
        assert material.phase == "selection"
        # A material with no official basis yet must read as unattributed, not as attributed to nothing.
        assert material.source_id is None

        # Dropping the material first must be allowed: RESTRICT refuses only the reverse order.
        db_session.delete(material)
        db_session.delete(db_session.get(RoadmapPhase, "selection"))
        db_session.commit()
    finally:
        _discard(
            db_session, (MaterialTemplate, "aca-transcript"), (RoadmapPhase, "selection")
        )


def test_phase_key_is_unique(db_session, require_db):
    try:
        db_session.add(RoadmapPhase(key="dup-check", title="a", offset_days=1, sort_order=0))
        db_session.commit()
        db_session.add(RoadmapPhase(key="dup-check", title="b", offset_days=2, sort_order=1))
        try:
            db_session.commit()
        except Exception:
            db_session.rollback()
        else:
            raise AssertionError("a duplicate phase key was accepted")
    finally:
        _discard(db_session, (RoadmapPhase, "dup-check"))


def test_deleting_a_phase_is_refused_while_materials_reference_it(db_session, require_db):
    """A phase with materials must not vanish underneath them.

    The relationship is `passive_deletes=True`, so the delete really reaches the database rule and
    this fails when the foreign key is missing (the phase row goes) or CASCADE (the material row
    goes). It only passes while the rule is RESTRICT.
    """
    try:
        db_session.add(RoadmapPhase(key="fk-check", title="a", offset_days=1, sort_order=0))
        db_session.flush()
        db_session.add(
            MaterialTemplate(key="fk-check-mat", phase="fk-check", title="t", applies_to="all")
        )
        db_session.commit()

        db_session.delete(db_session.get(RoadmapPhase, "fk-check"))
        try:
            db_session.commit()
        except Exception:
            db_session.rollback()
        else:
            raise AssertionError("a phase was deleted while materials still referenced it")
    finally:
        _discard(
            db_session,
            (MaterialTemplate, "fk-check-mat"),
            (RoadmapPhase, "fk-check"),
        )
