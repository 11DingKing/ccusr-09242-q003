# 水果深加工招商台账后端服务

记录合作主体、园区、项目、洽谈、立项、里程碑和投产后的产能兑现情况，为招商团队提供可追溯的业务接口。

## 运行约定

服务端代码位于 `app` 目录，默认使用项目目录中的 SQLite 文件保存业务数据。环境变量可以覆盖数据库位置和接口前缀，临时配置不应提交到仓库。

## 测试

在项目根目录执行：

```bash
python3 -m unittest discover -s tests -v
```

## 产能受控修订

- `GET/POST /api/v1/capacity/closed-boundary`：查询/设置封账边界（年月，含当月）。边界及之前的月份拒绝新增、覆盖、删除与修订，响应中始终回传当前边界。
- `POST /api/v1/capacity/reports/{report_id}/revisions`：对可修订月份提交受控修订，必填 `reason`，可带 `operator`、`expected_version`（乐观锁）、`idempotency_key`（幂等）。响应包含封账边界、新旧版本号及取代关系、阈值是否跨越、跟进事项变更明细。
- `GET /api/v1/capacity/reports/{report_id}/revisions`：查看版本链（初始登记为第 1 版，之后逐版追加）。
- 达产率以承诺月产能 100% 为阈值：由未达标跨上达标线时，仍未关闭的**自动**跟进事项自动标记为已解决；反向跨越时补建自动跟进；手工跟进与已关闭事项不受影响。
- 相同 `idempotency_key` 重复提交只回放首次结果（`idempotent: true`，`effects_applied: false`），不产生第二版与第二次跟进调整。
- 报告主表始终保存生效版本，季度/总览统计与产能曲线从生效版本稳定重算。


## 编译检查

在项目根目录执行：

```bash
python3 -m compileall -q app tests
```

## 启动服务

准备依赖后可执行 `uvicorn app.main:app --host 127.0.0.1 --port 8000`，根路径返回服务状态，接口文档位于 `/docs`。
