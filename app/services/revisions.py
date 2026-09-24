"""月度产能受控修订、封账账期与季度重算服务。

规则：
- 封账边界取所有 AccountingPeriod 中最大的 closed_through 月份（year*12+month-1），
  小于等于边界的月份拒绝任何登记/修订/删除（跨年月份用周期序号比较）。
- 每次可修订月份的更正生成不可变的 CapacityReportRevision（原因、操作者、新旧快照）。
- 达产率跨越 100% 阈值时联动该月报下仍未关闭的跟进事项（含手工挂接事项）：
  下方→达标点关闭，达标→下方重开一条修订联动事项。
- idempotency_key 相同的重复提交返回首次结果，不产生第二次影响；
  (report_id, revision_no) 唯一约束兜底并发修订。
- 报告行始终保存当前生效值与 current_version_no，季度统计只读取生效版本，可稳定重算。
"""

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError, OperationalError

from .. import models
from ..enums import (
    ProjectStatus,
    FollowUpStatus,
    FollowUpPriority,
    FollowUpSource,
    AccountingScope,
)


UTILIZATION_THRESHOLD_PCT = 100.0

CROSS_UPWARD = "upward"
CROSS_DOWNWARD = "downward"

ACTION_CLOSED = "closed_open_follow_ups"
ACTION_CREATED = "created_follow_up"
ACTION_EXISTING_OPEN = "existing_open_follow_up"
ACTION_NONE = "none"


class RevisionError(ValueError):
    """修订入参语义错误（400）。"""


class PeriodSealedError(Exception):
    """月份已封账，拒绝更改（423）。"""

    def __init__(self, message: str, boundary: Dict[str, Any]):
        super().__init__(message)
        self.boundary = boundary


class RevisionConflictError(Exception):
    """并发修订或幂等键冲突（409）。"""


def period_index(year: int, month: int) -> int:
    return year * 12 + (month - 1)


def quarter_range(year: int, quarter: int) -> Tuple[int, int, int, int]:
    start_month = (quarter - 1) * 3 + 1
    start_year = year
    end_index = period_index(start_year, start_month) + 2
    end_year, end_month = divmod(end_index, 12)
    return start_year, start_month, end_year, end_month + 1


def _round2(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 2)


def _get_promised_monthly_capacity(project: models.Project) -> float:
    if project.promised_monthly_capacity_tonnes:
        return project.promised_monthly_capacity_tonnes
    if project.expected_annual_capacity_tonnes:
        return project.expected_annual_capacity_tonnes / 12.0
    return 0.0


def _determine_priority(gap_pct: float) -> FollowUpPriority:
    if gap_pct >= 50:
        return FollowUpPriority.URGENT
    elif gap_pct >= 30:
        return FollowUpPriority.HIGH
    elif gap_pct >= 15:
        return FollowUpPriority.MEDIUM
    return FollowUpPriority.LOW


# ---------------------------------------------------------------------------
# 封账边界
# ---------------------------------------------------------------------------


def get_boundary(db: Session) -> Dict[str, Any]:
    periods = (
        db.query(models.AccountingPeriod)
        .order_by(
            models.AccountingPeriod.closed_through_year,
            models.AccountingPeriod.closed_through_month,
        )
        .all()
    )
    period_dicts = [
        {
            "scope": p.scope,
            "year": p.year,
            "quarter": p.quarter,
            "closed_through_year": p.closed_through_year,
            "closed_through_month": p.closed_through_month,
        }
        for p in periods
    ]
    if not periods:
        return {
            "closed_through_year": None,
            "closed_through_month": None,
            "closed_through_label": None,
            "periods": period_dicts,
        }
    latest = max(periods, key=lambda p: period_index(p.closed_through_year, p.closed_through_month))
    return {
        "closed_through_year": latest.closed_through_year,
        "closed_through_month": latest.closed_through_month,
        "closed_through_label": (
            f"{latest.closed_through_year}年{latest.closed_through_month}月"
        ),
        "periods": period_dicts,
    }


