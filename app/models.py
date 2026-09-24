from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    Text,
    Date,
    UniqueConstraint,
    Enum as SAEnum,
)
from sqlalchemy.orm import relationship
from datetime import datetime

from .database import Base
from .enums import (
    Region,
    ProcessingCategory,
    ProjectStatus,
    ParkType,
    IntentStatus,
    MilestoneStatus,
    MilestoneType,
    FollowUpStatus,
    FollowUpPriority,
    FollowUpSource,
    AccountingScope,
)


class Entity(Base):
    __tablename__ = "entities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(256), unique=True, nullable=False, index=True)
    region = Column(SAEnum(Region), nullable=False, index=True)
    country_or_province = Column(String(128), nullable=False)
    city = Column(String(128))
    contact_person = Column(String(64), nullable=False)
    contact_phone = Column(String(32), nullable=False)
    contact_email = Column(String(128))
    address = Column(String(512))
    description = Column(Text)
    registered_capital = Column(Float)
    established_year = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    capabilities = relationship(
        "EntityCapability",
        back_populates="entity",
        cascade="all, delete-orphan",
    )
    submitted_intents = relationship(
        "CooperationIntent",
        foreign_keys="CooperationIntent.submitter_id",
        back_populates="submitter",
    )
    counterparty_intents = relationship(
        "CooperationIntent",
        foreign_keys="CooperationIntent.counterparty_id",
        back_populates="counterparty",
    )


