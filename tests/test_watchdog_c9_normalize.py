# -*- coding: utf-8 -*-
"""test_watchdog_c9_normalize.py — C9 签名归一化 + 台账自愈 单测 (t_f630eb92, 2026-10-26 R1 告警层, 老三)

覆盖对象: scripts/sys_watchdog.py 的
  - normalize_error_line (归一化 5 规则)
  - _heal_ledger_entries / load_seen_ledger / save_seen_ledger (台账去重/封顶/迁移/原子写)
  - check_log_errors(log_paths, seen_path) (C9 双跑去重 / 假阴对照组 / EOF 冲刷 / 无新签名=ok)

任务单验收映射:
  AC1 合成日志双跑 → 第二次 new_sigs=0      → test_ac1_double_run_second_new_sigs_zero
  AC2 台账自愈 → 重复行=0、长度≤500         → test_ledger_heal_* 系列
  AC5 归一化 5 规则单测                      → test_rule1..5 + test_normalize_idempotent

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
        "sys_watchdog_c9_test_mod", ROOT / "scripts" / "sys_watchdog.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


WG = _load_watchdog()


# ---------- 归一化 5 规则 (AC5) ----------

def test_rule1_strip_timestamp_prefix():
    line = "2026-10-26 06:32:09,341 ERROR Lark: connect failed, err: HTTPSConnectionPool Max retries"
    assert WG.normalize_error_line(line) == \
        "ERROR Lark: connect failed, err: HTTPSConnectionPool Max retries"


def test_rule1b_strip_timestamp_without_millis():
    # 防御: 无 ,mmm 的秒级时间戳同样剥除
    assert WG.normalize_error_line("2026-10-26 06:32:09 ERROR x: boom") == "ERROR x: boom"


def test_rule2_mask_conn_id():
    line = "ERROR Lark: receive message loop exit, err: no close frame received or sent [conn_id=7700737390328286221]"
    assert WG.normalize_error_line(line) == \
        "ERROR Lark: receive message loop exit, err: no close frame received or sent [conn_id=*]"


def test_rule2b_mask_conn_id_unclosed_bracket():
    # 旧台账 120 字符截断残留 [conn_id=77007 (无闭括号) → 迁移后同样打码为 [conn_id=*]
    assert WG.normalize_error_line("ERROR Lark: x [conn_id=7700737390") == "ERROR Lark: x [conn_id=*]"


def test_rule3_mask_pid():
    line = "ERROR gateway.run: Another gateway instance (PID 9360) started during our startup"
    assert WG.normalize_error_line(line) == \
        "ERROR gateway.run: Another gateway instance (PID *) started during our startup"


def test_rule4_mask_session_id():
    line = "ERROR tools.run: session [20261025_014437_93240b] bootstrap failed"
    assert WG.normalize_error_line(line) == "ERROR tools.run: session [sess_id] bootstrap failed"


def test_rule5_truncate_to_120_after_normalize():
    line = "2026-10-26 06:32:09,341 " + "ERROR " + "A" * 300
    sig = WG.normalize_error_line(line)
    assert len(sig) == 120
    assert sig.startswith("ERROR AAAA")


def test_normalize_idempotent():
    raw = "2026-10-18 05:48:12,331 ERROR Lark: loop exit [conn_id=7700737390328286221]"
    once = WG.normalize_error_line(raw)
    assert WG.normalize_error_line(once) == once


# ---------- 台账自愈 (AC2) ----------

def test_ledger_heal_dedup_preserves_first_occurrence(tmp_path):
    p = tmp_path / "seen.json"
    p.write_text(json.dumps(["ERROR a", "ERROR b", "ERROR a", "ERROR c", "ERROR b"]), encoding="utf-8")
    healed = WG.load_seen_ledger(str(p))
    assert healed == ["ERROR a", "ERROR b", "ERROR c"]
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk == healed, "自愈后必须原子回写落盘"


def test_ledger_heal_cap_500_trims_oldest(tmp_path):
    p = tmp_path / "seen.json"
    entries = ["ERROR uniq-%d" % i for i in range(600)]
    p.write_text(json.dumps(entries), encoding="utf-8")
    healed = WG.load_seen_ledger(str(p))
    assert len(healed) == 500
    assert healed == entries[-500:], "超封顶裁最旧(前部)"
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert len(on_disk) == 500


def test_ledger_heal_migrates_legacy_raw_lines(tmp_path):
    # 存量原始行(时间戳+conn_id+PID) → 归一化迁移; 同类仅可变项不同者折叠为 1 条
    p = tmp_path / "seen.json"
    entries = [
        "2026-10-18 05:48:12,331 ERROR Lark: loop exit [conn_id=7700737390328286221]",
        "2026-10-19 05:48:12,332 ERROR Lark: loop exit [conn_id=8811223344556677888]",
        "2026-10-15 02:52:56,758 ERROR gateway.run: Another gateway instance (PID 9360) started",
    ]
    p.write_text(json.dumps(entries), encoding="utf-8")
    healed = WG.load_seen_ledger(str(p))
    assert len(healed) == 2
    assert healed[0] == "ERROR Lark: loop exit [conn_id=*]"
    assert healed[1] == "ERROR gateway.run: Another gateway instance (PID *) started"


def test_ledger_heal_junk_entries_loud_not_silent(tmp_path, capsys):
    p = tmp_path / "seen.json"
    p.write_text(json.dumps(["ERROR good", 123, "", None, "ERROR good"]), encoding="utf-8")
    healed = WG.load_seen_ledger(str(p))
    assert healed == ["ERROR good"]
    err = capsys.readouterr().err
    assert "非字符串" in err and "丢弃" in err, "垃圾条目必须 loud 报出(禁静默吞噬)"


def test_ledger_missing_returns_empty(tmp_path):
    assert WG.load_seen_ledger(str(tmp_path / "absent.json")) == []


def test_ledger_non_array_kept_as_evidence(tmp_path, capsys):
    p = tmp_path / "seen.json"
    p.write_text(json.dumps({"weird": "dict"}), encoding="utf-8")
    healed = WG.load_seen_ledger(str(p))
    assert healed == []
    assert json.loads(p.read_text(encoding="utf-8")) == {"weird": "dict"}, "非数组台账不得覆盖, 保留证据"
    assert "非 JSON 数组" in capsys.readouterr().err


def test_ledger_stays_json_array_format(tmp_path):
    p = tmp_path / "seen.json"
    p.write_text(json.dumps(["ERROR a", "ERROR b"]), encoding="utf-8")
    # save 契约 = 对传入 entries 做去重/封顶/归一化后整体原子写(合并责任在调用方, 见 check_log_errors)
    out = WG.save_seen_ledger(["ERROR b", "ERROR c"], str(p))
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(on_disk, list), "必须保持 JSON 数组格式"
    assert on_disk == out == ["ERROR b", "ERROR c"]


# ---------- C9 双跑去重 (AC1) ----------

def _write_synthetic_log(tmp_path, name, day, conn_ids=None):
    """两条'仅时间戳毫秒/conn_id 不同'的 ERROR 行 + 各自触发提交的后续行"""
    conn_ids = conn_ids or ["7700737390328286221", "8811223344556677888"]
    p = tmp_path / name
    p.write_text(
        "%s 04:55:12,345 ERROR Lark: receive message loop exit, err: no close frame [conn_id=%s]\n"
        "%s 04:55:12,346 INFO gateway.run: ws reconnect scheduled\n"
        "%s 05:05:40,221 ERROR Lark: receive message loop exit, err: no close frame [conn_id=%s]\n"
        "%s 05:05:40,222 INFO gateway.run: ws reconnect scheduled\n"
        % (day, conn_ids[0], day, day, conn_ids[1], day),
        encoding="utf-8")
    return str(p)


def test_ac1_double_run_second_new_sigs_zero(tmp_path):
    day = WG.dt.date.today().isoformat()
    logf = _write_synthetic_log(tmp_path, "syn.log", day)
    seen = str(tmp_path / "seen.json")
    r1 = WG.check_log_errors(log_paths=[logf], seen_path=seen)
    assert r1["status"] == "fail"
    assert "新错误签名 1 个" in r1["evidence"], "两行仅 conn_id/毫秒不同 → 折叠为 1 个签名"
    r2 = WG.check_log_errors(log_paths=[logf], seen_path=seen)
    assert r2["status"] == "ok", "第二次必须 new_sigs=0(去重生效)"
    assert "无新错误签名" in r2["evidence"]
    on_disk = json.loads(open(seen, encoding="utf-8").read())
    assert len(on_disk) == 1 and on_disk[0].endswith("[conn_id=*]")


def test_c9_cross_file_same_error_deduped(tmp_path):
    # 同一错误出现在两个日志文件 → 台账只记 1 条(旧码双文件各自 append 产生重复行)
    day = WG.dt.date.today().isoformat()
    f1 = _write_synthetic_log(tmp_path, "g.log", day)
    f2 = _write_synthetic_log(tmp_path, "a.log", day)
    seen = str(tmp_path / "seen2.json")
    r = WG.check_log_errors(log_paths=[f1, f2], seen_path=seen)
    assert "新错误签名 1 个" in r["evidence"]
    on_disk = json.loads(open(seen, encoding="utf-8").read())
    assert len(on_disk) == 1, "跨文件同错必须消重"


def test_c9_truly_new_error_still_reported(tmp_path):
    # 假阴对照组: 合成已知新错误行(台账中没有)必须命中 P1
    day = WG.dt.date.today().isoformat()
    logf = str(tmp_path / "new_err.log")
    seen = str(tmp_path / "seen3.json")
    open(seen, "w", encoding="utf-8").write(json.dumps(["ERROR Lark: known old err [conn_id=*]"]))
    open(logf, "w", encoding="utf-8").write(
        "%s 09:00:00,000 ERROR totally_new_module: brand new failure mode xyz-12345\n"
        "%s 09:00:00,001 INFO gateway.run: after\n" % (day, day))
    r = WG.check_log_errors(log_paths=[logf], seen_path=seen)
    assert r["status"] == "fail"
    assert "新错误签名 1 个" in r["evidence"]
    assert "totally_new_module" in r["evidence"], "真新错误不得漏报"


def test_c9_no_new_sig_returns_ok_without_fix_hint(tmp_path):
    day = WG.dt.date.today().isoformat()
    logf = _write_synthetic_log(tmp_path, "syn_ok.log", day)
    seen = str(tmp_path / "seen4.json")
    WG.check_log_errors(log_paths=[logf], seen_path=seen)
    r2 = WG.check_log_errors(log_paths=[logf], seen_path=seen)
    assert r2["status"] == "ok" and "fix_hint" not in r2, "无新签名 C9=ok(入队门=main() 仅对 fail 入队)"
    assert r2["level"] == "P1", "严重级保持不变"


def test_c9_eof_pending_signature_flushed(tmp_path):
    # 日志以 ERROR 行结尾(最后一行, 无后续提交行): 旧码挂起签名永不入台账 → 每轮再报新;
    # 新码 EOF 冲刷。注: 无时间戳 Traceback 行在 loop 内会触发 reset 分支(原始行为, 不在本次范围)。
    day = WG.dt.date.today().isoformat()
    logf = str(tmp_path / "eof.log")
    seen = str(tmp_path / "seen5.json")
    open(logf, "w", encoding="utf-8").write(
        "%s 23:59:57,000 INFO gateway.run: before\n"
        "%s 23:59:58,001 ERROR tools.legacy: boom\n" % (day, day))
    r1 = WG.check_log_errors(log_paths=[logf], seen_path=seen)
    assert r1["status"] == "fail"
    r2 = WG.check_log_errors(log_paths=[logf], seen_path=seen)
    assert r2["status"] == "ok", "EOF 冲刷后第二次不得再报"
    on_disk = json.loads(open(seen, encoding="utf-8").read())
    assert on_disk == ["ERROR tools.legacy: boom"]


def test_c9_missing_log_paths_ok_zero_scanned(tmp_path):
    r = WG.check_log_errors(log_paths=[str(tmp_path / "absent.log")],
                            seen_path=str(tmp_path / "seen6.json"))
    assert r["status"] == "ok" and "今日无日志行" in r["evidence"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
