from enum import Enum


class Region(str, Enum):
    ASSOCIATION_SOUTH_EAST_ASIAN_NATIONS = "东盟方"
    GUANGXI = "广西方"


class ProcessingCategory(str, Enum):
    COCONUT = "椰子深加工"
    FRUIT_JUICE = "果汁加工"
    TROPICAL_FRUIT = "热带水果加工"
    DURIAN = "榴莲加工"
    MANGO = "芒果加工"
    DRAGON_FRUIT = "火龙果加工"
    JACKFRUIT = "菠萝蜜加工"
    MANGOSTEEN = "山竹加工"
    CANNED_FRUIT = "水果罐头"
    DRIED_FRUIT = "果干加工"
    JAM = "果酱加工"
    FROZEN_FRUIT = "速冻水果"


class ProjectStatus(str, Enum):
    ATTRACTING_INVESTMENT = "招商中"
    NEGOTIATING = "洽谈中"
    ESTABLISHED = "已立项"
    UNDER_CONSTRUCTION = "建设中"
    COMMISSIONED = "已投产"


class ParkType(str, Enum):
    BORDER_PORT = "沿边临港产业园"
    QINFANG_COLLABORATION = "钦防协作园"
    BORDER_ECONOMIC_COOPERATION = "边境经济合作区"
    FREE_TRADE = "自贸试验区"
    COMPREHENSIVE_BONDED = "综合保税区"
    KEY_INDUSTRIAL = "重点工业园区"


class IntentStatus(str, Enum):
    SUBMITTED = "已提交"
    REVIEWING = "评审中"
    IN_DISCUSSION = "洽谈中"
    ACCEPTED = "已采纳"
    REJECTED = "已拒绝"
    WITHDRAWN = "已撤回"


class MilestoneStatus(str, Enum):
    NOT_STARTED = "未启动"
    IN_PROGRESS = "进行中"
    COMPLETED = "已完成"
    DELAYED = "已延期"


class MilestoneType(str, Enum):
    FOUNDATION = "奠基开工"
    MAIN_STRUCTURE = "主体结构"
    EQUIPMENT_INSTALLATION = "设备安装"
    TRIAL_PRODUCTION = "试生产"
    OFFICIAL_PRODUCTION = "正式投产"


class FollowUpStatus(str, Enum):
    PENDING = "待跟进"
    IN_PROGRESS = "跟进中"
    RESOLVED = "已解决"
    CLOSED = "已关闭"


class FollowUpPriority(str, Enum):
    LOW = "低"
    MEDIUM = "中"
    HIGH = "高"
    URGENT = "紧急"


class FollowUpSource(str, Enum):
    AUTO = "自动生成"
    MANUAL = "手工创建"
    REVISION = "修订联动"


class AccountingScope(str, Enum):
    GLOBAL = "全局封账"
    QUARTER = "季度封账"
