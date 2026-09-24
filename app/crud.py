from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from datetime import datetime

from . import models, schemas
from .enums import (
    ProjectStatus,
    IntentStatus,
    MilestoneStatus,
    MilestoneType,
    FollowUpStatus,
    FollowUpPriority,
    FollowUpSource,
    ProcessingCategory,
)
from .services.status_flow import (
    validate_status_transition,
    transition_project_status,
    trigger_status_after_intent,
    trigger_status_after_approval,
    StatusTransitionError,
)
from .services.milestones import (
    process_milestone_update,
    build_default_milestones,
    persist_milestones,
    list_milestones_for_project,
    MilestoneStateError,
)
from .services.statistics import (
    get_overall_statistics as _svc_get_overall_statistics,
    get_capacity_overview_statistics as _svc_get_capacity_overview,
    get_project_capacity_curve_data as _svc_get_capacity_curve,
)
from .services import revisions as revision_service
from .services.revisions import (
    RevisionError,
    PeriodSealedError,
    RevisionConflictError,
)


def get_entity(db: Session, entity_id: int):
    return (
        db.query(models.Entity)
        .options(joinedload(models.Entity.capabilities))
        .filter(models.Entity.id == entity_id)
        .first()
    )


def get_entity_by_name(db: Session, name: str):
    return db.query(models.Entity).filter(models.Entity.name == name).first()


def list_entities(
    db: Session,
    region: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
):
    query = db.query(models.Entity)
    if region:
        query = query.filter(models.Entity.region == region)
    return query.offset(skip).limit(limit).all()


def create_entity(db: Session, obj_in: schemas.EntityCreate):
    capabilities_data = (
        [c.model_dump() for c in obj_in.capabilities]
        if getattr(obj_in, "capabilities", None)
        else []
    )
    entity_data = obj_in.model_dump(exclude={"capabilities"})
    db_entity = models.Entity(**entity_data)
    db.add(db_entity)
    db.flush()
    for cap_data in capabilities_data:
        db_cap = models.EntityCapability(entity_id=db_entity.id, **cap_data)
        db.add(db_cap)
    db.commit()
    db.refresh(db_entity)
    return get_entity(db, db_entity.id)


def update_entity(db: Session, entity_id: int, obj_in: schemas.EntityUpdate):
    db_entity = get_entity(db, entity_id)
    if not db_entity:
        return None
    update_data = obj_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_entity, field, value)
    db.commit()
    db.refresh(db_entity)
    return db_entity


def delete_entity(db: Session, entity_id: int):
    db_entity = get_entity(db, entity_id)
    if db_entity:
        db.delete(db_entity)
        db.commit()
    return db_entity


def add_entity_capability(
    db: Session, entity_id: int, cap_in: schemas.EntityCapabilityCreate
):
    db_cap = models.EntityCapability(entity_id=entity_id, **cap_in.model_dump())
    db.add(db_cap)
    db.commit()
    db.refresh(db_cap)
    return db_cap


def delete_entity_capability(db: Session, capability_id: int):
    db_cap = (
        db.query(models.EntityCapability)
        .filter(models.EntityCapability.id == capability_id)
        .first()
    )
    if db_cap:
        db.delete(db_cap)
        db.commit()
    return db_cap


def get_park(db: Session, park_id: int):
    return (
        db.query(models.IndustrialPark)
        .filter(models.IndustrialPark.id == park_id)
        .first()
    )


def list_parks(
    db: Session,
    park_type: Optional[str] = None,
    city: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
):
    query = db.query(models.IndustrialPark)
    if park_type:
        query = query.filter(models.IndustrialPark.park_type == park_type)
    if city:
        query = query.filter(models.IndustrialPark.city == city)
    return query.offset(skip).limit(limit).all()


def create_park(db: Session, obj_in: schemas.IndustrialParkCreate):
    db_park = models.IndustrialPark(**obj_in.model_dump())
    db.add(db_park)
    db.commit()
    db.refresh(db_park)
    return db_park


