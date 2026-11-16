"""Read-only check that the initial publish landed: 12 attributed open-tier passages (2 per level), 0 restricted."""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Passage

LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
PER_LEVEL = 2


@dataclass
class VerifyReport:
    open_by_level: dict[str, int] = field(default_factory=dict)
    open_total: int = 0
    restricted_total: int = 0
    missing_attribution: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def lines(self) -> list[str]:
        out = [f"open-tier ingested passages: {self.open_total} (expected {PER_LEVEL * len(LEVELS)})"]
        out += [f"  {lv}: {self.open_by_level.get(lv, 0)} (expected {PER_LEVEL})" for lv in LEVELS]
        out.append(f"restricted-tier passages: {self.restricted_total} (expected 0)")
        out.append(f"open passages missing attribution: {self.missing_attribution} (expected 0)")
        out += [f"MISMATCH: {p}" for p in self.problems]
        out.append("verify-publish: OK" if self.ok else "verify-publish: FAILED")
        return out


def _blank(col):
    return (col.is_(None)) | (func.btrim(col) == "")


def verify_publish(session: Session) -> VerifyReport:
    """Count only; never writes. Ingested open passages are those with a source_url."""
    rep = VerifyReport()
    rows = session.execute(
        select(Passage.level, func.count()).where(
            Passage.license_tier == "open", Passage.source_url.is_not(None)
        ).group_by(Passage.level)
    ).all()
    rep.open_by_level = {lvl: n for lvl, n in rows}
    rep.open_total = sum(rep.open_by_level.values())
    rep.restricted_total = session.scalar(
        select(func.count()).select_from(Passage).where(Passage.license_tier != "open")
    ) or 0
    rep.missing_attribution = session.scalar(
        select(func.count()).select_from(Passage).where(
            Passage.license_tier == "open", Passage.source_url.is_not(None),
            _blank(Passage.source_title) | _blank(Passage.author)
            | _blank(Passage.license) | (func.btrim(Passage.source_url) == ""),
        )
    ) or 0

    if rep.open_total != PER_LEVEL * len(LEVELS):
        rep.problems.append(f"open total {rep.open_total} != {PER_LEVEL * len(LEVELS)}")
    for lv in LEVELS:
        if rep.open_by_level.get(lv, 0) != PER_LEVEL:
            rep.problems.append(f"level {lv} has {rep.open_by_level.get(lv, 0)}, expected {PER_LEVEL}")
    for lv in set(rep.open_by_level) - set(LEVELS):
        rep.problems.append(f"unexpected level {lv!r}")
    if rep.restricted_total:
        rep.problems.append(f"{rep.restricted_total} restricted-tier passage(s) present")
    if rep.missing_attribution:
        rep.problems.append(f"{rep.missing_attribution} open passage(s) lack attribution")
    return rep
