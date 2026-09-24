"""产能受控修订流程测试。

覆盖：
- 封账月份拒绝登记/修订/删除（含跨年月份边界）
- 修订留痕（原因、操作者、新旧版本关系）
- 达产率 100% 阈值两侧的跟进事项联动（含已有手工跟进）
- 相同修订幂等重复提交不产生第二次影响
- 并发修订（同幂等键 / 不同内容）
- 季度统计从生效版本稳定重算（跨季度、封账前后一致）
"""

import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app import models
from app.enums import FollowUpStatus


API = "/api/v1"


class RevisionFlowTestBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )

        @event.listens_for(self.engine, "connect")
        def _wal(dbapi_con, _record):  # noqa: ANN001
            cur = dbapi_con.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.project_id = self._seed_commissioned_project()

    def tearDown(self):
        app.dependency_overrides.clear()
        self.engine.dispose()
        for suffix in ("", "-wal", "-shm"):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _seed_commissioned_project(self) -> int:
        entity = self.client.post(
            f"{API}/entities",
            json={
                "name": "东盟果业集团",
                "region": "东盟方",
                "country_or_province": "泰国",
                "contact_person": "林经理",
                "contact_phone": "0771-1000001",
            },
        ).json()
        park = self.client.post(
            f"{API}/parks",
            json={
                "name": "凭祥沿边临港产业园",
                "park_type": "沿边临港产业园",
                "city": "崇左市",
            },
        ).json()
        project = self.client.post(
            f"{API}/projects",
            json={
                "name": "榴莲深加工一期",
                "status": "已投产",
                "investment_direction": "榴莲果肉加工",
                "planned_investment_10k": 5000,
                "promised_monthly_capacity_tonnes": 100,
                "park_id": park["id"],
                "initiator_id": entity["id"],
                "project_leader": "黄组长",
            },
        ).json()
        return project["id"]

    def _create_report(self, year, month, tonnes, reported_by="统计员"):
        resp = self.client.post(
            f"{API}/capacity/reports",
            json={
                "project_id": self.project_id,
                "report_year": year,
                "report_month": month,
                "actual_output_tonnes": tonnes,
                "reported_by": reported_by,
            },
        )
        self.assertIn(resp.status_code, (200, 201), resp.text)
        return resp.json()

    def _revise(self, report_id, **payload):
        return self.client.post(
            f"{API}/capacity/reports/{report_id}/revisions", json=payload
        )

    def _close_quarter(self, year, quarter):
        return self.client.post(
            f"{API}/capacity/accounting/close-quarter",
            json={
                "year": year,
                "quarter": quarter,
                "closed_by": "财务主管",
                "reason": "季度结算",
            },
        )