class EntityCapability(Base):
    __tablename__ = "entity_capabilities"

    id = Column(Integer, primary_key=True, index=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    category = Column(SAEnum(ProcessingCategory), nullable=False, index=True)
    annual_capacity_tonnes = Column(Float, nullable=False)
    capacity_unit = Column(String(32), default="吨/年")
    production_lines = Column(Integer)
    key_products = Column(String(512))
    certifications = Column(String(512))
    created_at = Column(DateTime, default=datetime.utcnow)

    entity = relationship("Entity", back_populates="capabilities")


class IndustrialPark(Base):
    __tablename__ = "industrial_parks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(256), unique=True, nullable=False, index=True)
    park_type = Column(SAEnum(ParkType), nullable=False, index=True)
    city = Column(String(128), nullable=False)
    district = Column(String(128))
    total_area_km2 = Column(Float)
    developed_area_km2 = Column(Float)
    pillar_industries = Column(String(512))
    preferential_policies = Column(Text)
    infrastructure = Column(Text)
    contact_person = Column(String(64))
    contact_phone = Column(String(32))
    address = Column(String(512))
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    projects = relationship("Project", back_populates="park")


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(256), unique=True, nullable=False, index=True)
    project_code = Column(String(64), unique=True, index=True)
    status = Column(
        SAEnum(ProjectStatus),
        nullable=False,
        default=ProjectStatus.ATTRACTING_INVESTMENT,
        index=True,
    )
    investment_direction = Column(Text, nullable=False)
    planned_investment_10k = Column(Float, nullable=False)
    expected_annual_capacity_tonnes = Column(Float)
    planned_land_area_mu = Column(Float)
    expected_output_value_10k = Column(Float)
    expected_jobs = Column(Integer)
    construction_cycle_months = Column(Integer)
    commissioned_date = Column(Date)
    promised_monthly_capacity_tonnes = Column(Float)
    expected_local_procurement_pct = Column(Float)
    park_id = Column(Integer, ForeignKey("industrial_parks.id"), nullable=False)
    initiator_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    background = Column(Text)
    market_analysis = Column(Text)
    cooperation_modes = Column(String(256))
    support_requirements = Column(Text)
    responsible_department = Column(String(128))
    project_leader = Column(String(64))
    leader_phone = Column(String(32))
    publish_date = Column(Date)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    park = relationship("IndustrialPark", back_populates="projects")
    initiator = relationship("Entity", foreign_keys=[initiator_id])
    categories = relationship(
        "ProjectCategory",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    intents = relationship(
        "CooperationIntent",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    approval = relationship(
        "ProjectApproval",
        back_populates="project",
        uselist=False,
        cascade="all, delete-orphan",
    )
    milestones = relationship(
        "ProjectMilestone",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectMilestone.sequence",
    )
    status_logs = relationship(
        "ProjectStatusLog",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectStatusLog.changed_at.desc()",
    )
    capacity_reports = relationship(
        "MonthlyCapacityReport",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="MonthlyCapacityReport.report_year, MonthlyCapacityReport.report_month",
    )
    capacity_follow_ups = relationship(
        "CapacityFollowUp",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="CapacityFollowUp.created_at.desc()",
    )


class ProjectCategory(Base):
    __tablename__ = "project_categories"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    category = Column(SAEnum(ProcessingCategory), nullable=False, index=True)
    proportion = Column(Float)
    description = Column(String(256))

    project = relationship("Project", back_populates="categories")


class CooperationIntent(Base):
    __tablename__ = "cooperation_intents"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    submitter_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    counterparty_id = Column(Integer, ForeignKey("entities.id"))
    status = Column(
        SAEnum(IntentStatus),
        nullable=False,
        default=IntentStatus.SUBMITTED,
        index=True,
    )
    cooperation_mode = Column(String(128))
    proposed_investment_10k = Column(Float)
    proposed_capacity_tonnes = Column(Float)
    cooperation_content = Column(Text, nullable=False)
    expected_timeline = Column(String(256))
    requirements = Column(Text)
    submitter_comments = Column(Text)
    reviewer = Column(String(64))
    review_comments = Column(Text)
    submitted_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="intents")
    submitter = relationship(
        "Entity",
        foreign_keys=[submitter_id],
        back_populates="submitted_intents",
    )
    counterparty = relationship(
        "Entity",
        foreign_keys=[counterparty_id],
        back_populates="counterparty_intents",
    )
    negotiations = relationship(
        "NegotiationRecord",
        back_populates="intent",
        cascade="all, delete-orphan",
        order_by="NegotiationRecord.round, NegotiationRecord.held_at",
    )


class NegotiationRecord(Base):
    __tablename__ = "negotiation_records"

    id = Column(Integer, primary_key=True, index=True)
    intent_id = Column(Integer, ForeignKey("cooperation_intents.id"), nullable=False)
    round = Column(Integer, nullable=False)
    title = Column(String(256), nullable=False)
    held_at = Column(DateTime, nullable=False)
    location = Column(String(256))
    host = Column(String(128))
    participants = Column(String(512))
    key_topics = Column(Text, nullable=False)
    consensus = Column(Text)
    disagreements = Column(Text)
    next_steps = Column(Text)
    next_meeting_date = Column(Date)
    minutes_author = Column(String(64))
    created_at = Column(DateTime, default=datetime.utcnow)

    intent = relationship("CooperationIntent", back_populates="negotiations")


class ProjectApproval(Base):
    __tablename__ = "project_approvals"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer,
        ForeignKey("projects.id"),
        nullable=False,
        unique=True,
    )
    approval_number = Column(String(128), unique=True, nullable=False)
    approval_date = Column(Date, nullable=False)
    approving_authority = Column(String(256), nullable=False)
    agreed_investment_10k = Column(Float, nullable=False)
    agreed_capacity_tonnes = Column(Float)
    agreed_land_area_mu = Column(Float)
    construction_start_deadline = Column(Date)
    completion_deadline = Column(Date)
    main_content = Column(Text)
    approval_conditions = Column(Text)
    approved_by = Column(String(64))
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="approval")


class ProjectMilestone(Base):
    __tablename__ = "project_milestones"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    sequence = Column(Integer, nullable=False)
    milestone_type = Column(SAEnum(MilestoneType), nullable=False)
    name = Column(String(256), nullable=False)
    status = Column(
        SAEnum(MilestoneStatus),
        nullable=False,
        default=MilestoneStatus.NOT_STARTED,
        index=True,
    )
    planned_date = Column(Date, nullable=False)
    actual_date = Column(Date)
    description = Column(Text)
    responsible_person = Column(String(64))
    completion_rate = Column(Float, default=0.0)
    remarks = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="milestones")


class ProjectStatusLog(Base):
    __tablename__ = "project_status_logs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    from_status = Column(SAEnum(ProjectStatus))
    to_status = Column(SAEnum(ProjectStatus), nullable=False)
    changed_at = Column(DateTime, default=datetime.utcnow)
    operator = Column(String(64))
    reason = Column(String(512))
    remarks = Column(Text)

    project = relationship("Project", back_populates="status_logs")


