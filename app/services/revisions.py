"""月度产能受控修订流程。

规则：
- 封账月份（封账边界及之前的年月，支持跨年比较）拒绝任何更改；
- 可修订月份的每次修订追加一条带原因与操作者的版本记录，报告主表始终保存生效版本；
- 当达产率跨过承诺产能阈值（达标线）时，同步调整仍未关闭的自动跟进事项；
  手工跟进事项与已关闭事项一律不动；
- 相同修订（同一幂等键）重复提交只返回首次结果，不产生第二次影响；
- 季度统计始终基于报告主表中的生效版本重算。
"""

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from .. import models, schemas
from ..enums import FollowUpStatus, FollowUpPriority

# 达产率达标阈值（百分比）：实际产量相对承诺月产能达到该比例视为达标
ACHIEVEMENT_THRESHOLD_PCT = 100.0

OPEN_FOLLOW_UP_STATUSES = (
    FollowUpStatus.PENDING,
    FollowUpStatus.IN_PROGRESS,
)


def determine_follow_up_priority(gap_pct: float) -> FollowUpPriority:
    if gap_pct >= 50:
        return FollowUpPriority.URGENT
    elif gap_pct >= 30:
        return FollowUpPriority.HIGH
    elif gap_pct >= 15:
        return FollowUpPriority.MEDIUM
    return FollowUpPriority.LOW


def get_promised_monthly_capacity(project: models.Project) -> float:
    if project.promised_monthly_capacity_tonnes:
        return project.promised_monthly_capacity_tonnes
    if project.expected_annual_capacity_tonnes:
        return project.expected_annual_capacity_tonnes / 12.0
    return 0.0


def _get_project(db: Session, project_id: int) -> Optional[models.Project]:
    return db.query(models.Project).filter(models.Project.id == project_id).first()


def _get_report(db: Session, report_id: int) -> Optional[models.MonthlyCapacityReport]:
    return (
        db.query(models.MonthlyCapacityReport)
        .filter(models.MonthlyCapacityReport.id == report_id)
        .first()
    )


def month_key(year: int, month: int) -> Tuple[int, int]:
    """跨年月份的可比较键，保证 2025-12 早于 2026-01。"""
    return (year, month)


def get_closed_boundary(
    db: Session,
) -> Optional[models.CapacityClosedMonth]:
    """返回当前封账边界（已封账的最近年月），未封账时为 None。"""
    return (
        db.query(models.CapacityClosedMonth)
        .order_by(
            models.CapacityClosedMonth.close_year.desc(),
            models.CapacityClosedMonth.close_month.desc(),
        )
        .first()
    )


def boundary_payload(boundary: Optional[models.CapacityClosedMonth]) -> Optional[Dict[str, Any]]:
    if boundary is None:
        return None
    return {"year": boundary.close_year, "month": boundary.close_month}


def is_month_open(
    year: int,
    month: int,
    boundary: Optional[models.CapacityClosedMonth],
) -> bool:
    if boundary is None:
        return True
    return month_key(year, month) > month_key(
        boundary.close_year, boundary.close_month
    )


