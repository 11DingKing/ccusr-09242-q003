from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, date
from typing import Optional, List

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
)


class EntityCapabilityBase(BaseModel):
    category: ProcessingCategory
    annual_capacity_tonnes: float
    capacity_unit: Optional[str] = "吨/年"
    production_lines: Optional[int] = None
    key_products: Optional[str] = None
    certifications: Optional[str] = None


class EntityCapabilityCreate(EntityCapabilityBase):
    pass


class EntityCapability(EntityCapabilityBase):
    id: int
    entity_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EntityBase(BaseModel):
    name: str
    region: Region
    country_or_province: str
    city: Optional[str] = None
    contact_person: str
    contact_phone: str
    contact_email: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None
    registered_capital: Optional[float] = None
    established_year: Optional[int] = None


class EntityCreate(EntityBase):
    capabilities: List[EntityCapabilityCreate] = Field(default_factory=list)


class EntityUpdate(BaseModel):
    name: Optional[str] = None
    region: Optional[Region] = None
    country_or_province: Optional[str] = None
    city: Optional[str] = None
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None
    registered_capital: Optional[float] = None
    established_year: Optional[int] = None


class Entity(EntityBase):
    id: int
    created_at: datetime
    updated_at: datetime
    capabilities: List[EntityCapability] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class EntityListItem(BaseModel):
    id: int
    name: str
    region: Region
    country_or_province: str
    city: Optional[str] = None
    contact_person: str
    registered_capital: Optional[float] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IndustrialParkBase(BaseModel):
    name: str
    park_type: ParkType
    city: str
    district: Optional[str] = None
    total_area_km2: Optional[float] = None
    developed_area_km2: Optional[float] = None
    pillar_industries: Optional[str] = None
    preferential_policies: Optional[str] = None
    infrastructure: Optional[str] = None
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None


class IndustrialParkCreate(IndustrialParkBase):
    pass


class IndustrialParkUpdate(BaseModel):
    name: Optional[str] = None
    park_type: Optional[ParkType] = None
    city: Optional[str] = None
    district: Optional[str] = None
    total_area_km2: Optional[float] = None
    developed_area_km2: Optional[float] = None
    pillar_industries: Optional[str] = None
    preferential_policies: Optional[str] = None
    infrastructure: Optional[str] = None
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None