def update_park(db: Session, park_id: int, obj_in: schemas.IndustrialParkUpdate):
    db_park = get_park(db, park_id)
    if not db_park:
        return None
    update_data = obj_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_park, field, value)
    db.commit()
    db.refresh(db_park)
    return db_park


def delete_park(db: Session, park_id: int):
    db_park = get_park(db, park_id)
    if db_park:
        db.delete(db_park)
        db.commit()
    return db_park


def get_project(db: Session, project_id: int):
    return (
        db.query(models.Project)
        .options(
            joinedload(models.Project.categories),
            joinedload(models.Project.park),
            joinedload(models.Project.initiator),
            joinedload(models.Project.capacity_reports),
            joinedload(models.Project.capacity_follow_ups),
        )
        .filter(models.Project.id == project_id)
        .first()
    )


def list_projects(
    db: Session,
    status: Optional[ProjectStatus] = None,
    park_id: Optional[int] = None,
    initiator_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
):
    query = db.query(models.Project)
    if status:
        query = query.filter(models.Project.status == status)
    if park_id:
        query = query.filter(models.Project.park_id == park_id)
    if initiator_id:
        query = query.filter(models.Project.initiator_id == initiator_id)
    return query.order_by(models.Project.created_at.desc()).offset(skip).limit(limit).all()


def create_project(db: Session, obj_in: schemas.ProjectCreate):
    categories_data = [c.model_dump() for c in obj_in.categories]
    project_data = obj_in.model_dump(exclude={"categories"})
    db_project = models.Project(**project_data)
    db.add(db_project)
    db.flush()
    for cat_data in categories_data:
        db_cat = models.ProjectCategory(project_id=db_project.id, **cat_data)
        db.add(db_cat)
    db.commit()
    db.refresh(db_project)
    return get_project(db, db_project.id)


def update_project(db: Session, project_id: int, obj_in: schemas.ProjectUpdate):
    db_project = get_project(db, project_id)
    if not db_project:
        return None
    update_data = obj_in.model_dump(exclude_unset=True)
    update_data.pop("status", None)
    for field, value in update_data.items():
        setattr(db_project, field, value)
    db.commit()
    db.refresh(db_project)
    return db_project


def delete_project(db: Session, project_id: int):
    db_project = get_project(db, project_id)
    if db_project:
        db.delete(db_project)
        db.commit()
    return db_project


def change_project_status(
    db: Session,
    project_id: int,
    to_status: ProjectStatus,
    operator: Optional[str] = None,
    reason: Optional[str] = None,
    remarks: Optional[str] = None,
):
    db_project = get_project(db, project_id)
    if not db_project:
        return None
    transition_project_status(
        db,
        project=db_project,
        to_status=to_status,
        operator=operator,
        reason=reason,
        remarks=remarks,
        skip_validation=False,
    )
    db.commit()
    db.refresh(db_project)
    return db_project


def get_project_status_logs(db: Session, project_id: int):
    return (
        db.query(models.ProjectStatusLog)
        .filter(models.ProjectStatusLog.project_id == project_id)
        .order_by(models.ProjectStatusLog.changed_at.desc())
        .all()
    )


def get_intent(db: Session, intent_id: int):
    return (
        db.query(models.CooperationIntent)
        .options(
            joinedload(models.CooperationIntent.project),
            joinedload(models.CooperationIntent.submitter),
            joinedload(models.CooperationIntent.counterparty),
            joinedload(models.CooperationIntent.negotiations),
        )
        .filter(models.CooperationIntent.id == intent_id)
        .first()
    )


