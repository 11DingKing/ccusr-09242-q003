"""受控修订流程测试。

覆盖：
- 跨年月份封账边界（2025-12 封账后 2026-01 可改、2025-12 拒绝）；
- 达产率阈值两侧联动（未达标建档/更新，跨上 100% 自动解决，跨下补建）；
- 已有手工跟进事项与已关闭事项不被自动流程改动；
- 并发修订冲突与相同修订幂等（第二次不产生影响）；
- 季度/总览统计始终基于生效版本稳定重算。
"""

import os
import sys
import tempfile
import threading
import unittest
from datetime import date

from fastapi.testclient import TestClient


def _build_app():
    """使用独立的临时文件数据库全新导入应用，避免触碰仓库内业务库。"""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp.name}"

    # 清掉可能已被其他测试模块导入的 app 包，确保按新环境变量重新初始化。
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    from app import database as db_module  # noqa: E402
    from app import models  # noqa: E402
    from app.enums import (  # noqa: E402
        Region,
        ProjectStatus,
        ParkType,
    )
    from app.main import app  # noqa: E402,F401  导入即完成建表与迁移

    Session = db_module.SessionLocal
    session = Session()
    park = models.IndustrialPark(
        name="测试园区",
        park_type=ParkType.KEY_INDUSTRIAL,
        city="南宁市",
    )
    entity = models.Entity(
        name="测试主体",
        region=Region.GUANGXI,
        country_or_province="广西",
        contact_person="张三",
        contact_phone="123",
    )
    session.add_all([park, entity])
    session.flush()
    project = models.Project(
        name="测试已投产项目",
        status=ProjectStatus.COMMISSIONED,
        investment_direction="水果加工",
        planned_investment_10k=1000.0,
        promised_monthly_capacity_tonnes=100.0,
        park_id=park.id,
        initiator_id=entity.id,
        commissioned_date=date(2025, 1, 1),
    )
    session.add(project)
    session.commit()
    project_id = project.id
    session.close()

    client = TestClient(app)
    return client, Session, project_id, tmp.name, db_module


def report_payload(project_id, year, month, output):
    return {
        "project_id": project_id,
        "report_year": year,
        "report_month": month,
        "actual_output_tonnes": output,
        "employee_count": 20,
        "local_material_procurement_10k": 5.0,
        "reported_by": "录入员",
    }