class IndustrialPark(IndustrialParkBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectCategoryBase(BaseModel):
    category: ProcessingCategory
    proportion: Optional[float] = None
    description: Optional[str] = None


class ProjectCategoryCreate(ProjectCategoryBase):
    pass


class ProjectCategory(ProjectCategoryBase):
    id: int
    project_id: int

    model_config = ConfigDict(from_attributes=True)


class ProjectBase(BaseModel):
    name: str
    project_code: Optional[str] = None
    status: ProjectStatus = ProjectStatus.ATTRACTING_INVESTMENT
    investment_direction: str
    planned_investment_10k: float
    expected_annual_capacity_tonnes: Optional[float] = None
    planned_land_area_mu: Optional[float] = None
    expected_output_value_10k: Optional[float] = None
    expected_jobs: Optional[int] = None
    construction_cycle_months: Optional[int] = None
    commissioned_date: Optional[date] = None
    promised_monthly_capacity_tonnes: Optional[float] = None
    expected_local_procurement_pct: Optional[float] = None
    park_id: int
    initiator_id: int
    background: Optional[str] = None
    market_analysis: Optional[str] = None
    cooperation_modes: Optional[str] = None
    support_requirements: Optional[str] = None
    responsible_department: Optional[str] = None
    project_leader: Optional[str] = None
    leader_phone: Optional[str] = None
    publish_date: Optional[date] = None


class ProjectCreate(ProjectBase):
    categories: List[ProjectCategoryCreate] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    project_code: Optional[str] = None
    investment_direction: Optional[str] = None
    planned_investment_10k: Optional[float] = None
    expected_annual_capacity_tonnes: Optional[float] = None
    planned_land_area_mu: Optional[float] = None
    expected_output_value_10k: Optional[float] = None
    expected_jobs: Optional[int] = None
    construction_cycle_months: Optional[int] = None
    commissioned_date: Optional[date] = None
    promised_monthly_capacity_tonnes: Optional[float] = None
    expected_local_procurement_pct: Optional[float] = None
    park_id: Optional[int] = None
    background: Optional[str] = None
    market_analysis: Optional[str] = None
    cooperation_modes: Optional[str] = None
    support_requirements: Optional[str] = None
    responsible_department: Optional[str] = None
    project_leader: Optional[str] = None
    leader_phone: Optional[str] = None
    publish_date: Optional[date] = None


class ProjectListItem(BaseModel):
    id: int
    name: str
    project_code: Optional[str] = None
    status: ProjectStatus
    planned_investment_10k: float
    expected_annual_capacity_tonnes: Optional[float] = None
    park_id: int
    park_name: Optional[str] = None
    initiator_name: Optional[str] = None
    publish_date: Optional[date] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class Project(ProjectBase):
    id: int
    created_at: datetime
    updated_at: datetime
    categories: List[ProjectCategory] = Field(default_factory=list)
    park: Optional[IndustrialPark] = None
    initiator: Optional[EntityListItem] = None
    capacity_reports: List["MonthlyCapacityReport"] = Field(default_factory=list)
    capacity_follow_ups: List["CapacityFollowUp"] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class StatusChangeRequest(BaseModel):
    to_status: ProjectStatus
    operator: Optional[str] = None
    reason: str = Field(..., min_length=1, description="状态变更原因，退回时必填")
    remarks: Optional[str] = None


class ProjectStatusLogBase(BaseModel):
    from_status: Optional[ProjectStatus] = None
    to_status: ProjectStatus
    operator: Optional[str] = None
    reason: Optional[str] = None
    remarks: Optional[str] = None


class ProjectStatusLog(ProjectStatusLogBase):
    id: int
    project_id: int
    changed_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NegotiationRecordBase(BaseModel):
    round: int
    title: str
    held_at: datetime
    location: Optional[str] = None
    host: Optional[str] = None
    participants: Optional[str] = None
    key_topics: str
    consensus: Optional[str] = None
    disagreements: Optional[str] = None
    next_steps: Optional[str] = None
    next_meeting_date: Optional[date] = None
    minutes_author: Optional[str] = None


class NegotiationRecordCreate(NegotiationRecordBase):
    pass


class NegotiationRecord(NegotiationRecordBase):
    id: int
    intent_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CooperationIntentBase(BaseModel):
    project_id: int
    submitter_id: int
    counterparty_id: Optional[int] = None
    cooperation_mode: Optional[str] = None
    proposed_investment_10k: Optional[float] = None
    proposed_capacity_tonnes: Optional[float] = None
    cooperation_content: str
    expected_timeline: Optional[str] = None
    requirements: Optional[str] = None
    submitter_comments: Optional[str] = None


class CooperationIntentCreate(CooperationIntentBase):
    pass


class CooperationIntentUpdate(BaseModel):
    status: Optional[IntentStatus] = None
    cooperation_mode: Optional[str] = None
    proposed_investment_10k: Optional[float] = None
    proposed_capacity_tonnes: Optional[float] = None
    cooperation_content: Optional[str] = None
    expected_timeline: Optional[str] = None
    requirements: Optional[str] = None
    submitter_comments: Optional[str] = None
    reviewer: Optional[str] = None
    review_comments: Optional[str] = None


class CooperationIntentListItem(BaseModel):
    id: int
    project_id: int
    project_name: Optional[str] = None
    submitter_id: int
    submitter_name: Optional[str] = None
    counterparty_id: Optional[int] = None
    counterparty_name: Optional[str] = None
    status: IntentStatus
    cooperation_mode: Optional[str] = None
    proposed_investment_10k: Optional[float] = None
    submitted_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CooperationIntent(CooperationIntentBase):
    id: int
    status: IntentStatus
    reviewer: Optional[str] = None
    review_comments: Optional[str] = None
    submitted_at: datetime
    reviewed_at: Optional[datetime] = None
    updated_at: datetime
    project: Optional[ProjectListItem] = None
    submitter: Optional[EntityListItem] = None
    counterparty: Optional[EntityListItem] = None
    negotiations: List[NegotiationRecord] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ProjectApprovalBase(BaseModel):
    approval_number: str
    approval_date: date
    approving_authority: str
    agreed_investment_10k: float
    agreed_capacity_tonnes: Optional[float] = None
    agreed_land_area_mu: Optional[float] = None
    construction_start_deadline: Optional[date] = None
    completion_deadline: Optional[date] = None
    main_content: Optional[str] = None
    approval_conditions: Optional[str] = None
    approved_by: Optional[str] = None


class ProjectApprovalCreate(ProjectApprovalBase):
    project_id: int


class ProjectApproval(ProjectApprovalBase):
    id: int
    project_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectApprovalRequest(BaseModel):
    approval_number: str
    approval_date: date
    approving_authority: str
    agreed_investment_10k: float
    agreed_capacity_tonnes: Optional[float] = None
    agreed_land_area_mu: Optional[float] = None
    construction_start_deadline: Optional[date] = None
    completion_deadline: Optional[date] = None
    main_content: Optional[str] = None
    approval_conditions: Optional[str] = None
    approved_by: Optional[str] = None
    operator: Optional[str] = None
    milestones: List["MilestoneCreate"] = Field(default_factory=list)


class ProjectMilestoneBase(BaseModel):
    sequence: int
    milestone_type: MilestoneType
    name: str
    status: MilestoneStatus = MilestoneStatus.NOT_STARTED
    planned_date: date
    actual_date: Optional[date] = None
    description: Optional[str] = None
    responsible_person: Optional[str] = None
    completion_rate: float = 0.0
    remarks: Optional[str] = None


class MilestoneCreate(ProjectMilestoneBase):
    pass


class ProjectMilestoneCreate(ProjectMilestoneBase):
    project_id: int


class ProjectMilestoneUpdate(BaseModel):
    status: Optional[MilestoneStatus] = None
    actual_date: Optional[date] = None
    completion_rate: Optional[float] = None
    description: Optional[str] = None
    responsible_person: Optional[str] = None
    remarks: Optional[str] = None


class ProjectMilestone(ProjectMilestoneBase):
    id: int
    project_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ParkStatistics(BaseModel):
    park_id: int
    park_name: str
    park_type: ParkType
    total_projects: int
    established_projects: int
    under_construction_projects: int
    commissioned_projects: int
    attracting_projects: int
    negotiating_projects: int
    total_agreed_investment_10k: float
    total_planned_investment_10k: float
    commission_rate: float


class CategoryStatistics(BaseModel):
    category: ProcessingCategory
    project_count: int
    total_investment_10k: float
    total_capacity_tonnes: float


class OverallStatistics(BaseModel):
    total_projects: int
    attracting_investment_count: int
    negotiating_count: int
    established_count: int
    under_construction_count: int
    commissioned_count: int
    total_planned_investment_10k: float
    total_agreed_investment_10k: float
    total_expected_output_value_10k: float
    total_expected_jobs: int
    commission_rate: float
    parks: List[ParkStatistics]
    categories: List[CategoryStatistics]


class MonthlyCapacityReportBase(BaseModel):
    report_year: int
    report_month: int
    actual_output_tonnes: float = 0.0
    capacity_utilization_rate: Optional[float] = None
    employee_count: Optional[int] = 0
    local_material_procurement_10k: Optional[float] = 0.0
    remarks: Optional[str] = None
    reported_by: Optional[str] = None


class MonthlyCapacityReportCreate(MonthlyCapacityReportBase):
    project_id: int


class MonthlyCapacityReportUpdate(BaseModel):
    actual_output_tonnes: Optional[float] = None
    capacity_utilization_rate: Optional[float] = None
    employee_count: Optional[int] = None
    local_material_procurement_10k: Optional[float] = None
    remarks: Optional[str] = None
    reported_by: Optional[str] = None


class MonthlyCapacityReport(MonthlyCapacityReportBase):
    id: int
    project_id: int
    current_version: int = 1
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CapacityFollowUpBase(BaseModel):
    title: str
    description: Optional[str] = None
    status: FollowUpStatus = FollowUpStatus.PENDING
    priority: FollowUpPriority = FollowUpPriority.MEDIUM
    gap_percentage: Optional[float] = None
    responsible_person: Optional[str] = None
    deadline: Optional[date] = None
    resolution: Optional[str] = None


class CapacityFollowUpCreate(CapacityFollowUpBase):
    project_id: int
    report_id: Optional[int] = None


class CapacityFollowUpUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[FollowUpStatus] = None
    priority: Optional[FollowUpPriority] = None
    gap_percentage: Optional[float] = None
    responsible_person: Optional[str] = None
    deadline: Optional[date] = None
    resolution: Optional[str] = None


class CapacityFollowUp(CapacityFollowUpBase):
    id: int
    project_id: int
    report_id: Optional[int] = None
    source: str = "AUTO"
    auto_generated: bool = True
    last_revision_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CapacityRevisionBase(BaseModel):
    actual_output_tonnes: Optional[float] = None
    capacity_utilization_rate: Optional[float] = None
    employee_count: Optional[int] = None
    local_material_procurement_10k: Optional[float] = None
    remarks: Optional[str] = None
    reported_by: Optional[str] = None


class CapacityRevisionCreate(CapacityRevisionBase):
    reason: str = Field(..., min_length=1, description="修订原因，必填以便追溯")
    operator: Optional[str] = Field(None, description="操作者（修订发起人）")
    expected_version: Optional[int] = Field(
        None, description="乐观锁：提交时所基于的版本号，防止并发覆盖"
    )
    idempotency_key: Optional[str] = Field(
        None, description="幂等键：相同键重复提交不产生第二次影响"
    )


class CapacityRevision(BaseModel):
    id: int
    report_id: int
    project_id: int
    version_no: int
    actual_output_tonnes: float
    capacity_utilization_rate: Optional[float] = None
    employee_count: Optional[int] = None
    local_material_procurement_10k: Optional[float] = None
    remarks: Optional[str] = None
    reported_by: Optional[str] = None
    change_type: str
    reason: Optional[str] = None
    operator: Optional[str] = None
    idempotency_key: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ClosedBoundary(BaseModel):
    year: int
    month: int


class CapacityFollowUpChange(BaseModel):
    action: str
    follow_up_id: int
    title: str
    status: str
    priority: str
    gap_percentage: Optional[float] = None


class CapacityRevisionResponse(BaseModel):
    message: str
    idempotent: bool = False
    effects_applied: bool = True
    closed_boundary: Optional[ClosedBoundary] = None
    report_id: int
    project_id: int
    report_year: int
    report_month: int
    current_version: int
    previous_version_no: Optional[int] = None
    new_version_no: int
    relationship: str
    threshold_crossed: bool = False
    old_version: Optional[CapacityRevision] = None
    new_version: CapacityRevision
    follow_up_changes: List[CapacityFollowUpChange] = Field(default_factory=list)


class CapacityCloseMonthRequest(BaseModel):
    close_year: int = Field(..., ge=2000, le=2100)
    close_month: int = Field(..., ge=1, le=12)
    reason: Optional[str] = None
    operator: Optional[str] = None


class CapacityCloseMonthResponse(BaseModel):
    message: str
    closed_boundary: ClosedBoundary
    closed_through: ClosedBoundary
    reason: Optional[str] = None
    operator: Optional[str] = None


class CapacityCurvePoint(BaseModel):
    period: str
    year: int
    month: int
    promised_capacity_tonnes: float
    actual_output_tonnes: float
    utilization_rate: float


class CapacityCurveResponse(BaseModel):
    project_id: int
    project_name: str
    promised_monthly_capacity_tonnes: Optional[float]
    curve: List[CapacityCurvePoint]


class ParkCapacityStatistics(BaseModel):
    park_id: int
    park_name: str
    park_type: ParkType
    commissioned_projects: int
    reporting_projects: int
    total_promised_capacity_tonnes: float
    total_actual_output_tonnes: float
    average_utilization_rate: float
    total_local_procurement_10k: float


class CategoryCapacityStatistics(BaseModel):
    category: ProcessingCategory
    project_count: int
    total_promised_capacity_tonnes: float
    total_actual_output_tonnes: float
    average_utilization_rate: float
    total_local_procurement_10k: float


class CapacityOverviewStatistics(BaseModel):
    total_commissioned_projects: int
    total_reporting_projects: int
    total_promised_capacity_tonnes: float
    total_actual_output_tonnes: float
    overall_utilization_rate: float
    total_local_procurement_10k: float
    parks: List[ParkCapacityStatistics]
    categories: List[CategoryCapacityStatistics]


Project.model_rebuild()