def list_intents(
    db: Session,
    project_id: Optional[int] = None,
    submitter_id: Optional[int] = None,
    status: Optional[IntentStatus] = None,
    skip: int = 0,
    limit: int = 100,
):
    query = db.query(models.CooperationIntent)
    if project_id:
        query = query.filter(models.CooperationIntent.project_id == project_id)
    if submitter_id:
        query = query.filter(models.CooperationIntent.submitter_id == submitter_id)
    if status:
        query = query.filter(models.CooperationIntent.status == status)
    return query.order_by(models.CooperationIntent.submitted_at.desc()).offset(skip).limit(limit).all()


def create_intent(db: Session, obj_in: schemas.CooperationIntentCreate):
    db_intent = models.CooperationIntent(**obj_in.model_dump())
    db.add(db_intent)
    project = (
        db.query(models.Project)
        .filter(models.Project.id == obj_in.project_id)
        .first()
    )
    if project:
        trigger_status_after_intent(db, project)
    db.commit()
    db.refresh(db_intent)
    return get_intent(db, db_intent.id)


def update_intent(db: Session, intent_id: int, obj_in: schemas.CooperationIntentUpdate):
    db_intent = get_intent(db, intent_id)
    if not db_intent:
        return None
    update_data = obj_in.model_dump(exclude_unset=True)
    if "status" in update_data and update_data["status"] != db_intent.status:
        if (
            update_data["status"] in [IntentStatus.REVIEWING, IntentStatus.IN_DISCUSSION]
            and db_intent.reviewed_at is None
        ):
            db_intent.reviewed_at = datetime.utcnow()
    for field, value in update_data.items():
        setattr(db_intent, field, value)
    db.commit()
    db.refresh(db_intent)
    return db_intent


def create_negotiation(
    db: Session, intent_id: int, obj_in: schemas.NegotiationRecordCreate
):
    db_neg = models.NegotiationRecord(intent_id=intent_id, **obj_in.model_dump())
    db.add(db_neg)
    intent = db.query(models.CooperationIntent).filter(models.CooperationIntent.id == intent_id).first()
    if intent and intent.status in [IntentStatus.SUBMITTED, IntentStatus.REVIEWING]:
        intent.status = IntentStatus.IN_DISCUSSION
        if intent.reviewed_at is None:
            intent.reviewed_at = datetime.utcnow()
    db.commit()
    db.refresh(db_neg)
    return db_neg


def list_negotiations(db: Session, intent_id: int):
    return (
        db.query(models.NegotiationRecord)
        .filter(models.NegotiationRecord.intent_id == intent_id)
        .order_by(models.NegotiationRecord.round, models.NegotiationRecord.held_at)
        .all()
    )


def approve_project(
    db: Session,
    project_id: int,
    approval_in: schemas.ProjectApprovalRequest,
):
    project = get_project(db, project_id)
    if not project:
        return None
    if project.approval:
        return None
    if project.status != ProjectStatus.NEGOTIATING:
        return None

    milestones_data = [m.model_dump() for m in approval_in.milestones]
    approval_data = approval_in.model_dump(
        exclude={"operator", "milestones"}
    )
    db_approval = models.ProjectApproval(project_id=project_id, **approval_data)
    db.add(db_approval)
    db.flush()

    if milestones_data:
        for m_data in milestones_data:
            db_milestone = models.ProjectMilestone(project_id=project_id, **m_data)
            db.add(db_milestone)
    else:
        default_milestones = build_default_milestones(approval_in.approval_date)
        persist_milestones(db, project_id, default_milestones)

    trigger_status_after_approval(
        db, project, approval_in.approval_number, operator=approval_in.operator
    )
    db.commit()
    db.refresh(project)
    return project


def get_project_approval(db: Session, project_id: int):
    return (
        db.query(models.ProjectApproval)
        .filter(models.ProjectApproval.project_id == project_id)
        .first()
    )


def get_milestone(db: Session, milestone_id: int):
    return (
        db.query(models.ProjectMilestone)
        .filter(models.ProjectMilestone.id == milestone_id)
        .first()
    )