class CrossYearClosedMonthTests(unittest.TestCase):
    def setUp(self):
        self.client, self.Session, self.pid, self.db_path, self.db_module = _build_app()

    def tearDown(self):
        self.db_module.engine.dispose()
        os.unlink(self.db_path)

    def test_cross_year_boundary_blocks_old_and_allows_new(self):
        client = self.client
        # 2025-12 与 2026-01 各登记一条
        r = client.post(
            "/api/v1/capacity/reports",
            json=report_payload(self.pid, 2025, 12, 60.0),
        )
        self.assertEqual(r.status_code, 200, r.text)
        old_report_id = r.json()["id"]

        r = client.post(
            "/api/v1/capacity/reports",
            json=report_payload(self.pid, 2026, 1, 70.0),
        )
        self.assertEqual(r.status_code, 200, r.text)
        new_report_id = r.json()["id"]

        # 封账至 2025-12（跨年边界）
        r = client.post(
            "/api/v1/capacity/closed-boundary",
            json={
                "close_year": 2025,
                "close_month": 12,
                "reason": "四季度结算",
                "operator": "财务",
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["closed_boundary"], {"year": 2025, "month": 12})

        r = client.get("/api/v1/capacity/closed-boundary")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"year": 2025, "month": 12})

        # 2025-12 修订被拒绝
        r = client.post(
            f"/api/v1/capacity/reports/{old_report_id}/revisions",
            json={
                "actual_output_tonnes": 66.0,
                "reason": "统计填错",
                "operator": "运营A",
            },
        )
        self.assertEqual(r.status_code, 409, r.text)
        detail = r.json()["detail"]
        self.assertEqual(detail["code"], "CAPACITY_MONTH_CLOSED")
        self.assertEqual(detail["closed_boundary"], {"year": 2025, "month": 12})
        self.assertEqual(detail["report_year"], 2025)
        self.assertEqual(detail["report_month"], 12)

        # 旧版 PUT / DELETE 同样被封账拦截
        r = client.put(
            f"/api/v1/capacity/reports/{old_report_id}",
            json={"actual_output_tonnes": 66.0},
        )
        self.assertEqual(r.status_code, 409, r.text)
        r = client.delete(f"/api/v1/capacity/reports/{old_report_id}")
        self.assertEqual(r.status_code, 409, r.text)

        # 2026-01 在边界之后，可以修订
        r = client.post(
            f"/api/v1/capacity/reports/{new_report_id}/revisions",
            json={
                "actual_output_tonnes": 80.0,
                "reason": "补报",
                "operator": "运营A",
            },
        )
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["current_version"], 2)
        self.assertEqual(r.json()["previous_version_no"], 1)
        self.assertIn("取代第 1 版", r.json()["relationship"])
        self.assertEqual(r.json()["closed_boundary"], {"year": 2025, "month": 12})

        # 封账月份内也不允许新增登记
        r = client.post(
            "/api/v1/capacity/reports",
            json=report_payload(self.pid, 2025, 11, 30.0),
        )
        self.assertEqual(r.status_code, 409, r.text)

    def test_advance_boundary_then_new_year_locks(self):
        client = self.client
        r = client.post(
            "/api/v1/capacity/reports",
            json=report_payload(self.pid, 2026, 2, 50.0),
        )
        self.assertEqual(r.status_code, 200)
        report_id = r.json()["id"]
        # 先封到 2026-01，再推进到 2026-02
        client.post(
            "/api/v1/capacity/closed-boundary",
            json={"close_year": 2026, "close_month": 1, "operator": "财务"},
        )
        r = client.post(
            "/api/v1/capacity/closed-boundary",
            json={"close_year": 2026, "close_month": 2, "operator": "财务"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["closed_boundary"], {"year": 2026, "month": 2})
        # 推进后 2026-02 也被锁定
        r = client.post(
            f"/api/v1/capacity/reports/{report_id}/revisions",
            json={"actual_output_tonnes": 55.0, "reason": "x", "operator": "y"},
        )
        self.assertEqual(r.status_code, 409)


class ThresholdAndFollowUpTests(unittest.TestCase):
    def setUp(self):
        self.client, self.Session, self.pid, self.db_path, self.db_module = _build_app()

    def tearDown(self):
        self.db_module.engine.dispose()
        os.unlink(self.db_path)

    def _create_report(self, year=2026, month=3, output=50.0):
        r = self.client.post(
            "/api/v1/capacity/reports",
            json=report_payload(self.pid, year, month, output),
        )
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def test_below_threshold_creates_auto_follow_up(self):
        report_id = self._create_report(output=50.0)  # 达产率 50%
        r = self.client.get(
            "/api/v1/capacity/follow-ups",
            params={"project_id": self.pid},
        )
        self.assertEqual(r.status_code, 200)
        items = r.json()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source"], "AUTO")
        self.assertTrue(items[0]["auto_generated"])
        self.assertEqual(items[0]["report_id"], report_id)
        self.assertEqual(items[0]["gap_percentage"], 50.0)

    def test_revision_around_threshold_updates_and_resolves(self):
        client = self.client
        report_id = self._create_report(output=50.0)

        # 阈值之下修订（50 -> 80，仍未达标）：更新缺口，不新增事项
        r = client.post(
            f"/api/v1/capacity/reports/{report_id}/revisions",
            json={
                "actual_output_tonnes": 80.0,
                "reason": "漏报一个批次",
                "operator": "运营B",
            },
        )
        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        self.assertFalse(body["threshold_crossed"])
        actions = [c["action"] for c in body["follow_up_changes"]]
        self.assertEqual(actions, ["updated"])
        self.assertEqual(body["follow_up_changes"][0]["gap_percentage"], 20.0)

        # 手工跟进事项不应被后续自动流程影响
        r = client.post(
            "/api/v1/capacity/follow-ups",
            json={
                "project_id": self.pid,
                "report_id": report_id,
                "title": "手工补充：协调原料",
                "status": "待跟进",
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        manual_id = r.json()["id"]
        self.assertEqual(r.json()["source"], "MANUAL")
        self.assertFalse(r.json()["auto_generated"])

        # 跨上阈值（80 -> 100，恰好达标）：自动事项解决，手工事项保持待跟进
        r = client.post(
            f"/api/v1/capacity/reports/{report_id}/revisions",
            json={
                "actual_output_tonnes": 100.0,
                "reason": "财务核账后补回产量",
                "operator": "运营B",
                "idempotency_key": "fix-2026-03-final",
            },
        )
        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        self.assertTrue(body["threshold_crossed"])
        self.assertEqual(
            [c["action"] for c in body["follow_up_changes"]], ["resolved"]
        )

        follow_ups = client.get(
            "/api/v1/capacity/follow-ups", params={"project_id": self.pid}
        ).json()
        auto = next(f for f in follow_ups if f["id"] != manual_id)
        manual = next(f for f in follow_ups if f["id"] == manual_id)
        self.assertEqual(auto["status"], "已解决")
        self.assertEqual(manual["status"], "待跟进")

        # 版本链：初始 1 + 两次修订 = 3 版
        versions = client.get(
            f"/api/v1/capacity/reports/{report_id}/revisions"
        ).json()
        self.assertEqual([v["version_no"] for v in versions], [1, 2, 3])
        self.assertEqual(versions[0]["change_type"], "CREATE")
        self.assertEqual(versions[2]["reason"], "财务核账后补回产量")
        self.assertEqual(versions[2]["operator"], "运营B")

        # 主表为生效版本
        detail = client.get(f"/api/v1/capacity/reports/{report_id}").json()
        self.assertEqual(detail["actual_output_tonnes"], 100.0)
        self.assertEqual(detail["current_version"], 3)
        self.assertEqual(detail["capacity_utilization_rate"], 100.0)

    def test_cross_back_below_threshold_creates_new_auto_followup(self):
        client = self.client
        report_id = self._create_report(output=120.0)  # 初始即达标，无自动事项
        self.assertEqual(
            client.get(
                "/api/v1/capacity/follow-ups", params={"project_id": self.pid}
            ).json(),
            [],
        )
        # 跌入未达标：跨阈值，补建自动跟进
        r = client.post(
            f"/api/v1/capacity/reports/{report_id}/revisions",
            json={"actual_output_tonnes": 70.0, "reason": "多报", "operator": "运营C"},
        )
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json()["threshold_crossed"])
        self.assertEqual(
            [c["action"] for c in r.json()["follow_up_changes"]], ["created"]
        )

    def test_closed_follow_up_not_reopened_on_crossing(self):
        client = self.client
        report_id = self._create_report(output=50.0)
        follow_ups = client.get(
            "/api/v1/capacity/follow-ups", params={"project_id": self.pid}
        ).json()
        auto_id = follow_ups[0]["id"]
        # 运营先把自动事项关闭
        r = client.put(
            f"/api/v1/capacity/follow-ups/{auto_id}",
            json={"status": "已关闭", "resolution": "已线下处理"},
        )
        self.assertEqual(r.status_code, 200)
        # 修订跨上达标线：已关闭事项不被改动
        r = client.post(
            f"/api/v1/capacity/reports/{report_id}/revisions",
            json={"actual_output_tonnes": 110.0, "reason": "更正", "operator": "运营D"},
        )
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json()["threshold_crossed"])
        self.assertEqual(r.json()["follow_up_changes"], [])
        follow_ups = client.get(
            "/api/v1/capacity/follow-ups", params={"project_id": self.pid}
        ).json()
        self.assertEqual(follow_ups[0]["status"], "已关闭")
        self.assertEqual(follow_ups[0]["resolution"], "已线下处理")


class IdempotencyAndConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.client, self.Session, self.pid, self.db_path, self.db_module = _build_app()

    def tearDown(self):
        self.db_module.engine.dispose()
        os.unlink(self.db_path)

    def _report_id(self):
        r = self.client.post(
            "/api/v1/capacity/reports",
            json=report_payload(self.pid, 2026, 4, 40.0),
        )
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def test_duplicate_submission_has_no_second_effect(self):
        client = self.client
        report_id = self._report_id()
        payload = {
            "actual_output_tonnes": 90.0,
            "reason": "统一更正",
            "operator": "运营E",
            "idempotency_key": "batch-fix-2026-04",
        }
        r1 = client.post(
            f"/api/v1/capacity/reports/{report_id}/revisions", json=payload
        )
        self.assertEqual(r1.status_code, 201, r1.text)
        self.assertFalse(r1.json()["idempotent"])

        r2 = client.post(
            f"/api/v1/capacity/reports/{report_id}/revisions", json=payload
        )
        self.assertEqual(r2.status_code, 201, r2.text)
        body = r2.json()
        self.assertTrue(body["idempotent"])
        self.assertFalse(body["effects_applied"])
        self.assertEqual(body["new_version_no"], 2)
        self.assertIn("no-op", body["relationship"])
        self.assertEqual(body["follow_up_changes"], [])

        # 只存在 1、2 两版；自动跟进只被更新一次
        versions = client.get(
            f"/api/v1/capacity/reports/{report_id}/revisions"
        ).json()
        self.assertEqual(len(versions), 2)
        follow_ups = client.get(
            "/api/v1/capacity/follow-ups", params={"project_id": self.pid}
        ).json()
        self.assertEqual(len(follow_ups), 1)
        self.assertEqual(follow_ups[0]["gap_percentage"], 10.0)

        # 相同产量、不同幂等键视为一次新的显式修订
        r3 = client.post(
            f"/api/v1/capacity/reports/{report_id}/revisions",
            json={**payload, "idempotency_key": "another-key"},
        )
        self.assertEqual(r3.status_code, 201)
        self.assertFalse(r3.json()["idempotent"])
        self.assertEqual(r3.json()["new_version_no"], 3)

    def test_optimistic_lock_rejects_stale_version(self):
        client = self.client
        report_id = self._report_id()
        r = client.post(
            f"/api/v1/capacity/reports/{report_id}/revisions",
            json={
                "actual_output_tonnes": 60.0,
                "reason": "第一次",
                "operator": "运营F",
                "expected_version": 1,
            },
        )
        self.assertEqual(r.status_code, 201)
        # 仍声明基于第 1 版 -> 冲突
        r = client.post(
            f"/api/v1/capacity/reports/{report_id}/revisions",
            json={
                "actual_output_tonnes": 70.0,
                "reason": "滞后的第二次",
                "operator": "运营F",
                "expected_version": 1,
            },
        )
        self.assertEqual(r.status_code, 409)
        self.assertEqual(
            r.json()["detail"]["code"], "CAPACITY_VERSION_CONFLICT"
        )
        self.assertEqual(r.json()["detail"]["current_version"], 2)

    def test_legacy_report_without_revision_backfilled(self):
        from app import models

        session = self.Session()
        report = models.MonthlyCapacityReport(
            project_id=self.pid,
            report_year=2026,
            report_month=6,
            actual_output_tonnes=30.0,
            capacity_utilization_rate=30.0,
            current_version=1,
        )
        session.add(report)
        session.commit()
        report_id = report.id
        session.close()

        r = self.client.post(
            f"/api/v1/capacity/reports/{report_id}/revisions",
            json={"actual_output_tonnes": 85.0, "reason": "历史补录", "operator": "运营G"},
        )
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["previous_version_no"], 1)
        versions = self.client.get(
            f"/api/v1/capacity/reports/{report_id}/revisions"
        ).json()
        self.assertEqual([v["version_no"] for v in versions], [1, 2])
        self.assertEqual(versions[0]["change_type"], "CREATE")
        self.assertIn("迁移", versions[0]["reason"])
        self.assertEqual(versions[1]["actual_output_tonnes"], 85.0)

    def test_true_concurrent_revisions_only_one_wins(self):
        # 两个独立线程/连接同时提交，版本号唯一约束保证只有一次生效。
        from app import models  # noqa: E402
        from app.services import revisions as revision_service  # noqa: E402
        from app import schemas  # noqa: E402

        setup = self.Session()
        report = models.MonthlyCapacityReport(
            project_id=self.pid,
            report_year=2026,
            report_month=5,
            actual_output_tonnes=40.0,
            capacity_utilization_rate=40.0,
            current_version=1,
        )
        setup.add(report)
        setup.flush()
        setup.add(
            models.CapacityReportRevision(
                report_id=report.id,
                project_id=self.pid,
                version_no=1,
                actual_output_tonnes=40.0,
                capacity_utilization_rate=40.0,
                change_type="CREATE",
                reason="初始登记",
            )
        )
        setup.commit()
        report_id = report.id
        setup.close()

        barrier = threading.Barrier(2)
        results = []

        def worker(output):
            session = self.Session()
            try:
                barrier.wait()
                payload = schemas.CapacityRevisionCreate(
                    actual_output_tonnes=output,
                    reason="并发修订",
                    operator=f"运营-{output}",
                )
                try:
                    revision_service.apply_revision(session, report_id, payload)
                    results.append(("ok", output))
                except revision_service.ConcurrentRevisionError:
                    results.append(("conflict", output))
            finally:
                session.close()

        t1 = threading.Thread(target=worker, args=(60.0,))
        t2 = threading.Thread(target=worker, args=(70.0,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        statuses = sorted(r[0] for r in results)
        self.assertEqual(statuses, ["conflict", "ok"])

        verify = self.Session()
        versions = (
            verify.query(models.CapacityReportRevision)
            .filter_by(report_id=report_id)
            .order_by(models.CapacityReportRevision.version_no)
            .all()
        )
        self.assertEqual([v.version_no for v in versions], [1, 2])
        current = (
            verify.query(models.MonthlyCapacityReport).filter_by(id=report_id).first()
        )
        self.assertEqual(current.current_version, 2)
        winning_output = [r[1] for r in results if r[0] == "ok"][0]
        self.assertEqual(current.actual_output_tonnes, winning_output)
        verify.close()


class QuarterlyRecomputeTests(unittest.TestCase):
    def setUp(self):
        self.client, self.Session, self.pid, self.db_path, self.db_module = _build_app()

    def tearDown(self):
        self.db_module.engine.dispose()
        os.unlink(self.db_path)

    def test_statistics_reflect_effective_version(self):
        client = self.client
        # 一季度三个月登记后，对 2026-02 做修订
        for month, output in [(1, 50.0), (2, 60.0), (3, 70.0)]:
            r = client.post(
                "/api/v1/capacity/reports",
                json=report_payload(self.pid, 2026, month, output),
            )
            self.assertEqual(r.status_code, 200)

        feb = next(
            r
            for r in client.get("/api/v1/capacity/reports").json()
            if r["report_month"] == 2
        )
        r = client.post(
            f"/api/v1/capacity/reports/{feb['id']}/revisions",
            json={
                "actual_output_tonnes": 95.0,
                "reason": "台账更正",
                "operator": "统计员",
            },
        )
        self.assertEqual(r.status_code, 201)

        # 总览按“最新月份生效版本”取值：3 月为 70 吨
        overview = client.get("/api/v1/capacity/statistics/overview").json()
        self.assertEqual(overview["total_actual_output_tonnes"], 70.0)
        self.assertEqual(overview["overall_utilization_rate"], 70.0)

        # 项目曲线逐月读取生效版本：2 月应显示修订后的 95 吨
        curve = client.get(
            f"/api/v1/capacity/projects/{self.pid}/curve"
        ).json()
        feb_point = next(p for p in curve["curve"] if p["month"] == 2)
        self.assertEqual(feb_point["actual_output_tonnes"], 95.0)
        self.assertEqual(feb_point["utilization_rate"], 95.0)

        # 封账后再次重算，结果保持稳定
        client.post(
            "/api/v1/capacity/closed-boundary",
            json={"close_year": 2026, "close_month": 3, "operator": "财务"},
        )
        overview2 = client.get("/api/v1/capacity/statistics/overview").json()
        self.assertEqual(
            overview2["total_actual_output_tonnes"],
            overview["total_actual_output_tonnes"],
        )
        curve2 = client.get(
            f"/api/v1/capacity/projects/{self.pid}/curve"
        ).json()
        self.assertEqual(curve2["curve"], curve["curve"])


if __name__ == "__main__":
    unittest.main()
