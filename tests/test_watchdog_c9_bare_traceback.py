# -*- coding: utf-8 -*-
"""test_watchdog_c9_bare_traceback.py — C9 裸 Traceback 续行误检修复回归 (t_df0af4fa, 2026-10-26 R1 告警层, 老三)

覆盖对象: scripts/sys_watchdog.py check_log_errors 的 continuation 语义三分支:
  ① 带日期且非今日行 → 历史块重置 (旧行为保留)
  ② 无日期前缀裸续行 (Traceback/堆栈/缩进文本) → 保挂起签名, 不重置不冲刷
  ③ 今日日期行 (非 ERROR) → commit-line 冲刷; EOF 冲刷不变

根因 (总管 10-26 三 commit 审查实证): 旧码重置守卫 `if not line.startswith(today)`
把裸 Traceback 续行当"非今日行"重置 → 带堆栈错误签名永远不入基线、永不告警
(gateway.log 220 条裸 ^Traceback 形态下 059215f8 的 EOF 冲刷路径恰好失效)。

任务单 AC1 映射 (机判项):
  ① today+ERROR + 裸 Traceback + today+commit → RUN1 报新签名且 RUN2 静默(双跑收敛)
  ② 历史昨日块+裸行在前不误重置今日挂起
  ③ 原 AC1 双跑 new_sigs=0 不破

纪律: 全部 I/O 走 tmp_path 注入(log_paths/seen_path), 不碰生产 data/ 与 HH 日志;
模块按仓内惯例 importlib 直载 scripts/ 真源, 独立模块名防污染。
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_watchdog():
    spec = importlib.util.spec_from_file_location(
        "sys_watchdog_c9_bare_test_mod", ROOT / "scripts" / "sys_watchdog.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


WG = _load_watchdog()


def _day_offsets(offsets):
    """[0]=今日, [-1]=昨日 ... 的 ISO 日期列表"""
    import datetime as _dt
    today = _dt.date.today()
    return [str(today + _dt.timedelta(days=o)) for o in offsets]


# ---------- AC1① 裸 Traceback 三段日志: RUN1 报新签名 + RUN2 静默(双跑收敛) ----------

def test_bare_traceback_run1_reports_run2_silent(tmp_path):
    day, = _day_offsets([0])
    logf = str(tmp_path / "bare.log")
    seen = str(tmp_path / "seen.json")
    # 卡面探针形态: today+ERROR行 + 裸"Traceback..."行 + today+commit行
    open(logf, "w", encoding="utf-8").write(
        "%s 10:00:00,000 INFO gateway.run: warmup\n"
        "%s 10:00:01,000 ERROR tools.example:kaboom\n"
        "Traceback (most recent call last):\n"
        '  File "example.py", line 7, in <module>\n'
        "%s 10:00:02,000 INFO gateway.run: commit line after\n" % (day, day, day))
    r1 = WG.check_log_errors(log_paths=[logf], seen_path=seen)
    assert r1["status"] == "fail", "裸 Traceback 续行不得重置挂起签名(旧假阴性形态)"
    assert "新错误签名 1 个" in r1["evidence"], r1["evidence"]
    on_disk = json.loads(open(seen, encoding="utf-8").read())
    assert on_disk == ["ERROR tools.example:kaboom"], "挂起签名必须入台账(原文归一化, 不造空格)"
    r2 = WG.check_log_errors(log_paths=[logf], seen_path=seen)
    assert r2["status"] == "ok", "双跑收敛: 第二次必须 new_sigs=0"
    assert "无新错误签名" in r2["evidence"]


def test_bare_traceback_at_eof_flushed(tmp_path):
    # 059215f8 宣称的 EOF 冲刷在裸续行形态下曾失效(裸行先触发 reset): 末段 = ERROR + 裸堆栈 + EOF
    day, = _day_offsets([0])
    logf = str(tmp_path / "bare_eof.log")
    seen = str(tmp_path / "seen_eof.json")
    open(logf, "w", encoding="utf-8").write(
        "%s 23:58:00,000 INFO gateway.run: before\n"
        "%s 23:59:59,001 ERROR tools.edge:eof-boom\n"
        "Traceback (most recent call last):\n"
        '  File "edge.py", line 3, in main\n' % (day, day))
    r1 = WG.check_log_errors(log_paths=[logf], seen_path=seen)
    assert r1["status"] == "fail" and "新错误签名 1 个" in r1["evidence"], r1["evidence"]
    r2 = WG.check_log_errors(log_paths=[logf], seen_path=seen)
    assert r2["status"] == "ok", "EOF 冲刷后第二次不得再报(双跑收敛)"


# ---------- AC1② 历史昨日块 + 裸行在前不误重置今日挂起 ----------

def test_yesterday_block_bare_lines_do_not_reset_today_pending(tmp_path):
    yesterday, today = _day_offsets([-1, 0])
    logf = str(tmp_path / "mixed.log")
    seen = str(tmp_path / "seen_mixed.json")
    open(logf, "w", encoding="utf-8").write(
        # 昨日块: 昨日日期行(含昨日 ERROR) + 昨日裸续行 → 历史块重置, 昨日签名不得入今日基线
        "%s 09:00:00,000 ERROR yesterday.mod: old err\n"
        "Traceback (most recent call last):\n"
        '  File "old.py", line 1, in <module>\n'
        # 今日块: INFO + ERROR + 裸堆栈 + commit 行 → 必须报出且仅 1 个
        "%s 10:00:00,000 INFO gateway.run: today start\n"
        "%s 10:00:01,000 ERROR today.mod: new err\n"
        "Traceback (most recent call last):\n"
        '  File "new.py", line 9, in main\n'
        "%s 10:00:02,000 INFO gateway.run: after\n" % (yesterday, today, today, today))
    r1 = WG.check_log_errors(log_paths=[logf], seen_path=seen)
    assert r1["status"] == "fail"
    on_disk = json.loads(open(seen, encoding="utf-8").read())
    assert on_disk == ["ERROR today.mod: new err"], "只报今日签名 1 条; 昨日块不污染今日基线"
    r2 = WG.check_log_errors(log_paths=[logf], seen_path=seen)
    assert r2["status"] == "ok", "双跑收敛"


def test_bare_lines_before_any_dated_line_are_noop(tmp_path):
    # 文件头部裸行(cur_sig=None 时): 不得产生任何挂起签名/误报
    today, = _day_offsets([0])
    logf = str(tmp_path / "head_bare.log")
    seen = str(tmp_path / "seen_head.json")
    open(logf, "w", encoding="utf-8").write(
        "Traceback (most recent call last):\n"
        '  File "orphan.py", line 1, in <module>\n'
        "%s 10:00:00,000 INFO gateway.run: ok day\n" % today)
    r = WG.check_log_errors(log_paths=[logf], seen_path=seen)
    assert r["status"] == "ok" and "无新错误签名" in r["evidence"], r["evidence"]


# ---------- AC1③ 原 AC1 双跑 new_sigs=0 不破 (纯带日期日志回归护栏) ----------

def test_ac1_dated_only_double_run_second_new_sigs_zero(tmp_path):
    # 与 test_watchdog_c9_normalize.py AC1 同形态(仅时间戳毫秒/conn_id 不同) → 折叠 1 签名;
    # 本卡改动不得破坏带日期行的旧行为
    day, = _day_offsets([0])
    logf = str(tmp_path / "dated.log")
    seen = str(tmp_path / "seen_dated.json")
    open(logf, "w", encoding="utf-8").write(
        "%s 04:55:12,345 ERROR Lark: receive message loop exit, err: no close frame [conn_id=7700737390328286221]\n"
        "%s 04:55:12,346 INFO gateway.run: ws reconnect scheduled\n"
        "%s 05:05:40,221 ERROR Lark: receive message loop exit, err: no close frame [conn_id=8811223344556677888]\n"
        "%s 05:05:40,222 INFO gateway.run: ws reconnect scheduled\n" % ((day,) * 4))
    r1 = WG.check_log_errors(log_paths=[logf], seen_path=seen)
    assert r1["status"] == "fail" and "新错误签名 1 个" in r1["evidence"], r1["evidence"]
    r2 = WG.check_log_errors(log_paths=[logf], seen_path=seen)
    assert r2["status"] == "ok" and "无新错误签名" in r2["evidence"], "原 AC1 双跑 new_sigs=0 不破"
    on_disk = json.loads(open(seen, encoding="utf-8").read())
    assert len(on_disk) == 1 and on_disk[0].endswith("[conn_id=*]")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