def list_milestones(db: Session, project_id: int):
    return list_milestones_for_project(db, project_id)


def create_milestone(db: Session, obj_in: schemas.ProjectMilestoneCreate):
    db_m = models.ProjectMilestone(**obj_in.model_dump())
    db.add(db_m)
    db.commit()
    db.refresh(db_m)
    return db_m


def update_milestone(
    db: Session, milestone_id: int, obj_in: schemas.ProjectMilestoneUpdate
):
    db_m = get_milestone(db, milestone_id)
    if not db_m:
        return None
    return process_milestone_update(db, db_m, obj_in)


def get_overall_statistics(db: Session):
    return _svc_get_overall_statistics(db)


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
    else:
        return FollowUpPriority.LOW


def create_capacity_report(db: Session, obj_in: schemas.MonthlyCapacityReportCreate):
    project = get_project(db, project_id=obj_in.project_id)
    if not project:
        return None
    if project.status != ProjectStatus.COMMISSIONED:
        raise ValueError("仅已投产项目可登记月度产能")

    # 封账月份拒绝登记
    revision_service.ensure_period_open(db, obj_in.report_year, obj_in.report_month)

    existing = (
        db.query(models.MonthlyCapacityReport)
        .filter(
            models.MonthlyCapacityReport.project_id == obj_in.project_id,
            models.MonthlyCapacityReport.report_year == obj_in.report_year,
            models.MonthlyCapacityReport.report_month == obj_in.report_month,
        )
        .first()
    )
    if existing:
        raise ValueError("该月份的产能报告已存在，请勿重复登记")

    report_data = obj_in.model_dump()
    promised = _get_promised_monthly_capacity(project)

    if report_data.get("capacity_utilization_rate") is None and promised > 0:
        report_data["capacity_utilization_rate"] = round(
            (report_data["actual_output_tonnes"] / promised) * 100, 2
        )

    db_report = models.MonthlyCapacityReport(**report_data)
    db.add(db_report)
    db.flush()

    follow_up = None
    if promised > 0 and report_data["actual_output_tonnes"] < promised:
        gap_pct = round(
            ((promised - report_data["actual_output_tonnes"]) / promised) * 100, 2
        )
        priority = _determine_priority(gap_pct)
        follow_up = models.CapacityFollowUp(
            project_id=obj_in.project_id,
            report_id=db_report.id,
            title=f"{obj_in.report_year}年{obj_in.report_month}月产能未达标",
            description=(
                f"承诺月产能 {promised:.2f} 吨，实际产量 {report_data['actual_output_tonnes']:.2f} 吨，"
                f"缺口 {gap_pct:.2f}%。请跟进原因并推动产能爬坡。"
            ),
            status=FollowUpStatus.PENDING,
            priority=priority,
            gap_percentage=gap_pct,
            responsible_person=project.project_leader,
            source=FollowUpSource.AUTO,
        )
        db.add(follow_up)

    # v1 版本记录：初次登记本身也是版本链的起点
    revision_service.record_initial_revision(db, db_report, follow_up)

    db.commit()
    db.refresh(db_report)
    return db_report


def get_capacity_report(db: Session, report_id: int):
    return (
        db.query(models.MonthlyCapacityReport)
        .filter(models.MonthlyCapacityReport.id == report_id)
        .first()
    )


def list_capacity_reports(
    db: Session,
    project_id: Optional[int] = None,
    year: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
):
    query = db.query(models.MonthlyCapacityReport)
    if project_id:
        query = query.filter(models.MonthlyCapacityReport.project_id == project_id)
    if year:
        query = query.filter(models.MonthlyCapacityReport.report_year == year)
    return (
        query.order_by(
            models.MonthlyCapacityReport.report_year.desc(),
            models.MonthlyCapacityReport.report_month.desc(),
        )
        .offset(skip)
        .limit(limit)
        .all()
    )