def ensure_period_open(db: Session, year: int, month: int) -> Dict[str, Any]:
    """封账月份直接拒绝更改。"""
    boundary = get_boundary(db)
    ct_year = boundary["closed_through_year"]
    if ct_year is not None:
        if period_index(year, month) <= period_index(
            ct_year, boundary["closed_through_month"]
        ):
            raise PeriodSealedError(
                f"{year}年{month}月已封账（封账边界：{boundary['closed_through_label']}），"
                "不可登记、修订或删除",
                boundary,
            )
    return boundary


def close_quarter(
    db: Session,
    year: int,
    quarter: int,
    closed_by: str,
    reason: Optional[str] = None,
    scope: AccountingScope = AccountingScope.QUARTER,
):
    _, _, end_year, end_month = quarter_range(year, quarter)
    existing = (
        db.query(models.AccountingPeriod)
        .filter(
            models.AccountingPeriod.scope == scope,
            models.AccountingPeriod.year == year,
            models.AccountingPeriod.quarter == quarter,
        )
        .first()
    )
    if existing:
        raise RevisionConflictError(
            f"{year}年第{quarter}季度（{scope.value}）已封账，请勿重复操作"
        )
    period = models.AccountingPeriod(
        scope=scope,
        year=year,
        quarter=quarter,
        closed_through_year=end_year,
        closed_through_month=end_month,
        closed_by=closed_by,
        reason=reason,
    )
    db.add(period)
    db.commit()
    db.refresh(period)
    return period


def reopen_quarter(
    db: Session,
    year: int,
    quarter: int,
    reopened_by: str,
    reason: Optional[str] = None,
    scope: AccountingScope = AccountingScope.QUARTER,
):
    period = (
        db.query(models.AccountingPeriod)
        .filter(
            models.AccountingPeriod.scope == scope,
            models.AccountingPeriod.year == year,
            models.AccountingPeriod.quarter == quarter,
        )
        .first()
    )
    if not period:
        return None
    # 只允许解除当前最末端的封账，避免边界中间出现空洞
    boundary = get_boundary(db)
    if (
        period.closed_through_year,
        period.closed_through_month,
    ) != (
        boundary["closed_through_year"],
        boundary["closed_through_month"],
    ):
        raise RevisionConflictError(
            "只能解除封账边界末端的账期，请先解除之后封账的季度"
        )
    db.delete(period)
    db.commit()
    return {"reopened_by": reopened_by, "reason": reason}


# ---------------------------------------------------------------------------
# 初次登记（生成 v1 版本记录）
# ---------------------------------------------------------------------------


def _snapshot_from_report(report: models.MonthlyCapacityReport) -> Dict[str, Any]:
    return {
        "actual_output_tonnes": report.actual_output_tonnes,
        "capacity_utilization_rate": report.capacity_utilization_rate,
        "employee_count": report.employee_count,
        "local_material_procurement_10k": report.local_material_procurement_10k,
        "remarks": report.remarks,
        "reported_by": report.reported_by,
    }


def record_initial_revision(
    db: Session,
    report: models.MonthlyCapacityReport,
    follow_up: Optional[models.CapacityFollowUp],
) -> models.CapacityReportRevision:
    snapshot = _snapshot_from_report(report)
    revision = models.CapacityReportRevision(
        report_id=report.id,
        project_id=report.project_id,
        revision_no=1,
        revised_by=report.reported_by or "系统",
        reason="初次登记",
        to_actual_output_tonnes=snapshot["actual_output_tonnes"],
        to_capacity_utilization_rate=snapshot["capacity_utilization_rate"],
        to_employee_count=snapshot["employee_count"],
        to_local_material_procurement_10k=snapshot["local_material_procurement_10k"],
        to_remarks=snapshot["remarks"],
        to_reported_by=snapshot["reported_by"],
        follow_up_action=ACTION_CREATED if follow_up is not None else ACTION_NONE,
    )
    db.add(revision)
    db.flush()
    if follow_up is not None:
        follow_up.revision_id = revision.id
    return revision