class MonthlyCapacityReport(Base):
    __tablename__ = "monthly_capacity_reports"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    report_year = Column(Integer, nullable=False, index=True)
    report_month = Column(Integer, nullable=False, index=True)
    actual_output_tonnes = Column(Float, nullable=False, default=0.0)
    capacity_utilization_rate = Column(Float)
    employee_count = Column(Integer, default=0)
    local_material_procurement_10k = Column(Float, default=0.0)
    remarks = Column(Text)
    reported_by = Column(String(64))
    # 当前生效版本号：1 为初次登记，受控修订成功后递增；统计与曲线均以生效版本为准
    current_version_no = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="capacity_reports")
    revisions = relationship(
        "CapacityReportRevision",
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="CapacityReportRevision.revision_no",
    )

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "report_year",
            "report_month",
            name="uq_monthly_capacity_project_period",
        ),
    )


class CapacityReportRevision(Base):
    """月度产能的不可变版本记录。version_no=1 为初次登记，>=2 为受控修订。"""

    __tablename__ = "capacity_report_revisions"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(
        Integer,
        ForeignKey("monthly_capacity_reports.id"),
        nullable=False,
        index=True,
    )
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    revision_no = Column(Integer, nullable=False)
    revised_by = Column(String(64), nullable=False)
    reason = Column(Text, nullable=False)
    idempotency_key = Column(String(128))
    # 版本快照旧值（v1 时为 None）
    from_actual_output_tonnes = Column(Float)
    from_capacity_utilization_rate = Column(Float)
    from_employee_count = Column(Integer)
    from_local_material_procurement_10k = Column(Float)
    from_remarks = Column(Text)
    from_reported_by = Column(String(64))
    # 版本快照新值
    to_actual_output_tonnes = Column(Float, nullable=False)
    to_capacity_utilization_rate = Column(Float)
    to_employee_count = Column(Integer)
    to_local_material_procurement_10k = Column(Float)
    to_remarks = Column(Text)
    to_reported_by = Column(String(64))
    threshold_crossed = Column(String(32))
    follow_up_action = Column(String(32))
    supersedes_revision_id = Column(
        Integer,
        ForeignKey("capacity_report_revisions.id"),
    )
    created_at = Column(DateTime, default=datetime.utcnow)

    report = relationship("MonthlyCapacityReport", back_populates="revisions", foreign_keys=[report_id])
    supersedes = relationship(
        "CapacityReportRevision",
        remote_side="CapacityReportRevision.id",
        foreign_keys=[supersedes_revision_id],
    )

    __table_args__ = (
        UniqueConstraint(
            "report_id",
            "revision_no",
            name="uq_capacity_revision_report_no",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_capacity_revision_idempotency_key",
        ),
    )


class AccountingPeriod(Base):
    """封账账期：scope=季度封账 绑定季度指标，scope=全局封账 作为封账边界。"""

    __tablename__ = "accounting_periods"

    id = Column(Integer, primary_key=True, index=True)
    scope = Column(SAEnum(AccountingScope), nullable=False)
    year = Column(Integer, nullable=False, index=True)
    quarter = Column(Integer)
    # 账期覆盖的最后一个月份（year*12+month），小于等于该月份均视为已封账
    closed_through_year = Column(Integer, nullable=False)
    closed_through_month = Column(Integer, nullable=False)
    closed_by = Column(String(64), nullable=False)
    reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "scope",
            "year",
            "quarter",
            name="uq_accounting_period_scope_quarter",
        ),
    )


class CapacityFollowUp(Base):
    __tablename__ = "capacity_follow_ups"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    report_id = Column(Integer, ForeignKey("monthly_capacity_reports.id"), index=True)
    title = Column(String(256), nullable=False)
    description = Column(Text)
    status = Column(SAEnum(FollowUpStatus), nullable=False, default=FollowUpStatus.PENDING, index=True)
    priority = Column(SAEnum(FollowUpPriority), nullable=False, default=FollowUpPriority.MEDIUM)
    source = Column(SAEnum(FollowUpSource), nullable=False, default=FollowUpSource.MANUAL)
    gap_percentage = Column(Float)
    responsible_person = Column(String(64))
    deadline = Column(Date)
    resolution = Column(Text)
    revision_id = Column(Integer, ForeignKey("capacity_report_revisions.id"))
    closed_by_revision_id = Column(
        Integer, ForeignKey("capacity_report_revisions.id")
    )
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="capacity_follow_ups")
    report = relationship("MonthlyCapacityReport")