def update_capacity_report(
    db: Session, report_id: int, obj_in: schemas.MonthlyCapacityReportUpdate
):
    # 受控修订流程上线后，月度产能不允许直接覆盖；更正必须走修订接口留痕
    raise RevisionError(
        "月度产能不允许直接覆盖，请使用受控修订接口并填写修订原因"
    )


def revise_capacity_report(
    db: Session, report_id: int, obj_in: schemas.CapacityReportRevisionCreate
):
    return revision_service.create_revision(db, report_id, obj_in)


def list_capacity_revisions(db: Session, report_id: int):
    return revision_service.list_revisions(db, report_id)


def get_capacity_revision(db: Session, revision_id: int):
    return revision_service.get_revision(db, revision_id)


def delete_capacity_report(db: Session, report_id: int):
    db_report = get_capacity_report(db, report_id)
    if db_report:
        # 封账月份拒绝删除
        revision_service.ensure_period_open(
            db, db_report.report_year, db_report.report_month
        )
        db.delete(db_report)
        db.commit()
    return db_report


def close_accounting_quarter(
    db: Session,
    year: int,
    quarter: int,
    closed_by: str,
    reason: Optional[str] = None,
    scope=revision_service.AccountingScope.QUARTER,
):
    return revision_service.close_quarter(
        db, year, quarter, closed_by, reason, scope
    )


def reopen_accounting_quarter(
    db: Session,
    year: int,
    quarter: int,
    reopened_by: str,
    reason: Optional[str] = None,
    scope=revision_service.AccountingScope.QUARTER,
):
    return revision_service.reopen_quarter(
        db, year, quarter, reopened_by, reason, scope
    )


def list_accounting_periods(db: Session):
    return (
        db.query(models.AccountingPeriod)
        .order_by(
            models.AccountingPeriod.closed_through_year.desc(),
            models.AccountingPeriod.closed_through_month.desc(),
        )
        .all()
    )


def get_accounting_boundary(db: Session):
    return revision_service.get_boundary(db)


def get_quarterly_capacity_statistics(db: Session, year: int, quarter: int):
    return revision_service.get_quarterly_statistics(db, year, quarter)


def get_follow_up(db: Session, follow_up_id: int):
    return (
        db.query(models.CapacityFollowUp)
        .filter(models.CapacityFollowUp.id == follow_up_id)
        .first()
    )


def list_follow_ups(
    db: Session,
    project_id: Optional[int] = None,
    status: Optional[FollowUpStatus] = None,
    priority: Optional[FollowUpPriority] = None,
    skip: int = 0,
    limit: int = 100,
):
    query = db.query(models.CapacityFollowUp)
    if project_id:
        query = query.filter(models.CapacityFollowUp.project_id == project_id)
    if status:
        query = query.filter(models.CapacityFollowUp.status == status)
    if priority:
        query = query.filter(models.CapacityFollowUp.priority == priority)
    return (
        query.order_by(models.CapacityFollowUp.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def create_follow_up(db: Session, obj_in: schemas.CapacityFollowUpCreate):
    project = get_project(db, project_id=obj_in.project_id)
    if not project:
        return None
    db_obj = models.CapacityFollowUp(**obj_in.model_dump())
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def update_follow_up(
    db: Session, follow_up_id: int, obj_in: schemas.CapacityFollowUpUpdate
):
    db_obj = get_follow_up(db, follow_up_id)
    if not db_obj:
        return None
    update_data = obj_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_obj, field, value)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def delete_follow_up(db: Session, follow_up_id: int):
    db_obj = get_follow_up(db, follow_up_id)
    if db_obj:
        db.delete(db_obj)
        db.commit()
    return db_obj


def get_project_capacity_curve(db: Session, project_id: int):
    project = get_project(db, project_id=project_id)
    if not project:
        return None
    return _svc_get_capacity_curve(project)


def get_capacity_overview_statistics(db: Session):
    return _svc_get_capacity_overview(db)
