# -*- coding: utf-8 -*-
"""
test_ops2_write_side.py — OPS-2 (t_2c2f88f0) C5 心跳龄根因修复 + 告警写口收敛 add_alert 回归

验证目标（修复后 GREEN）:
  1. sys_watchdog._hb_parse_ts 时间戳单位自动判别:
     epoch秒 / epoch毫秒 / '|'-前缀毫秒串 / ISO 文本 / 0 / '0' / None / 不可解析
  2. sys_watchdog.check_kanban_zombie 分类 (tmp sqlite 注入):
     缺失/epoch-0 → P0「心跳缺失(epoch)」; 龄>10080min → P0「心跳脏值」;
     45min<龄≤10080min → P1 stale; 新鲜 → ok; 不再产出天文年龄(57年型误报)
  3. queue_integration.add_alert 契约: 条目 shape {id,type,priority,content,data,ts,sent}
     + 队列落盘 + alert_history 保留100条
  4. 消费侧兼容: cron_message_sender._render_content(add_alert条目) 层2可渲染;
     C5 新 P0 文案不含 >10080min 的「心跳龄 NNNmin」段 → 层4 不误吞
"""
import importlib.util
import json
import os
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestHbParseTs(unittest.TestCase):
    """C5 根因: 秒/毫秒单位错位曾致 1970 基线 → 57 年天文年龄误报"""

    @classmethod
    def setUpClass(cls):
        cls.swd = _load("swd", "scripts/sys_watchdog.py")

    def test_epoch_seconds_auto_detect(self):
        now_s = int(time.time())
        d = self.swd._hb_parse_ts(now_s)
        self.assertIsNotNone(d)
        self.assertLess(abs((datetime.now() - d).total_seconds()), 5)

    def test_epoch_ms_auto_detect(self):
        now_ms = int(time.time() * 1000)
        d = self.swd._hb_parse_ts(now_ms)
        self.assertIsNotNone(d)
        self.assertLess(abs((datetime.now() - d).total_seconds()), 5)

    def test_pipe_prefixed_ms_string(self):
        now_ms = int(time.time() * 1000)
        d = self.swd._hb_parse_ts("|%d" % now_ms)
        self.assertIsNotNone(d)
        self.assertLess(abs((datetime.now() - d).total_seconds()), 5)

    def test_iso_string(self):
        d = self.swd._hb_parse_ts("2026-01-01T08:30:00")
        self.assertEqual(d, datetime(2026, 1, 1, 8, 30, 0))

    def test_epoch_zero_variants_all_none(self):
        for bad in (0, 0.0, "0", "|0", None, "", "|"):
            self.assertIsNone(self.swd._hb_parse_ts(bad), "bad=%r" % (bad,))

    def test_unparseable_none(self):
        self.assertIsNone(self.swd._hb_parse_ts("garbage-not-a-ts"))


class TestCheckKanbanZombie(unittest.TestCase):
    """C5 分类: 缺失(epoch)/脏值 → P0 loud; 45min stale → P1; 新鲜 → ok"""

    @classmethod
    def setUpClass(cls):
        cls.swd = _load("swd2", "scripts/sys_watchdog.py")

    def _make_db(self, rows):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE tasks (id TEXT, assignee TEXT, status TEXT,"
                    " last_heartbeat_at, worker_started_at)")
        for r in rows:
            con.execute("INSERT INTO tasks VALUES (?,?,?,?,?)", r)
        con.commit()
        con.close()
        return path

    def _now(self):
        return int(time.time())

    def test_fresh_rows_ok(self):
        n = self._now()
        db = self._make_db([
            ("t_fresh_s", "a", "running", n, "|%d" % (n * 1000)),
            ("t_fresh_ms", "b", "running", n * 1000, str(n * 1000)),
            ("t_fresh_iso", "c", "running",
             (datetime.now() - timedelta(minutes=10)).isoformat(), None),
        ])
        c = self.swd.check_kanban_zombie(db_path=db)
        os.unlink(db)
        self.assertEqual(c["status"], "ok", c)
        self.assertEqual(c["level"], "P1")

    def test_epoch_zero_and_null_p0_missing(self):
        n = self._now()
        db = self._make_db([
            ("t_epoch0", "a", "running", 0, 0),
            ("t_null", "b", "running", None, None),
        ])
        c = self.swd.check_kanban_zombie(db_path=db)
        os.unlink(db)
        self.assertEqual(c["status"], "fail", c)
        self.assertEqual(c["level"], "P0")
        self.assertIn("心跳缺失(epoch)", c["evidence"])
        self.assertIn("t_epoch0", c["evidence"])
        self.assertIn("t_null", c["evidence"])

    def test_dirty_value_p0_no_astronomical_age(self):
        n = self._now()
        db = self._make_db([
            ("t_dirty", "a", "running", n - 8 * 86400, None),  # 8天前 (秒) → 脏值
        ])
        c = self.swd.check_kanban_zombie(db_path=db)
        os.unlink(db)
        self.assertEqual(c["status"], "fail", c)
        self.assertEqual(c["level"], "P0")
        self.assertIn("心跳脏值", c["evidence"])
        # 天文年龄不复现: evidence 中不得出现 >10080min 的「心跳龄 NNNmin」
        import re
        for m in re.findall(r"心跳龄(\d+)min", c["evidence"]):
            self.assertLessEqual(int(m), 10080)

    def test_stale_45min_p1(self):
        n = self._now()
        db = self._make_db([
            ("t_stale", "a", "running", n - 60 * 60, None),  # 60min → stale
        ])
        c = self.swd.check_kanban_zombie(db_path=db)
        os.unlink(db)
        self.assertEqual(c["status"], "fail", c)
        self.assertEqual(c["level"], "P1")
        self.assertIn("心跳龄", c["evidence"])

    def test_pipe_started_not_astronomical(self):
        """worker_started_at='|'+ms 不再参与判龄, 新鲜 hb 的任务即使 started 脏也 ok"""
        n = self._now()
        db = self._make_db([
            ("t_pipe", "a", "running", n, "|179220252129"),
        ])
        c = self.swd.check_kanban_zombie(db_path=db)
        os.unlink(db)
        self.assertEqual(c["status"], "ok", c)