# ---------------------------------------------------------------------------
# 受控修订
# ---------------------------------------------------------------------------

_EDITABLE_FIELDS = (
    "actual_output_tonnes",
    "capacity_utilization_rate",
    "employee_count",
    "local_material_procurement_10k",
    "remarks",
    "reported_by",
)


def _threshold_direction(
    before_rate: Optional[float], after_rate: Optional[float]
) -> Optional[str]:
    if before_rate is None or after_rate is None:
        return None
    before_ok = before_rate >= UTILIZATION_THRESHOLD_PCT
    after_ok = after_rate >= UTILIZATION_THRESHOLD_PCT
    if before_ok == after_ok:
        return None
    return CROSS_UPWARD if after_ok else CROSS_DOWNWARD


def _apply_follow_up_sync(
    db: Session,
    project: models.Project,
    report: models.MonthlyCapacityReport,
    revision: models.CapacityReportRevision,
    promised: float,
    after_tonnes: float,
    direction: Optional[str],
) -> Dict[str, Any]:
    changes: List[Dict[str, Any]] = []
    closed_ids: List[int] = []
    created_id: Optional[int] = None
    action = ACTION_NONE

    open_follow_ups = (
        db.query(models.CapacityFollowUp)
        .filter(
            models.CapacityFollowUp.report_id == report.id,
            models.CapacityFollowUp.status.in_(
                [FollowUpStatus.PENDING, FollowUpStatus.IN_PROGRESS]
            ),
        )
        .all()
    )

    if direction == CROSS_UPWARD:
        for fu in open_follow_ups:
            status_before = fu.status
            fu.status = FollowUpStatus.CLOSED
            fu.closed_by_revision_id = revision.id
            fu.resolution = (
                f"修订版本 v{revision.revision_no} 后达产率回升至阈值"
                f"（{UTILIZATION_THRESHOLD_PCT:.0f}%）以上，事项自动关闭。"
                f"修订原因：{revision.reason}"
            )
            closed_ids.append(fu.id)
            changes.append(
                {
                    "follow_up_id": fu.id,
                    "action": "closed",
                    "title": fu.title,
                    "status_before": status_before,
                    "status_after": FollowUpStatus.CLOSED,
                }
            )
        action = ACTION_CLOSED if closed_ids else ACTION_NONE

    elif direction == CROSS_DOWNWARD:
        gap_pct = _round2(((promised - after_tonnes) / promised) * 100) if promised > 0 else None
        if open_follow_ups:
            # 已有未关闭事项（如手工挂接）时不重复建单，仅在描述中补充修订信息
            for fu in open_follow_ups:
                fu.description = (fu.description or "") + (
                    f"\n[修订 v{revision.revision_no}] 达产率回落至阈值以下，"
                    f"当前缺口 {gap_pct:.2f}%。修订原因：{revision.reason}"
                )
            action = ACTION_EXISTING_OPEN
        else:
            fu = models.CapacityFollowUp(
                project_id=report.project_id,
                report_id=report.id,
                title=f"{report.report_year}年{report.report_month}月产能修订后未达标",
                description=(
                    f"修订版本 v{revision.revision_no} 后实际产量 {after_tonnes:.2f} 吨，"
                    f"承诺月产能 {promised:.2f} 吨，缺口 {gap_pct:.2f}%。\n"
                    f"修订原因：{revision.reason}"
                ),
                status=FollowUpStatus.PENDING,
                priority=_determine_priority(gap_pct or 0.0),
                gap_percentage=gap_pct,
                responsible_person=project.project_leader,
                source=FollowUpSource.REVISION,
                revision_id=revision.id,
            )
            db.add(fu)
            db.flush()
            created_id = fu.id
            changes.append(
                {
                    "follow_up_id": fu.id,
                    "action": "created",
                    "title": fu.title,
                    "status_before": FollowUpStatus.PENDING,
                    "status_after": FollowUpStatus.PENDING,
                }
            )
            action = ACTION_CREATED

    revision.follow_up_action = action
    return {
        "follow_up_action": action,
        "follow_up_changes": changes,
        "closed_follow_ups": closed_ids,
        "created_follow_up_id": created_id,
    }