class SealedPeriodTests(RevisionFlowTestBase):
    def test_cross_year_sealed_boundary_rejects_changes(self):
        # 先登记 2025-12（跨年月份），封 2025Q4
        report = self._create_report(2025, 12, 80)

        resp = self._close_quarter(2025, 4)
        self.assertEqual(resp.status_code, 201, resp.text)

        boundary = self.client.get(
            f"{API}/capacity/accounting/boundary"
        ).json()
        self.assertEqual(boundary["closed_through_year"], 2025)
        self.assertEqual(boundary["closed_through_month"], 12)
        self.assertIn("2025年12月", boundary["closed_through_label"])

        # 封账月份拒绝修订
        resp = self._revise(
            report["id"],
            actual_output_tonnes=90,
            reason="补录更正",
            revised_by="运营小王",
        )
        self.assertEqual(resp.status_code, 423)
        detail = resp.json()["detail"]
        self.assertEqual(
            detail["accounting_boundary"]["closed_through_month"], 12
        )

        # 封账月份拒绝删除与重复登记
        self.assertEqual(
            self.client.delete(f"{API}/capacity/reports/{report['id']}").status_code,
            423,
        )
        dup = self.client.post(
            f"{API}/capacity/reports",
            json={
                "project_id": self.project_id,
                "report_year": 2025,
                "report_month": 12,
                "actual_output_tonnes": 70,
            },
        )
        self.assertEqual(dup.status_code, 423)

        # 下一年度月份仍可修订（跨年边界比较正确）
        report_2026 = self._create_report(2026, 1, 80)
        resp = self._revise(
            report_2026["id"],
            actual_output_tonnes=95,
            reason="次月补报修正",
            revised_by="运营小王",
        )
        self.assertEqual(resp.status_code, 201, resp.text)

    def test_cannot_close_same_quarter_twice_and_reopen_order(self):
        self._create_report(2026, 1, 80)
        self.assertEqual(self._close_quarter(2026, 1).status_code, 201)
        self.assertEqual(self._close_quarter(2026, 1).status_code, 409)

        self._create_report(2026, 4, 80)
        self._close_quarter(2026, 2)

        # 边界末端是 Q2，不能先解 Q1
        resp = self.client.post(
            f"{API}/capacity/accounting/reopen-quarter",
            json={"year": 2026, "quarter": 1, "reopened_by": "财务主管"},
        )
        self.assertEqual(resp.status_code, 409)
        # 逆序解封
        resp = self.client.post(
            f"{API}/capacity/accounting/reopen-quarter",
            json={"year": 2026, "quarter": 2, "reopened_by": "财务主管"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        boundary = self.client.get(f"{API}/capacity/accounting/boundary").json()
        self.assertEqual(boundary["closed_through_month"], 3)


class RevisionVersioningTests(RevisionFlowTestBase):
    def test_revision_creates_version_chain_with_operator_and_reason(self):
        report = self._create_report(2026, 2, 80)
        self.assertEqual(report["current_version_no"], 1)

        resp = self._revise(
            report["id"],
            actual_output_tonnes=88,
            reason="企业补报，统计口径错误",
            revised_by="运营小王",
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        result = resp.json()
        self.assertFalse(result["idempotent_replay"])
        self.assertEqual(result["previous_version_no"], 1)
        self.assertEqual(result["report"]["current_version_no"], 2)
        self.assertEqual(result["revision"]["revision_no"], 2)
        self.assertEqual(result["revision"]["revised_by"], "运营小王")
        self.assertEqual(result["revision"]["from_actual_output_tonnes"], 80)
        self.assertEqual(result["revision"]["to_actual_output_tonnes"], 88)
        # 达产率按承诺产能重算 88%
        self.assertEqual(result["utilization_after"], 88.0)
        # 封账边界信息随响应返回
        self.assertIn("periods", result["accounting_boundary"])

        # 版本链：v1 初次登记，v2 受控修订，supersedes 指向 v1
        revisions = self.client.get(
            f"{API}/capacity/reports/{report['id']}/revisions"
        ).json()
        self.assertEqual([r["revision_no"] for r in revisions], [1, 2])
        self.assertEqual(revisions[0]["reason"], "初次登记")
        self.assertEqual(
            revisions[1]["supersedes_revision_id"], revisions[0]["id"]
        )

    def test_reason_and_operator_are_required(self):
        report = self._create_report(2026, 2, 80)
        resp = self._revise(report["id"], actual_output_tonnes=88, reason="补报")
        self.assertEqual(resp.status_code, 422)
        resp = self._revise(
            report["id"], actual_output_tonnes=88, revised_by="小王"
        )
        self.assertEqual(resp.status_code, 422)

    def test_direct_put_is_blocked(self):
        report = self._create_report(2026, 2, 80)
        resp = self.client.put(
            f"{API}/capacity/reports/{report['id']}",
            json={"actual_output_tonnes": 999},
        )
        self.assertEqual(resp.status_code, 400)
        fresh = self.client.get(f"{API}/capacity/reports/{report['id']}").json()
        self.assertEqual(fresh["actual_output_tonnes"], 80)
        self.assertEqual(fresh["current_version_no"], 1)

    def test_noop_revision_rejected(self):
        report = self._create_report(2026, 2, 80)
        resp = self._revise(
            report["id"],
            actual_output_tonnes=80,
            reason="与现值一致",
            revised_by="小王",
        )
        self.assertEqual(resp.status_code, 400)


class ThresholdFollowUpTests(RevisionFlowTestBase):
    def _open_follow_ups(self, report_id):
        rows = (
            self.SessionLocal()
            .query(models.CapacityFollowUp)
            .filter(models.CapacityFollowUp.report_id == report_id)
            .all()
        )
        return rows

    def test_cross_upward_closes_auto_and_manual_follow_ups(self):
        # 80/100 未达标，自动生成跟进；再手工挂接一条
        report = self._create_report(2026, 3, 80)
        manual = self.client.post(
            f"{API}/capacity/follow-ups",
            json={
                "project_id": self.project_id,
                "report_id": report["id"],
                "title": "手工跟进：核查用电瓶颈",
                "status": "跟进中",
            },
        )
        self.assertIn(manual.status_code, (200, 201), manual.text)

        # 阈值下方之间调整（80→90），不联动
        resp = self._revise(
            report["id"],
            actual_output_tonnes=90,
            reason="小幅修正",
            revised_by="小王",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertIsNone(resp.json()["threshold_crossed"])
        self.assertEqual(
            self.client.get(f"{API}/capacity/follow-ups").json().__len__(), 2
        )

        # 跨阈值向上（90→100）：自动 + 手工未关闭事项全部关闭
        resp = self._revise(
            report["id"],
            actual_output_tonnes=100,
            reason="企业补报，产量已达标",
            revised_by="小王",
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        result = resp.json()
        self.assertEqual(result["threshold_crossed"], "upward")
        self.assertEqual(result["follow_up_action"], "closed_open_follow_ups")
        self.assertEqual(len(result["closed_follow_ups"]), 2)
        for fu in self._open_follow_ups(report["id"]):
            self.assertEqual(fu.status, FollowUpStatus.CLOSED)
            self.assertIsNotNone(fu.closed_by_revision_id)

        # 已关闭后再在阈值上方修订（100→110），不重复操作事项
        resp = self._revise(
            report["id"],
            actual_output_tonnes=110,
            reason="继续补报",
            revised_by="小王",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertIsNone(resp.json()["threshold_crossed"])

    def test_cross_downward_creates_follow_up_or_annotates_manual(self):
        # 初次登记即达标，无自动跟进
        report = self._create_report(2026, 4, 120)
        self.assertEqual(
            [fu for fu in self._open_follow_ups(report["id"])], []
        )

        # 跨阈值向下：自动生成修订联动事项
        resp = self._revise(
            report["id"],
            actual_output_tonnes=70,
            reason="统计多录，实际未达标",
            revised_by="小王",
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        result = resp.json()
        self.assertEqual(result["threshold_crossed"], "downward")
        self.assertEqual(result["follow_up_action"], "created_follow_up")
        self.assertIsNotNone(result["created_follow_up_id"])
        follow_ups = self._open_follow_ups(report["id"])
        self.assertEqual(len(follow_ups), 1)
        self.assertEqual(follow_ups[0].source.value, "修订联动")
        self.assertEqual(follow_ups[0].gap_percentage, 30.0)

        # 再向下修订（仍在阈值下方）不重复建单
        resp = self._revise(
            report["id"],
            actual_output_tonnes=60,
            reason="再次修正",
            revised_by="小王",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertIsNone(resp.json()["threshold_crossed"])
        self.assertEqual(len(self._open_follow_ups(report["id"])), 1)

    def test_downward_with_existing_manual_follow_up_no_duplicate(self):
        report = self._create_report(2026, 5, 120)
        manual = self.client.post(
            f"{API}/capacity/follow-ups",
            json={
                "project_id": self.project_id,
                "report_id": report["id"],
                "title": "手工事项：预防性巡检",
            },
        ).json()
        resp = self._revise(
            report["id"],
            actual_output_tonnes=80,
            reason="补报后发现未达标",
            revised_by="小王",
        )
        self.assertEqual(resp.status_code, 201)
        result = resp.json()
        self.assertEqual(result["follow_up_action"], "existing_open_follow_up")
        self.assertIsNone(result["created_follow_up_id"])
        follow_ups = self._open_follow_ups(report["id"])
        self.assertEqual(len(follow_ups), 1)
        self.assertEqual(follow_ups[0].id, manual["id"])
        self.assertIn("修订 v2", follow_ups[0].description)


class IdempotencyTests(RevisionFlowTestBase):
    def test_duplicate_submission_has_no_second_effect(self):
        report = self._create_report(2026, 6, 80)
        payload = {
            "actual_output_tonnes": 100,
            "reason": "企业补报修正",
            "revised_by": "小王",
            "idempotency_key": "rev-2026-06-001",
        }
        first = self._revise(report["id"], **payload)
        self.assertEqual(first.status_code, 201, first.text)
        first_data = first.json()
        self.assertFalse(first_data["idempotent_replay"])
        self.assertEqual(len(first_data["closed_follow_ups"]), 1)

        second = self._revise(report["id"], **payload)
        self.assertEqual(second.status_code, 201, second.text)
        second_data = second.json()
        self.assertTrue(second_data["idempotent_replay"])
        self.assertEqual(
            second_data["revision"]["id"], first_data["revision"]["id"]
        )
        self.assertEqual(second_data["report"]["current_version_no"], 2)

        # 只生成一条修订、只关闭一次跟进
        revisions = self.client.get(
            f"{API}/capacity/reports/{report['id']}/revisions"
        ).json()
        self.assertEqual(len(revisions), 2)
        db = self.SessionLocal()
        self.assertEqual(
            db.query(models.CapacityReportRevision)
            .filter(
                models.CapacityReportRevision.idempotency_key
                == "rev-2026-06-001"
            )
            .count(),
            1,
        )
        closed = (
            db.query(models.CapacityFollowUp)
            .filter(
                models.CapacityFollowUp.closed_by_revision_id
                == first_data["revision"]["id"]
            )
            .count()
        )
        self.assertEqual(closed, 1)
        db.close()

    def test_idempotency_key_cannot_be_reused_across_reports(self):
        r1 = self._create_report(2026, 7, 80)
        r2 = self._create_report(2026, 8, 80)
        payload = {
            "actual_output_tonnes": 90,
            "reason": "修正",
            "revised_by": "小王",
            "idempotency_key": "shared-key",
        }
        self.assertEqual(self._revise(r1["id"], **payload).status_code, 201)
        self.assertEqual(self._revise(r2["id"], **payload).status_code, 409)


class ConcurrentRevisionTests(RevisionFlowTestBase):
    def test_concurrent_same_idempotency_key_applies_once(self):
        report = self._create_report(2026, 9, 80)
        payload = {
            "actual_output_tonnes": 100,
            "reason": "企业补报",
            "revised_by": "小王",
            "idempotency_key": "concurrent-key",
        }

        results = []

        def fire():
            client = TestClient(app)
            results.append(
                client.post(
                    f"{API}/capacity/reports/{report['id']}/revisions",
                    json=payload,
                )
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: fire(), range(2)))

        self.assertEqual({r.status_code for r in results}, {201})
        revision_ids = {r.json()["revision"]["id"] for r in results}
        self.assertEqual(len(revision_ids), 1)
        fresh = self.client.get(
            f"{API}/capacity/reports/{report['id']}"
        ).json()
        self.assertEqual(fresh["current_version_no"], 2)
        self.assertEqual(len(fresh["revisions"]), 2)

    def test_concurrent_distinct_revisions_never_corrupt_version_chain(self):
        report = self._create_report(2026, 10, 80)

        def fire(tonnes):
            client = TestClient(app)
            return client.post(
                f"{API}/capacity/reports/{report['id']}/revisions",
                json={
                    "actual_output_tonnes": tonnes,
                    "reason": f"并发修正至{tonnes}",
                    "revised_by": f"运营{tonnes}",
                },
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(fire, [90, 95]))

        statuses = sorted(r.status_code for r in responses)
        self.assertIn(statuses[0], (201, 409))
        self.assertNotIn(500, statuses)

        # 真实冲突时一胜一败：败方基于最新版本顺序重试
        if any(r.status_code == 409 for r in responses):
            winner = next(r for r in responses if r.status_code == 201)
            winner_tonnes = winner.json()["revision"]["to_actual_output_tonnes"]
            loser_tonnes = 95 if winner_tonnes == 90 else 90
            retry = self._revise(
                report["id"],
                actual_output_tonnes=loser_tonnes,
                reason="冲突后顺序重试",
                revised_by="仲裁员",
            )
            self.assertEqual(retry.status_code, 201, retry.text)

        # 无论串行还是冲突重试：版本链连续无重复，两次修订的值都保留
        db = self.SessionLocal()
        revisions = (
            db.query(models.CapacityReportRevision)
            .filter(
                models.CapacityReportRevision.report_id == report["id"]
            )
            .order_by(models.CapacityReportRevision.revision_no)
            .all()
        )
        self.assertEqual([r.revision_no for r in revisions], [1, 2, 3])
        self.assertEqual(
            {r.to_actual_output_tonnes for r in revisions if r.revision_no > 1},
            {90.0, 95.0},
        )
        fresh_report = (
            db.query(models.MonthlyCapacityReport)
            .filter(models.MonthlyCapacityReport.id == report["id"])
            .first()
        )
        self.assertEqual(fresh_report.current_version_no, 3)
        self.assertIn(fresh_report.actual_output_tonnes, (90.0, 95.0))
        db.close()


class QuarterlyStatisticsTests(RevisionFlowTestBase):
    def test_quarterly_stats_recompute_from_effective_version(self):
        # 2025-12（跨年月）与 2026-01/02
        self._create_report(2025, 12, 80)
        jan = self._create_report(2026, 1, 80)
        self._create_report(2026, 2, 120)

        def q1_stats():
            return self.client.get(
                f"{API}/capacity/statistics/quarterly",
                params={"year": 2026, "quarter": 1},
            )

        stats = q1_stats().json()
        self.assertEqual(stats["start_year"], 2026)
        self.assertEqual(stats["start_month"], 1)
        self.assertEqual(stats["end_month"], 3)
        self.assertFalse(stats["sealed"])
        item = stats["items"][0]
        self.assertEqual(
            [(m["period"], m["version_no"]) for m in item["months"]],
            [("2026-01", 1), ("2026-02", 1)],
        )
        self.assertEqual(stats["total_actual_output_tonnes"], 200.0)

        # 一月修订为 110 后，季度统计按生效版本重算
        resp = self._revise(
            jan["id"],
            actual_output_tonnes=110,
            reason="企业补报修正一月数据",
            revised_by="小王",
        )
        self.assertEqual(resp.status_code, 201)
        stats = q1_stats().json()
        item = stats["items"][0]
        self.assertEqual(item["months"][0]["actual_output_tonnes"], 110.0)
        self.assertEqual(item["months"][0]["version_no"], 2)
        self.assertIsNotNone(item["months"][0]["revised_at"])
        self.assertEqual(stats["total_actual_output_tonnes"], 230.0)
        self.assertEqual(stats["overall_utilization_rate"], 115.0)

        # 封账前后统计结果稳定一致
        before_seal = stats
        self._close_quarter(2026, 1)
        after_seal = q1_stats().json()
        self.assertTrue(after_seal["sealed"])
        self.assertEqual(
            after_seal["total_actual_output_tonnes"],
            before_seal["total_actual_output_tonnes"],
        )
        self.assertEqual(
            after_seal["overall_utilization_rate"],
            before_seal["overall_utilization_rate"],
        )
        self.assertEqual(
            after_seal["accounting_boundary"]["closed_through_label"],
            "2026年3月",
        )

    def test_stats_after_cross_year_quarter_close(self):
        self._create_report(2025, 12, 80)
        self._close_quarter(2025, 4)
        stats = self.client.get(
            f"{API}/capacity/statistics/quarterly",
            params={"year": 2025, "quarter": 4},
        ).json()
        self.assertTrue(stats["sealed"])
        self.assertEqual(stats["total_actual_output_tonnes"], 80.0)
        self.assertEqual(stats["items"][0]["months"][0]["period"], "2025-12")


if __name__ == "__main__":
    unittest.main()