class TestAddAlertContract(unittest.TestCase):
    """add_alert = 生产端唯一规范写口; 契约 shape 与落盘行为"""

    @classmethod
    def setUpClass(cls):
        cls.qi = _load("qi2", "scripts/queue_integration.py")

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.qi.QUEUE_FILE = Path(os.path.join(self.tmp, "message_queue.json"))
        self.qi.ALERT_HISTORY = Path(os.path.join(self.tmp, "alert_history.json"))

    def test_entry_shape_and_persist(self):
        a = self.qi.add_alert("unit_test", "P2", "hello", data={"x": 1})
        self.assertEqual(set(a.keys()), {"id", "type", "priority", "content", "data", "ts", "sent"})
        self.assertEqual(a["type"], "unit_test")
        self.assertEqual(a["priority"], "P2")
        self.assertEqual(a["data"], {"x": 1})
        self.assertFalse(a["sent"])
        q = json.loads(self.qi.QUEUE_FILE.read_text(encoding="utf-8"))
        self.assertEqual(len(q), 1)
        self.assertEqual(q[0]["content"], "hello")
        self.assertEqual(q[0]["id"], a["id"])

    def test_history_capped_100(self):
        for i in range(105):
            self.qi.add_alert("cap", "P2", "m%d" % i)
        h = json.loads(self.qi.ALERT_HISTORY.read_text(encoding="utf-8"))
        self.assertEqual(len(h), 100)
        self.assertEqual(h[-1]["content"], "m104")

    def test_append_preserves_existing(self):
        self.qi.add_alert("one", "P2", "first")
        self.qi.add_alert("two", "P1", "second")
        q = json.loads(self.qi.QUEUE_FILE.read_text(encoding="utf-8"))
        self.assertEqual([e["type"] for e in q], ["one", "two"])


class TestConsumerCompat(unittest.TestCase):
    """消费侧 (cron_message_sender) 对 add_alert 契约条目的兼容性 — 防契约漂移再发"""

    @classmethod
    def setUpClass(cls):
        cls.cms = _load("cms2", "cron_message_sender.py")

    def _entry(self, content, priority="P1"):
        return {"id": "t_syswatchdog", "type": "sys_watchdog", "priority": priority,
                "content": content, "data": {}, "ts": 0.0, "sent": False}

    def test_add_alert_entry_renderable_layer2(self):
        ok, text = self.cms._render_content(self._entry("🔴 [P1] C5_x — 心跳新鲜"))
        self.assertTrue(ok)
        self.assertIn("C5_x", text)

    def test_c5_p0_epoch_text_not_dirty_stripped(self):
        text = ("🔴 [P0] C5_kanban_zombie_worker — 心跳缺失(epoch)/脏值 1 项: "
                "t_x(a) 心跳缺失(epoch) hb=None started龄10min\n"
                "修复提示: epoch-0/null/1970基线 = 心跳写链断或单位/shape异常")
        clean, had = self.cms._strip_dirty_age_segments(text)
        self.assertFalse(had, "C5 新 P0 文案不得被层4 脏值过滤误吞")
        self.assertEqual(clean.strip(), text.strip())

    def test_legacy_astronomical_age_still_stripped(self):
        """层4 对旧型天文年龄的过滤行为保留 (回归锚)"""
        text = "🔴 [P1] C5_kanban_zombie_worker — t_x(a) 心跳龄29840130min\n修复提示: ..."
        clean, had = self.cms._strip_dirty_age_segments(text)
        self.assertTrue(had)
        self.assertEqual(clean.strip(), "")


if __name__ == "__main__":
    unittest.main()