def _load_report_graph(db: Session, report_id: int):
    return (
        db.query(models.MonthlyCapacityReport)
        .options(
            joinedload(models.MonthlyCapacityReport.project),
            joinedload(models.MonthlyCapacityReport.revisions),
        )
        .filter(models.MonthlyCapacityReport.id == report_id)
        .first()
    )


def _build_result(
    report: models.MonthlyCapacityReport,
    revision: models.CapacityReportRevision,
    boundary: Dict[str, Any],
    previous_version_no: int,
    utilization_before: Optional[float],
    sync_result: Optional[Dict[str, Any]] = None,
    idempotent_replay: bool = False,
) -> Dict[str, Any]:
    sync_result = sync_result or {}
    return {
        "report": report,
        "revision": revision,
        "idempotent_replay": idempotent_replay,
        "previous_version_no": previous_version_no,
        "threshold_crossed": revision.threshold_crossed,
        "utilization_before": utilization_before,
        "utilization_after": revision.to_capacity_utilization_rate,
        "follow_up_action": revision.follow_up_action,
        "follow_up_changes": sync_result.get("follow_up_changes", []),
        "closed_follow_ups": sync_result.get("closed_follow_ups", []),
        "created_follow_up_id": sync_result.get("created_follow_up_id"),
        "accounting_boundary": boundary,
    }


def _replay_result(
    db: Session, report: models.MonthlyCapacityReport, revision: models.CapacityReportRevision
) -> Dict[str, Any]:
    boundary = get_boundary(db)
    changes: List[Dict[str, Any]] = []
    closed = (
        db.query(models.CapacityFollowUp)
        .filter(models.CapacityFollowUp.closed_by_revision_id == revision.id)
        .all()
    )
    for fu in closed:
        changes.append(
            {
                "follow_up_id": fu.id,
                "action": "closed",
                "title": fu.title,
                "status_before": FollowUpStatus.CLOSED,
                "status_after": FollowUpStatus.CLOSED,
            }
        )
    created = (
        db.query(models.CapacityFollowUp)
        .filter(
            models.CapacityFollowUp.revision_id == revision.id,
            models.CapacityFollowUp.source == FollowUpSource.REVISION,
        )
        .first()
    )
    if created is not None:
        changes.append(
            {
                "follow_up_id": created.id,
                "action": "created",
                "title": created.title,
                "status_before": created.status,
                "status_after": created.status,
            }
        )
    before_rate = revision.from_capacity_utilization_rate
    return {
        "report": report,
        "revision": revision,
        "idempotent_replay": True,
        "previous_version_no": revision.revision_no - 1,
        "threshold_crossed": revision.threshold_crossed,
        "utilization_before": before_rate,
        "utilization_after": revision.to_capacity_utilization_rate,
        "follow_up_action": revision.follow_up_action,
        "follow_up_changes": changes,
        "closed_follow_ups": [fu.id for fu in closed],
        "created_follow_up_id": created.id if created else None,
        "accounting_boundary": boundary,
    }


