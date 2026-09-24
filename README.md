# 水果深加工招商台账后端服务

记录合作主体、园区、项目、洽谈、立项、里程碑和投产后的产能兑现情况，为招商团队提供可追溯的业务接口。

## 运行约定

服务端代码位于 `app` 目录，默认使用项目目录中的 SQLite 文件保存业务数据。环境变量可以覆盖数据库位置和接口前缀，临时配置不应提交到仓库。

## 测试

在项目根目录执行：

```bash
python3 -m unittest discover -s tests -v
```

`tests/test_capacity_revisions.py` 覆盖受控修订流程：跨年月份封账边界、达产率 100% 阈值两侧的跟进联动（含已有手工跟进）、幂等重复提交、并发修订与季度统计按生效版本重算。

## 月度产能受控修订

- **封账**：`POST /api/v1/capacity/accounting/close-quarter` 按季度封账；封账边界及之前的月份（按 `年*12+月` 比较，支持跨年）拒绝登记、修订、删除。`GET .../accounting/boundary` 查询当前边界。
- **修订**：`POST /api/v1/capacity/reports/{id}/revisions`，必填修订原因与操作者，生成不可变版本记录（`GET .../revisions` 查询版本链，v1 为初次登记）。直接 `PUT` 覆盖已停用。
- **阈值联动**：修订后达产率跨越 100% 阈值时，向上关闭该月报下仍未关闭的跟进事项（自动与手工挂接均包含），向下自动生成"修订联动"事项；已有未关闭手工事项时只追加说明、不重复建单。
- **幂等与并发**：相同 `idempotency_key` 重复提交返回首次结果（`idempotent_replay=true`），不产生第二次影响；版本号与幂等键均有唯一约束兜底并发。
- **季度统计**：`GET /api/v1/capacity/statistics/quarterly?year=&quarter=` 只读取报告生效版本（`current_version_no`），封账前后结果稳定一致。

## 编译检查

在项目根目录执行：

```bash
python3 -m compileall -q app tests
```

## 启动服务

准备依赖后可执行 `uvicorn app.main:app --host 127.0.0.1 --port 8000`，根路径返回服务状态，接口文档位于 `/docs`。
