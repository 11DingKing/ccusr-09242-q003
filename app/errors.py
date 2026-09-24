from enum import IntEnum


class HTTPStatus(IntEnum):
    OK = 200
    CREATED = 201
    BAD_REQUEST = 400
    NOT_FOUND = 404
    CONFLICT = 409
    LOCKED = 423


ERROR_NOT_FOUND = {
    "project": "项目不存在",
    "park": "园区不存在",
    "entity": "主体不存在",
    "intent": "合作意向不存在",
    "milestone": "里程碑不存在",
    "approval": "尚未立项",
    "capacity_report": "产能登记不存在",
    "follow_up": "跟进事项不存在",
    "capacity_curve": "产能曲线数据不存在",
}

ERROR_DUPLICATE = {
    "project_name": "项目名称已存在",
    "project_code": "项目编号已存在",
    "approval": "该项目已立项，不可重复操作",
    "capacity_report": "该月份的产能报告已存在，请勿重复登记",
}

ERROR_STATUS = {
    "only_attracting_can_submit_intent": "当前项目状态为「{status}」，只有「招商中」的项目才能提交合作意向",
    "only_negotiating_can_approve": "当前项目状态为「{status}」，只有「洽谈中」的项目才能立项",
    "only_established_or_uc_can_add_milestone": "当前项目状态为「{status}」，只有「已立项」或「建设中」的项目才能新增里程碑",
    "only_commissioned_can_report_capacity": "仅已投产项目可登记月度产能",
}

ERROR_OPERATION_FAILED = {
    "approval": "立项失败",
    "capacity_report": "登记失败",
}


def fmt(msg: str, **kwargs) -> str:
    return msg.format(**kwargs)