def create_revision(
    db: Session, report_id: int, payload: Any
) -> Dict[str, Any]:
    report = _load_report_graph(db, report_id)
    if not report:
        return None
    project = report.project
    if not project or project.status != ProjectStatus.COMMISSIONED:
        raise RevisionError("仅已投产项目的产能登记可修订")

    key = (payload.idempotency_key or "").strip() or None

    # 幂等：相同键的重复提交直接返回首次结果，不产生第二次影响
    if key:
        existing_revision = (
            db.query(models.CapacityReportRevision)
            .filter(models.CapacityReportRevision.idempotency_key == key)
            .first()
        )
        if existing_revision is not None:
            if existing_revision.report_id != report.id:
                raise RevisionConflictError("幂等键已用于其他产能记录的修订")
            return _replay_result(db, report, existing_revision)

    # 封账月份拒绝更改
    boundary = ensure_period_open(db, report.report_year, report.report_month)

    incoming = payload.model_dump(exclude_unset=True)
    incoming.pop("reason", None)
    incoming.pop("revised_by", None)
    incoming.pop("idempotency_key", None)

    current_snapshot = _snapshot_from_report(report)
    promised = _get_promised_monthly_capacity(project)
    effective = dict(current_snapshot)
    for field in _EDITABLE_FIELDS:
        if field in incoming and incoming[field] is not None:
            effective[field] = incoming[field]

    # 达产率：本次显式给出则尊重入参；本次改了产量则按新产量重算；
    # 历史率值缺失时补算；其余情况保留生效版本率值
    rate_explicit = incoming.get("capacity_utilization_rate") is not None
    tonnes_revised = "actual_output_tonnes" in incoming
    if (
        not rate_explicit
        and (tonnes_revised or current_snapshot["capacity_utilization_rate"] is None)
        and promised > 0
    ):
        effective["capacity_utilization_rate"] = _round2(
            (effective["actual_output_tonnes"] / promised) * 100
        )

    if all(effective[f] == current_snapshot[f] for f in _EDITABLE_FIELDS):
        raise RevisionError("修订内容与当前生效版本完全一致，无需生成新版本")

    utilization_before = current_snapshot["capacity_utilization_rate"]
    if utilization_before is None and promised > 0:
        utilization_before = _round2(
            (current_snapshot["actual_output_tonnes"] / promised) * 100
        )
    direction = _threshold_direction(
        utilization_before, effective["capacity_utilization_rate"]
    )

    previous_version_no = report.current_version_no
    previous_revision = max(report.revisions, key=lambda r: r.revision_no, default=None)
    revision = models.CapacityReportRevision(
        report_id=report.id,
        project_id=report.project_id,
        revision_no=previous_version_no + 1,
        revised_by=payload.revised_by,
        reason=payload.reason,
        idempotency_key=key,
        from_actual_output_tonnes=current_snapshot["actual_output_tonnes"],
        from_capacity_utilization_rate=utilization_before,
        from_employee_count=current_snapshot["employee_count"],
        from_local_material_procurement_10k=current_snapshot[
            "local_material_procurement_10k"
        ],
        from_remarks=current_snapshot["remarks"],
        from_reported_by=current_snapshot["reported_by"],
        to_actual_output_tonnes=effective["actual_output_tonnes"],
        to_capacity_utilization_rate=effective["capacity_utilization_rate"],
        to_employee_count=effective["employee_count"],
        to_local_material_procurement_10k=effective[
            "local_material_procurement_10k"
        ],
        to_remarks=effective["remarks"],
        to_reported_by=effective["reported_by"],
        threshold_crossed=direction,
        supersedes_revision_id=previous_revision.id if previous_revision else None,
    )
    try:
        db.add(revision)

        # 生效版本落到报告行上（季度统计始终读取该行）
        for field in _EDITABLE_FIELDS:
            setattr(report, field, effective[field])
        report.current_version_no = previous_version_no + 1

        db.flush()
        sync_result = _apply_follow_up_sync(
            db,
            project,
            report,
            revision,
            promised,
            effective["actual_output_tonnes"],
            direction,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        # 并发下唯一键碰撞：幂等键或版本号已被其他事务占用
        if key:
            winner = (
                db.query(models.CapacityReportRevision)
                .filter(models.CapacityReportRevision.idempotency_key == key)
                .first()
            )
            if winner is not None:
                report = _load_report_graph(db, report_id)
                return _replay_result(db, report, winner)
        raise RevisionConflictError("该记录正被其他修订处理，请基于最新版本重试")
    except OperationalError as exc:  # SQLite 写锁等并发冲突
        db.rollback()
        if "locked" in str(exc.orig).lower() or "busy" in str(exc.orig).lower():
            raise RevisionConflictError("修订并发冲突，请稍后重试")
        raise

    db.refresh(report)
    db.refresh(revision)
    return _build_result(
        report,
        revision,
        boundary,
        previous_version_no,
        utilization_before,
        sync_result,
    )


def list_revisions(db: Session, report_id: int):
    return (
        db.query(models.CapacityReportRevision)
        .filter(models.CapacityReportRevision.report_id == report_id)
        .order_by(models.CapacityReportRevision.revision_no)
        .all()
    )


def get_revision(db: Session, revision_id: int):
    return (
        db.query(models.CapacityReportRevision)
        .filter(models.CapacityReportRevision.id == revision_id)
        .first()
    )


# ---------------------------------------------------------------------------
# 季度统计（从生效版本稳定重算）
# ---------------------------------------------------------------------------


def get_quarterly_statistics(db: Session, year: int, quarter: int) -> Dict[str, Any]:
    start_year, start_month, end_year, end_month = quarter_range(year, quarter)
    start_index = period_index(start_year, start_month)
    end_index = period_index(end_year, end_month)
    boundary = get_boundary(db)

    projects = (
        db.query(models.Project)
        .options(
            joinedload(models.Project.park),
            joinedload(models.Project.capacity_reports).joinedload(
                models.MonthlyCapacityReport.revisions
            ),
        )
        .filter(models.Project.status == ProjectStatus.COMMISSIONED)
        .all()
    )

    items: List[Dict[str, Any]] = []
    total_promised = 0.0
    total_actual = 0.0
    total_procurement = 0.0

    for project in projects:
        promised = _get_promised_monthly_capacity(project)
        in_range = [
            r
            for r in (project.capacity_reports or [])
            if start_index
            <= period_index(r.report_year, r.report_month)
            <= end_index
        ]
        if not in_range:
            continue
        in_range.sort(key=lambda r: period_index(r.report_year, r.report_month))

        months = []
        project_actual = 0.0
        project_procurement = 0.0
        rates: List[float] = []
        for r in in_range:
            rate = r.capacity_utilization_rate
            if rate is None and promised > 0:
                rate = _round2((r.actual_output_tonnes / promised) * 100)
            latest_revision = max(r.revisions, key=lambda x: x.revision_no, default=None)
            months.append(
                {
                    "period": f"{r.report_year}-{r.report_month:02d}",
                    "year": r.report_year,
                    "month": r.report_month,
                    "actual_output_tonnes": _round2(r.actual_output_tonnes),
                    "utilization_rate": _round2(rate or 0.0),
                    "local_material_procurement_10k": _round2(
                        r.local_material_procurement_10k or 0.0
                    ),
                    "version_no": r.current_version_no,
                    "revised_at": latest_revision.created_at
                    if latest_revision and latest_revision.revision_no > 1
                    else None,
                }
            )
            project_actual += r.actual_output_tonnes or 0.0
            project_procurement += r.local_material_procurement_10k or 0.0
            if rate is not None:
                rates.append(rate)

        items.append(
            {
                "project_id": project.id,
                "project_name": project.name,
                "promised_monthly_capacity_tonnes": _round2(promised),
                "months": months,
                "total_actual_output_tonnes": _round2(project_actual),
                "total_local_procurement_10k": _round2(project_procurement),
                "average_utilization_rate": _round2(sum(rates) / len(rates))
                if rates
                else 0.0,
            }
        )
        total_promised += promised * len(in_range)
        total_actual += project_actual
        total_procurement += project_procurement

    sealed = boundary["closed_through_year"] is not None and (
        period_index(
            boundary["closed_through_year"], boundary["closed_through_month"]
        )
        >= end_index
    )

    return {
        "year": year,
        "quarter": quarter,
        "start_year": start_year,
        "start_month": start_month,
        "end_year": end_year,
        "end_month": end_month,
        "accounting_boundary": boundary,
        "sealed": sealed,
        "items": items,
        "total_promised_capacity_tonnes": _round2(total_promised),
        "total_actual_output_tonnes": _round2(total_actual),
        "overall_utilization_rate": _round2(
            (total_actual / total_promised) * 100
        )
        if total_promised > 0
        else 0.0,
        "total_local_procurement_10k": _round2(total_procurement),
    }
