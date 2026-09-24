from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List

from ..database import get_db
from .. import crud, schemas
from ..enums import FollowUpStatus, FollowUpPriority
from ..errors import (
    HTTPStatus,
    ERROR_NOT_FOUND,
    ERROR_OPERATION_FAILED,
)
from ..services.revisions import (
    MonthClosedError,
    VersionConflictError,
    ConcurrentRevisionError,
    RevisionNotFound,
)

router = APIRouter(prefix="/capacity", tags=["投产后产能兑现跟踪"])


def _closed_month_response(exc: MonthClosedError):
    return HTTPException(
        status_code=HTTPStatus.CONFLICT,
        detail={
            "message": str(exc),
            "code": "CAPACITY_MONTH_CLOSED",
            "closed_boundary": {
                "year": exc.boundary.close_year,
                "month": exc.boundary.close_month,
            },
            "report_year": exc.year,
            "report_month": exc.month,
        },
    )


@router.post(
    "/reports",
    response_model=schemas.MonthlyCapacityReport,
    summary="登记月度产能（自动计算达产率，低于承诺时自动生成跟进事项，写入第1版）",
)
def create_capacity_report(
    report_in: schemas.MonthlyCapacityReportCreate,
    db: Session = Depends(get_db),
):
    project = crud.get_project(db, project_id=report_in.project_id)
    if not project:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=ERROR_NOT_FOUND["project"],
        )
    try:
        result = crud.create_capacity_report(db=db, obj_in=report_in)
    except MonthClosedError as e:
        raise _closed_month_response(e)
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=str(e))
    if not result:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=ERROR_OPERATION_FAILED["capacity_report"],
        )
    return result


@router.get(
    "/reports",
    response_model=List[schemas.MonthlyCapacityReport],
    summary="查询月度产能登记列表",
)
def list_capacity_reports(
    project_id: Optional[int] = Query(None, description="项目ID筛选"),
    year: Optional[int] = Query(None, description="年度筛选"),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return crud.list_capacity_reports(
        db=db, project_id=project_id, year=year, skip=skip, limit=limit
    )


@router.get(
    "/reports/{report_id}",
    response_model=schemas.MonthlyCapacityReport,
    summary="查询单条月度产能登记详情",
)
def get_capacity_report(report_id: int, db: Session = Depends(get_db)):
    report = crud.get_capacity_report(db, report_id=report_id)
    if not report:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=ERROR_NOT_FOUND["capacity_report"],
        )
    return report


@router.put(
    "/reports/{report_id}",
    response_model=schemas.MonthlyCapacityReport,
    summary="更新月度产能登记（封账月份拒绝；可修订月份内部同样生成版本记录）",
)
def update_capacity_report(
    report_id: int,
    report_in: schemas.MonthlyCapacityReportUpdate,
    db: Session = Depends(get_db),
):
    try:
        updated = crud.update_capacity_report(db, report_id=report_id, obj_in=report_in)
    except MonthClosedError as e:
        raise _closed_month_response(e)
    if not updated:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=ERROR_NOT_FOUND["capacity_report"],
        )
    return updated


@router.delete("/reports/{report_id}", summary="删除月度产能登记（封账月份拒绝）")
def delete_capacity_report(report_id: int, db: Session = Depends(get_db)):
    try:
        deleted = crud.delete_capacity_report(db, report_id=report_id)
    except MonthClosedError as e:
        raise _closed_month_response(e)
    if not deleted:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=ERROR_NOT_FOUND["capacity_report"],
        )
    return {"message": "删除成功", "report_id": report_id}


@router.post(
    "/reports/{report_id}/revisions",
    response_model=schemas.CapacityRevisionResponse,
    status_code=HTTPStatus.CREATED,
    summary="受控修订：生成带原因/操作者的版本，跨阈值时联动未关闭跟进（支持幂等与乐观锁）",
)
def create_capacity_revision(
    report_id: int,
    revision_in: schemas.CapacityRevisionCreate,
    db: Session = Depends(get_db),
):
    try:
        return crud.revise_capacity_report(db, report_id=report_id, obj_in=revision_in)
    except RevisionNotFound:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=ERROR_NOT_FOUND["capacity_report"],
        )
    except MonthClosedError as e:
        raise _closed_month_response(e)
    except VersionConflictError as e:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail={
                "message": str(e),
                "code": "CAPACITY_VERSION_CONFLICT",
                "current_version": e.current,
                "expected_version": e.expected,
            },
        )
    except ConcurrentRevisionError as e:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail={
                "message": str(e),
                "code": "CAPACITY_CONCURRENT_REVISION",
            },
        )


@router.get(
    "/reports/{report_id}/revisions",
    response_model=List[schemas.CapacityRevision],
    summary="查询月度产能报告的全部版本（含初始登记与历次修订）",
)
def list_capacity_revisions(report_id: int, db: Session = Depends(get_db)):
    try:
        return crud.list_capacity_revisions(db, report_id=report_id)
    except RevisionNotFound:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=ERROR_NOT_FOUND["capacity_report"],
        )