def close_months_through(
    db: Session,
    close_year: int,
    close_month: int,
    reason: Optional[str] = None,
    operator: Optional[str] = None,
) -> models.CapacityClosedMonth:
    """将截至指定年月（含）的所有月份封账；重复封账只推进边界。"""
    existing = (
        db.query(models.CapacityClosedMonth)
        .filter(
            models.CapacityClosedMonth.close_year == close_year,
            models.CapacityClosedMonth.close_month == close_month,
        )
        .first()
    )
    if existing:
        existing.reason = reason
        existing.operator = operator
        db.commit()
        db.refresh(existing)
        return existing

    record = models.CapacityClosedMonth(
        close_year=close_year,
        close_month=close_month,
        reason=reason,
        operator=operator,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    # 封账边界只取最近年月，清理更早的冗余标记。
    stale = (
        db.query(models.CapacityClosedMonth)
        .filter(models.CapacityClosedMonth.id != record.id)
        .all()
    )
    for old in stale:
        if month_key(old.close_year, old.close_month) <= month_key(
            close_year, close_month
        ):
            db.delete(old)
    db.commit()
    return record


def _utilization_rate(actual: float, promised: float) -> Optional[float]:
    if promised > 0:
        return round((actual / promised) * 100, 2)
    return None


def _is_below_threshold(rate: Optional[float]) -> bool:
    return rate is not None and rate < ACHIEVEMENT_THRESHOLD_PCT


def _auto_follow_up_for_report(
    db: Session, report_id: int
) -> List[models.CapacityFollowUp]:
    return (
        db.query(models.CapacityFollowUp)
        .filter(
            models.CapacityFollowUp.report_id == report_id,
            models.CapacityFollowUp.auto_generated == 1,
        )
        .all()
    )


def _sync_follow_ups(
    db: Session,
    *,
    project: models.Project,
    report: models.MonthlyCapacityReport,
    revision: models.CapacityReportRevision,
    promised: float,
    old_rate: Optional[float],
    new_rate: Optional[float],
    old_actual: float,
    new_actual: float,
) -> Tuple[bool, List[Dict[str, Any]]]:
    """根据阈值跨越结果同步仍未关闭的自动跟进事项。

    返回 (是否跨过阈值, 变更明细)。手工跟进与已关闭/已解决事项不受影响。
    """
    changes: List[Dict[str, Any]] = []
    crossed = False
    old_below = _is_below_threshold(old_rate)
    new_below = _is_below_threshold(new_rate)

    if old_rate is not None and new_rate is not None and old_below != new_below:
        crossed = True

    autos = _auto_follow_up_for_report(db, report.id)
    open_autos = [fu for fu in autos if fu.status in OPEN_FOLLOW_UP_STATUSES]

    note = (
        f"依据 {report.report_year}年{report.report_month}月 产能修订第 {revision.version_no} 版"
        f"（操作者：{revision.operator or '未记录'}，原因：{revision.reason or '未填写'}）"
    )

    if crossed and not new_below:
        # 未达标 → 达标：仍未关闭的自动跟进事项标记为已解决。
        for fu in open_autos:
            fu.status = FollowUpStatus.RESOLVED
            fu.resolution = (
                (fu.resolution + "\n" if fu.resolution else "")
                + f"修订后达产率 {new_rate:.2f}% 已达标，自动关闭。{note}"
            )
            fu.last_revision_id = revision.id
            changes.append(
                {
                    "action": "resolved",
                    "follow_up_id": fu.id,
                    "title": fu.title,
                    "status": fu.status.value,
                    "priority": fu.priority.value,
                    "gap_percentage": fu.gap_percentage,
                }
            )
    elif new_below:
        gap_pct = round(((promised - new_actual) / promised) * 100, 2) if promised > 0 else 0.0
        if open_autos:
            # 仍在阈值之下（含首次跌入）：把缺口变化同步到仍未关闭的自动事项。
            for fu in open_autos:
                fu.gap_percentage = gap_pct
                fu.priority = determine_follow_up_priority(gap_pct)
                fu.description = (
                    f"承诺月产能 {promised:.2f} 吨，修订后实际产量 {new_actual:.2f} 吨，"
                    f"缺口 {gap_pct:.2f}%。{note}"
                )
                fu.last_revision_id = revision.id
                changes.append(
                    {
                        "action": "updated",
                        "follow_up_id": fu.id,
                        "title": fu.title,
                        "status": fu.status.value,
                        "priority": fu.priority.value,
                        "gap_percentage": gap_pct,
                    }
                )
        elif crossed:
            # 由达标跌入未达标、且没有仍未关闭的自动事项（旧事项均已关闭或从未生成）：补建一条。
            follow_up = models.CapacityFollowUp(
                project_id=project.id,
                report_id=report.id,
                title=f"{report.report_year}年{report.report_month}月产能未达标",
                description=(
                    f"承诺月产能 {promised:.2f} 吨，修订后实际产量 {new_actual:.2f} 吨，"
                    f"缺口 {gap_pct:.2f}%。{note}"
                ),
                status=FollowUpStatus.PENDING,
                priority=determine_follow_up_priority(gap_pct),
                gap_percentage=gap_pct,
                responsible_person=project.project_leader,
                source="AUTO",
                auto_generated=1,
                last_revision_id=revision.id,
            )
            db.add(follow_up)
            db.flush()
            changes.append(
                {
                    "action": "created",
                    "follow_up_id": follow_up.id,
                    "title": follow_up.title,
                    "status": follow_up.status.value,
                    "priority": follow_up.priority.value,
                    "gap_percentage": gap_pct,
                }
            )

    return crossed, changes


def _revision_to_dict(rev: models.CapacityReportRevision) -> Dict[str, Any]:
    return {
        "id": rev.id,
        "report_id": rev.report_id,
        "project_id": rev.project_id,
        "version_no": rev.version_no,
        "actual_output_tonnes": rev.actual_output_tonnes,
        "capacity_utilization_rate": rev.capacity_utilization_rate,
        "employee_count": rev.employee_count,
        "local_material_procurement_10k": rev.local_material_procurement_10k,
        "remarks": rev.remarks,
        "reported_by": rev.reported_by,
        "change_type": rev.change_type,
        "reason": rev.reason,
        "operator": rev.operator,
        "idempotency_key": rev.idempotency_key,
        "created_at": rev.created_at,
    }


def _build_idempotent_response(
    report: models.MonthlyCapacityReport,
    existing: models.CapacityReportRevision,
    boundary: Optional[models.CapacityClosedMonth],
    db: Session,
) -> Dict[str, Any]:
    previous = None
    if existing.version_no >= 2:
        previous = (
            db.query(models.CapacityReportRevision)
            .filter(
                models.CapacityReportRevision.report_id == existing.report_id,
                models.CapacityReportRevision.version_no == existing.version_no - 1,
            )
            .first()
        )
    return {
        "message": "相同修订已提交过，本次未重复生效",
        "idempotent": True,
        "effects_applied": False,
        "closed_boundary": boundary_payload(boundary),
        "report_id": report.id,
        "project_id": report.project_id,
        "report_year": report.report_year,
        "report_month": report.report_month,
        "current_version": report.current_version,
        "previous_version_no": previous.version_no if previous else None,
        "new_version_no": existing.version_no,
        "relationship": "no-op：该幂等键已生成过版本，未产生新版本与跟进调整",
        "threshold_crossed": False,
        "old_version": _revision_to_dict(previous) if previous else None,
        "new_version": _revision_to_dict(existing),
        "follow_up_changes": [],
    }


def apply_revision(
    db: Session,
    report_id: int,
    payload: schemas.CapacityRevisionCreate,
    *,
    change_type: str = "REVISION",
) -> Dict[str, Any]:
    """对指定月度产能报告实施受控修订。"""
    report = _get_report(db, report_id)
    if not report:
        raise RevisionNotFound()

    boundary = get_closed_boundary(db)
    if not is_month_open(report.report_year, report.report_month, boundary):
        raise MonthClosedError(
            report.report_year, report.report_month, boundary
        )

    # 幂等：同一报告 + 同一幂等键直接回放首次结果，不再产生任何副作用。
    if payload.idempotency_key:
        existing = (
            db.query(models.CapacityReportRevision)
            .filter(
                models.CapacityReportRevision.report_id == report_id,
                models.CapacityReportRevision.idempotency_key
                == payload.idempotency_key,
            )
            .first()
        )
        if existing:
            return _build_idempotent_response(report, existing, boundary, db)

    # 乐观锁：并发修订时允许调用方声明基于哪个版本提交。
    if (
        payload.expected_version is not None
        and payload.expected_version != report.current_version
    ):
        raise VersionConflictError(report.current_version, payload.expected_version)

    project = _get_project(db, report.project_id)
    promised = get_promised_monthly_capacity(project) if project else 0.0

    data = payload.model_dump(exclude_unset=True)
    old_actual = report.actual_output_tonnes
    old_rate = report.capacity_utilization_rate
    if old_rate is None and promised > 0:
        old_rate = round((old_actual / promised) * 100, 2)

    new_actual = data.get("actual_output_tonnes", old_actual)
    new_rate = data.get("capacity_utilization_rate")
    if new_rate is None and promised > 0:
        new_rate = _utilization_rate(new_actual, promised)
    elif new_rate is None:
        new_rate = old_rate
    rate_touched = (
        "actual_output_tonnes" in data or "capacity_utilization_rate" in data
    )

    prev_version_no = report.current_version
    next_version_no = prev_version_no + 1

    # 迁移前的历史报告可能没有任何版本快照：先补建第 1 版，保证版本链完整。
    has_revisions = (
        db.query(models.CapacityReportRevision.id)
        .filter(models.CapacityReportRevision.report_id == report.id)
        .first()
        is not None
    )
    if not has_revisions:
        db.add(
            models.CapacityReportRevision(
                report_id=report.id,
                project_id=report.project_id,
                version_no=1,
                actual_output_tonnes=old_actual,
                capacity_utilization_rate=old_rate,
                employee_count=report.employee_count,
                local_material_procurement_10k=report.local_material_procurement_10k,
                remarks=report.remarks,
                reported_by=report.reported_by,
                change_type="CREATE",
                reason="历史数据迁移：补建初始登记快照",
                operator=report.reported_by,
            )
        )
        report.current_version = 1

    revision = models.CapacityReportRevision(
        report_id=report.id,
        project_id=report.project_id,
        version_no=next_version_no,
        actual_output_tonnes=new_actual,
        capacity_utilization_rate=new_rate,
        employee_count=data.get("employee_count", report.employee_count),
        local_material_procurement_10k=data.get(
            "local_material_procurement_10k",
            report.local_material_procurement_10k,
        ),
        remarks=data.get("remarks", report.remarks),
        reported_by=data.get("reported_by", report.reported_by),
        change_type=change_type,
        reason=payload.reason,
        operator=payload.operator,
        idempotency_key=payload.idempotency_key,
    )
    db.add(revision)

    # 主表更新为生效版本。
    report.actual_output_tonnes = new_actual
    report.capacity_utilization_rate = new_rate
    if "employee_count" in data:
        report.employee_count = data["employee_count"]
    if "local_material_procurement_10k" in data:
        report.local_material_procurement_10k = data["local_material_procurement_10k"]
    if "remarks" in data:
        report.remarks = data["remarks"]
    if "reported_by" in data:
        report.reported_by = data["reported_by"]
    report.current_version = next_version_no
    crossed, follow_up_changes = (False, [])
    try:
        db.flush()  # 取得 revision.id，供跟进事项关联
        if rate_touched and project is not None:
            crossed, follow_up_changes = _sync_follow_ups(
                db,
                project=project,
                report=report,
                revision=revision,
                promised=promised,
                old_rate=old_rate,
                new_rate=new_rate,
                old_actual=old_actual,
                new_actual=new_actual,
            )
        db.commit()
    except Exception:
        # 并发下唯一约束（版本号 / 幂等键）冲突：回滚后按幂等回放或报并发冲突。
        db.rollback()
        if payload.idempotency_key:
            existing = (
                db.query(models.CapacityReportRevision)
                .filter(
                    models.CapacityReportRevision.report_id == report_id,
                    models.CapacityReportRevision.idempotency_key
                    == payload.idempotency_key,
                )
                .first()
            )
            if existing:
                report = _get_report(db, report_id)
                return _build_idempotent_response(
                    report, existing, get_closed_boundary(db), db
                )
        raise ConcurrentRevisionError()

    db.refresh(revision)
    previous = (
        db.query(models.CapacityReportRevision)
        .filter(
            models.CapacityReportRevision.report_id == report.id,
            models.CapacityReportRevision.version_no == prev_version_no,
        )
        .first()
    )

    return {
        "message": "修订已生效",
        "idempotent": False,
        "effects_applied": True,
        "closed_boundary": boundary_payload(boundary),
        "report_id": report.id,
        "project_id": report.project_id,
        "report_year": report.report_year,
        "report_month": report.report_month,
        "current_version": next_version_no,
        "previous_version_no": prev_version_no,
        "new_version_no": next_version_no,
        "relationship": f"第 {next_version_no} 版取代第 {prev_version_no} 版，主表当前为生效版本",
        "threshold_crossed": crossed,
        "old_version": _revision_to_dict(previous) if previous else None,
        "new_version": _revision_to_dict(revision),
        "follow_up_changes": follow_up_changes,
    }


def list_revisions(db: Session, report_id: int) -> List[Dict[str, Any]]:
    report = _get_report(db, report_id)
    if not report:
        raise RevisionNotFound()
    return [_revision_to_dict(rev) for rev in report.revisions]


def create_initial_revision(
    db: Session,
    report: models.MonthlyCapacityReport,
    operator: Optional[str] = None,
) -> models.CapacityReportRevision:
    """初始登记时写入第 1 版快照（调用方负责提交）。"""
    revision = models.CapacityReportRevision(
        report_id=report.id,
        project_id=report.project_id,
        version_no=1,
        actual_output_tonnes=report.actual_output_tonnes,
        capacity_utilization_rate=report.capacity_utilization_rate,
        employee_count=report.employee_count,
        local_material_procurement_10k=report.local_material_procurement_10k,
        remarks=report.remarks,
        reported_by=report.reported_by,
        change_type="CREATE",
        reason="初始登记",
        operator=operator or report.reported_by,
    )
    db.add(revision)
    report.current_version = 1
    return revision


class RevisionNotFound(Exception):
    pass


class MonthClosedError(Exception):
    def __init__(self, year: int, month: int, boundary):
        self.year = year
        self.month = month
        self.boundary = boundary
        super().__init__(
            f"{year}年{month}月已封账"
            f"（封账边界：{boundary.close_year}年{boundary.close_month}月），拒绝更改"
        )


class VersionConflictError(Exception):
    def __init__(self, current: int, expected: int):
        self.current = current
        self.expected = expected
        super().__init__(f"版本冲突：当前为第 {current} 版，提交基于第 {expected} 版")


class ConcurrentRevisionError(Exception):
    def __init__(self):
        super().__init__("并发修订冲突，请基于最新版本重试")
