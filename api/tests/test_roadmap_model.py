from sqlalchemy import select

from app.models.roadmap import MaterialTemplate, RoadmapPhase


def test_phase_and_material_round_trip(db_session, require_db):
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

    db_session.delete(material)
    db_session.delete(db_session.get(RoadmapPhase, "selection"))
    db_session.commit()


def test_phase_key_is_unique(db_session, require_db):
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
        db_session.execute(
            select(RoadmapPhase).where(RoadmapPhase.key == "dup-check")
        )
        for row in db_session.execute(
            select(RoadmapPhase).where(RoadmapPhase.key == "dup-check")
        ).scalars():
            db_session.delete(row)
        db_session.commit()


def test_deleting_a_phase_is_refused_while_materials_reference_it(db_session, require_db):
    """A phase with materials must not vanish underneath them."""
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
        db_session.delete(db_session.get(MaterialTemplate, "fk-check-mat"))
        db_session.delete(db_session.get(RoadmapPhase, "fk-check"))
        db_session.commit()