@router.get(
    "/closed-boundary",
    response_model=Optional[schemas.ClosedBoundary],
    summary="查询当前封账边界（该年月及之前拒绝更改；未封账时返回 null）",
)
def get_closed_boundary(db: Session = Depends(get_db)):
    boundary = crud.get_capacity_closed_boundary(db)
    if not boundary:
        return None
    return {"year": boundary.close_year, "month": boundary.close_month}


@router.post(
    "/closed-boundary",
    response_model=schemas.CapacityCloseMonthResponse,
    summary="设置封账边界（截至指定年月含，保护已结算季度指标）",
)
def set_closed_boundary(
    body: schemas.CapacityCloseMonthRequest,
    db: Session = Depends(get_db),
):
    record = crud.close_capacity_months(db, body)
    boundary = {"year": record.close_year, "month": record.close_month}
    return {
        "message": (
            f"已封账至 {record.close_year}年{record.close_month}月，"
            "该边界及之前月份的产能数据拒绝更改"
        ),
        "closed_boundary": boundary,
        "closed_through": boundary,
        "reason": record.reason,
        "operator": record.operator,
    }


@router.post(
    "/follow-ups",
    response_model=schemas.CapacityFollowUp,
    summary="手动创建产能跟进事项",
)
def create_follow_up(
    fu_in: schemas.CapacityFollowUpCreate,
    db: Session = Depends(get_db),
):
    project = crud.get_project(db, project_id=fu_in.project_id)
    if not project:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=ERROR_NOT_FOUND["project"],
        )
    return crud.create_follow_up(db=db, obj_in=fu_in)


@router.get(
    "/follow-ups",
    response_model=List[schemas.CapacityFollowUp],
    summary="查询产能跟进事项列表",
)
def list_follow_ups(
    project_id: Optional[int] = Query(None, description="项目ID筛选"),
    status: Optional[FollowUpStatus] = Query(None, description="跟进状态筛选"),
    priority: Optional[FollowUpPriority] = Query(None, description="优先级筛选"),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return crud.list_follow_ups(
        db=db,
        project_id=project_id,
        status=status,
        priority=priority,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/follow-ups/{follow_up_id}",
    response_model=schemas.CapacityFollowUp,
    summary="查询单条跟进事项详情",
)
def get_follow_up(follow_up_id: int, db: Session = Depends(get_db)):
    fu = crud.get_follow_up(db, follow_up_id=follow_up_id)
    if not fu:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=ERROR_NOT_FOUND["follow_up"],
        )
    return fu


@router.put(
    "/follow-ups/{follow_up_id}",
    response_model=schemas.CapacityFollowUp,
    summary="更新跟进事项（状态、责任人、解决方案等）",
)
def update_follow_up(
    follow_up_id: int,
    fu_in: schemas.CapacityFollowUpUpdate,
    db: Session = Depends(get_db),
):
    updated = crud.update_follow_up(db, follow_up_id=follow_up_id, obj_in=fu_in)
    if not updated:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=ERROR_NOT_FOUND["follow_up"],
        )
    return updated


@router.delete("/follow-ups/{follow_up_id}", summary="删除跟进事项")
def delete_follow_up(follow_up_id: int, db: Session = Depends(get_db)):
    deleted = crud.delete_follow_up(db, follow_up_id=follow_up_id)
    if not deleted:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=ERROR_NOT_FOUND["follow_up"],
        )
    return {"message": "删除成功", "follow_up_id": follow_up_id}


@router.get(
    "/projects/{project_id}/curve",
    response_model=schemas.CapacityCurveResponse,
    summary="企业详情：承诺产能 vs 实际产能曲线数据",
)
def get_project_capacity_curve(project_id: int, db: Session = Depends(get_db)):
    project = crud.get_project(db, project_id=project_id)
    if not project:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=ERROR_NOT_FOUND["project"],
        )
    curve = crud.get_project_capacity_curve(db, project_id=project_id)
    if not curve:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=ERROR_NOT_FOUND["capacity_curve"],
        )
    return curve


@router.get(
    "/statistics/overview",
    response_model=schemas.CapacityOverviewStatistics,
    summary="园区统计看板：达产率与本地采购汇总（全局+园区+品类）",
)
def get_capacity_overview_statistics(db: Session = Depends(get_db)):
    return crud.get_capacity_overview_statistics(db)


@router.get(
    "/statistics/parks",
    response_model=List[schemas.ParkCapacityStatistics],
    summary="园区维度达产率与采购额统计",
)
def get_parks_capacity_statistics(db: Session = Depends(get_db)):
    data = crud.get_capacity_overview_statistics(db)
    return data["parks"]


@router.get(
    "/statistics/categories",
    response_model=List[schemas.CategoryCapacityStatistics],
    summary="项目类型维度达产率与采购额统计",
)
def get_categories_capacity_statistics(db: Session = Depends(get_db)):
    data = crud.get_capacity_overview_statistics(db)
    return data["categories"]
