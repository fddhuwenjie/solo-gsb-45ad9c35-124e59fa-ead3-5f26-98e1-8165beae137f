# -*- coding: utf-8 -*-
"""发布航线（/api/releases）行为回归测试。

覆盖：
- 发布成功：版本航线 + 当前工作区禁飞区组合审查通过，发布号单调递增；
- 版本已删除 / 航线无非零长度航段 / 审查有冲突（响应附明细）/
  工作区或已发布号过期 → 返回原因且原发布不变；
- 已发布内容不随后续工作区编辑或来源版本删除而改变。
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402

ROUTE = {
    "departureTime": "2026-10-01T08:00", "unitScale": 100,
    "corridorHalfWidth": 0.3, "speeds": [24],
    "waypoints": [
        {"id": "w1", "name": "A", "x": 100, "y": 100, "alt": 200},
        {"id": "w2", "name": "B", "x": 500, "y": 100, "alt": 200},
    ],
}
# 远离航线（航线在 y=100 一线）的禁飞区：审查应通过
FAR_NFZ = {
    "id": "n1", "name": "南侧限制区", "enabled": True,
    "vertices": [[100, 500], [300, 500], [300, 600], [100, 600]],
    "minAlt": 0, "maxAlt": 400, "startTime": "", "endTime": "",
}
# 压在航线上的禁飞区：审查应报冲突
HIT_NFZ = {
    "id": "n2", "name": "压线禁飞区", "enabled": True,
    "vertices": [[200, 50], [400, 50], [400, 150], [200, 150]],
    "minAlt": 100, "maxAlt": 300, "startTime": "", "endTime": "",
}


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_db = app.DB_PATH
        app.DB_PATH = os.path.join(self.tmp, "test.db")
        app.init_db()
        self.client = app.app.test_client()
        # 干净工作区：航线 + 一个远离航线的禁飞区
        self.put_state({"route": dict(ROUTE), "nfzs": [dict(FAR_NFZ)]})

    def tearDown(self):
        app.DB_PATH = self.old_db
        shutil.rmtree(self.tmp, ignore_errors=True)

    # —— 辅助 ——
    def put_state(self, state):
        r = self.client.put("/api/state", json=state)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ok"])

    def revs(self):
        r = self.client.get("/api/releases")
        self.assertEqual(r.status_code, 200)
        return r.get_json()

    def make_version(self, route=None, name="候选"):
        state = {"route": route if route is not None else dict(ROUTE), "nfzs": []}
        r = self.client.post("/api/versions", json={"name": name, "state": state})
        self.assertEqual(r.status_code, 200)
        return r.get_json()["id"]

    def publish(self, vid, ws, pub):
        return self.client.post("/api/releases", json={
            "versionId": vid, "workspaceRev": ws, "publishedRev": pub})

    def publish_fresh(self, vid):
        meta = self.revs()
        return self.publish(vid, meta["workspaceRev"], meta["publishedRev"])

    # —— 成功路径 ——
    def test_publish_success_and_increment(self):
        vid = self.make_version()
        r = self.publish_fresh(vid)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["releaseNo"], 1)
        self.assertEqual(body["sourceVersionId"], vid)
        # 第二次发布：发布号递增
        meta = self.revs()
        self.assertEqual(meta["publishedRev"], 1)
        r2 = self.publish_fresh(vid)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.get_json()["releaseNo"], 2)

    def test_release_content_is_combined_state(self):
        vid = self.make_version()
        no = self.publish_fresh(vid).get_json()["releaseNo"]
        detail = self.client.get(f"/api/releases/{no}").get_json()
        self.assertTrue(detail["ok"])
        # 航线来自版本，禁飞区来自发布时的工作区
        self.assertEqual(detail["state"]["route"]["waypoints"][0]["name"], "A")
        self.assertEqual(len(detail["state"]["nfzs"]), 1)
        self.assertEqual(detail["state"]["nfzs"][0]["name"], "南侧限制区")
        self.assertEqual(detail["analysis"]["entries"], [])
        self.assertEqual(detail["analysis"]["errors"], [])
        # 列表摘要带发布号、来源与审查结果
        item = self.revs()["releases"][0]
        self.assertEqual(item["releaseNo"], no)
        self.assertEqual(item["sourceVersionId"], vid)
        self.assertEqual(item["conflictCount"], 0)
        self.assertEqual(item["errorCount"], 0)

    # —— 失败路径：返回原因且原发布不变 ——
    def test_version_deleted(self):
        vid = self.make_version()
        self.client.delete(f"/api/versions/{vid}")
        r = self.publish_fresh(vid)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()["reason"], "version_deleted")
        self.assertEqual(self.revs()["releases"], [])

    def test_no_live_segment(self):
        route = dict(ROUTE)
        route["waypoints"] = [
            {"id": "w1", "name": "A", "x": 100, "y": 100, "alt": 200},
            {"id": "w2", "name": "B", "x": 100, "y": 100, "alt": 200},
        ]
        vid = self.make_version(route=route)
        r = self.publish_fresh(vid)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.get_json()["reason"], "no_live_segment")
        self.assertEqual(self.revs()["releases"], [])

    def test_review_conflict_returns_details_and_keeps_old_release(self):
        vid = self.make_version()
        ok = self.publish_fresh(vid)
        self.assertEqual(ok.status_code, 200)
        # 工作区加入压线禁飞区 → 组合审查有冲突
        self.put_state({"route": dict(ROUTE), "nfzs": [dict(HIT_NFZ)]})
        r = self.publish_fresh(vid)
        self.assertEqual(r.status_code, 422)
        body = r.get_json()
        self.assertEqual(body["reason"], "review_failed")
        self.assertTrue(body["entries"], "冲突时应附明细")
        self.assertEqual(body["entries"][0]["nfzName"], "压线禁飞区")
        # 原发布不变
        releases = self.revs()["releases"]
        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0]["releaseNo"], 1)

    def test_stale_workspace_rev(self):
        vid = self.make_version()
        meta = self.revs()
        self.put_state({"route": dict(ROUTE), "nfzs": [dict(FAR_NFZ)]})  # 工作区前进
        r = self.publish(vid, meta["workspaceRev"], meta["publishedRev"])
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["reason"], "workspace_changed")
        self.assertEqual(self.revs()["releases"], [])

    def test_stale_published_rev(self):
        vid = self.make_version()
        meta = self.revs()
        ok = self.publish(vid, meta["workspaceRev"], meta["publishedRev"])
        self.assertEqual(ok.status_code, 200)
        # 用读取时的旧已发布号重提 → 拒绝
        r = self.publish(vid, meta["workspaceRev"], meta["publishedRev"])
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["reason"], "published_changed")
        self.assertEqual(len(self.revs()["releases"]), 1)

    def test_missing_params(self):
        r = self.client.post("/api/releases", json={"versionId": 1})
        self.assertEqual(r.status_code, 400)

    # —— 不可变 ——
    def test_release_immutable_after_workspace_edit_and_version_delete(self):
        vid = self.make_version(name="东线")
        no = self.publish_fresh(vid).get_json()["releaseNo"]
        before = self.client.get(f"/api/releases/{no}").get_json()
        # 之后编辑工作区、删除来源版本
        self.put_state({"route": dict(ROUTE), "nfzs": [dict(HIT_NFZ)]})
        self.client.delete(f"/api/versions/{vid}")
        after = self.client.get(f"/api/releases/{no}").get_json()
        self.assertEqual(before, after)
        self.assertEqual(after["sourceVersionName"], "东线")
        self.assertEqual(after["state"]["nfzs"][0]["name"], "南侧限制区")


if __name__ == "__main__":
    unittest.main(verbosity=2)
