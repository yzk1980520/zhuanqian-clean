"""t_cd7dab36: data_flow_audit 告警读侧契约测试（§4.1-12 读侧断言登记配套机判件）。

写侧契约（对齐 cron_message_sender._render_content L334-346 只认 content/msg/title+body）：
- 队列条目以 `content`（非空字符串，"[level] message" 格式）为唯一渲染源，旧裸 `message` 字段已弃用；
- payload = top-20 孤儿样本 + orphan_count 总数（_orphan_payload），禁止整表（19k 项 ≈1.2MB/条）入队，
  单条序列化 <8KB；
- P2 孤儿生产者告警仅在 SC-005 判据未显式通过时触发（pass=True 静默；判据版本缺失/无法判定 → 保守告警）；
- P0 孤儿消费者告警维持原触发（真实数据流缺陷），payload 同步紧凑化。
读侧 = QSP_MsgDrain（5 分钟计划任务）；失败路径 = data/drain_dead_letter.jsonl 死信 +
积压 P0 阈值（cron_message_sender BACKLOG_THRESHOLD=10）。

本文件全部为单元/合成场景断言：monkeypatch 注入临时 MSG_QUEUE 与临时台账/数据目录，
自动复原，不写真实台账、不真发飞书。
"""

import json
import sys
from pathlib import Path

import pytest

PROJ_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJ_ROOT / "scripts"


def _import_dfa():
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import data_flow_audit
    except ModuleNotFoundError:
        pytest.skip("data_flow_audit.py not yet implemented (RED phase)")
    return data_flow_audit


def _import_cms():
    if str(PROJ_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJ_ROOT))
    import cron_message_sender
    return cron_message_sender


# ---------------------------------------------------------------- 契约 1: content 字段

def test_write_alert_content_contract(tmp_path, monkeypatch):
    """write_alert 产出条目：content 非空字符串（"[level] message" 格式），
    读侧 _render_content 返回 ok=True；旧裸 message 字段不复存在。"""
    dfa = _import_dfa()
    queue = tmp_path / "message_queue.json"
    monkeypatch.setattr(dfa, "MSG_QUEUE", queue)

    dfa.write_alert("P2", "数据流审计发现 3 个孤儿生产者",
                    {"orphan_count": 3, "orphan_kind": "orphan_producer", "orphan_samples": []})

    items = json.loads(queue.read_text(encoding="utf-8"))
    assert len(items) == 1
    entry = items[0]
    assert entry["type"] == "data_flow_audit"
    assert entry["level"] == "P2"
    content = entry.get("content")
    assert isinstance(content, str) and content.strip(), "content 必须为非空字符串"
    assert content.startswith("[P2] ")
    assert "message" not in entry, "旧裸 message 字段必须弃用（读侧不认）"

    cms = _import_cms()
    ok, text = cms._render_content(entry)
    assert ok is True, "_render_content 对 data_flow_audit 条目必须可渲染（杜绝 unrenderable 死信）"
    assert text.strip() == content


def test_write_alert_p0_content_contract(tmp_path, monkeypatch):
    """P0 告警条目同契约：content 渲染源 + _render_content ok=True。"""
    dfa = _import_dfa()
    queue = tmp_path / "message_queue.json"
    monkeypatch.setattr(dfa, "MSG_QUEUE", queue)

    dfa.write_alert("P0", "数据流审计发现 2 个孤儿消费者",
                    dfa._orphan_payload(["/nonexistent/x.json", "/nonexistent/y.json"], "orphan_consumer"))

    entry = json.loads(queue.read_text(encoding="utf-8"))[0]
    assert entry["content"].startswith("[P0] ")
    ok, text = _import_cms()._render_content(entry)
    assert ok is True and text.strip()


# ---------------------------------------------------------------- 契约 2: payload 紧凑化

def test_orphan_payload_top20_and_count():
    """_orphan_payload：top-20 样本 + orphan_count 总数，整表不入队。"""
    dfa = _import_dfa()
    items = [f"data/orphan_probe_{i:05d}.json" for i in range(19340)]
    payload = dfa._orphan_payload(items, "orphan_producer")
    assert payload["orphan_count"] == 19340
    assert payload["orphan_kind"] == "orphan_producer"
    assert payload["orphan_samples"] == items[:20]
    assert len(payload["orphan_samples"]) == 20


def test_write_alert_payload_under_8kb(tmp_path, monkeypatch):
    """单条队列条目序列化 <8KB（旧实现 1.2MB/条 → 队列膨胀+死信风暴根因）。"""
    dfa = _import_dfa()
    queue = tmp_path / "message_queue.json"
    monkeypatch.setattr(dfa, "MSG_QUEUE", queue)

    items = [f"data/contract_asset_orphan_{i:05d}.json" for i in range(19340)]
    dfa.write_alert("P2", f"数据流审计发现 {len(items)} 个孤儿生产者",
                    dfa._orphan_payload(items, "orphan_producer"))

    entry = json.loads(queue.read_text(encoding="utf-8"))[0]
    serialized = json.dumps(entry, ensure_ascii=False).encode("utf-8")
    assert len(serialized) < 8 * 1024, f"payload {len(serialized)}B 超 8KB 上限"
    assert entry["orphan_count"] == 19340
    assert len(entry["orphan_samples"]) == 20


# ---------------------------------------------------------------- 契约 3: P2 触发判定（pass 静默）

def test_should_alert_orphan_producers_table():
    """P2 触发判定表：仅判据未显式通过时告警。"""
    dfa = _import_dfa()
    f = dfa.should_alert_orphan_producers
    assert f({"judgment_version": "SC-005-criterion-v2", "pass": True}) is False, "pass=True 必须静默"
    assert f({"judgment_version": "SC-005-criterion-v2", "pass": False}) is True, "pass=False 必须告警"
    assert f({"judgment_version": None, "pass": None}) is True, "判据版本缺失（未生效）保守告警"
    assert f({"judgment_version": "SC-005-criterion-v2", "pass": None}) is True, "无法判定（分母=0 等）保守告警"
    assert f({}) is True
    assert f(None) is True


def test_main_silent_when_judgment_pass(tmp_path, monkeypatch):
    """AC1 场景：判据 pass=True 态 main() → 队列无新增 data_flow_audit 条目（静默验证）。"""
    dfa = _import_dfa()
    queue = tmp_path / "message_queue.json"
    monkeypatch.setattr(dfa, "MSG_QUEUE", queue)
    report = {
        "scanned_at": "2026-10-26T00:00:00+00:00",
        "status": "degraded",
        "orphan_producers": [f"data/contract_asset_orphan_{i:02d}.json" for i in range(30)],
        "orphan_consumers": [],
        "nodes": [],
        "buckets": {
            "judgment": {"judgment_version": "SC-005-criterion-v2", "pass": True,
                         "denominator": 173, "numerator": 6, "orphan_rate": 0.0347,
                         "post_gc_expected": {"numerator": 2, "orphan_rate": 0.0115, "pass": True}},
            "contract_assets": {"files": 100, "orphans": 30, "orphan_rate": 0.3},
        },
    }
    monkeypatch.setattr(dfa, "run_audit", lambda: report)
    monkeypatch.setattr(dfa, "write_report", lambda r: None)

    assert dfa.main() == 0
    assert not queue.exists(), "pass=True 态不得向队列写任何 data_flow_audit 条目"


def test_main_alerts_when_judgment_fail(tmp_path, monkeypatch):
    """AC2 场景（判据不过）：main() 写 1 条 P2，content 可渲染、payload 紧凑、top-20 截断。"""
    dfa = _import_dfa()
    queue = tmp_path / "message_queue.json"
    monkeypatch.setattr(dfa, "MSG_QUEUE", queue)
    orphans = [f"data/contract_asset_orphan_{i:02d}.json" for i in range(30)]
    report = {
        "scanned_at": "2026-10-26T00:00:00+00:00",
        "status": "degraded",
        "orphan_producers": orphans,
        "orphan_consumers": [],
        "nodes": [],
        "buckets": {
            "judgment": {"judgment_version": "SC-005-criterion-v2", "pass": False,
                         "denominator": 173, "numerator": 120, "orphan_rate": 0.6936,
                         "post_gc_expected": {"numerator": 60, "orphan_rate": 0.347, "pass": False}},
            "contract_assets": {"files": 100, "orphans": 30, "orphan_rate": 0.3},
        },
    }
    monkeypatch.setattr(dfa, "run_audit", lambda: report)
    monkeypatch.setattr(dfa, "write_report", lambda r: None)

    assert dfa.main() == 0
    items = json.loads(queue.read_text(encoding="utf-8"))
    assert len(items) == 1, "判据不过 + 无孤儿消费者 → 恰好 1 条 P2"
    entry = items[0]
    assert entry["level"] == "P2" and entry["type"] == "data_flow_audit"
    assert isinstance(entry["content"], str) and entry["content"].startswith("[P2] ")
    assert entry["orphan_count"] == 30
    assert entry["orphan_samples"] == orphans[:20] and len(entry["orphan_samples"]) == 20
    ok, text = _import_cms()._render_content(entry)
    assert ok is True and text.strip()
    assert len(json.dumps(entry, ensure_ascii=False).encode("utf-8")) < 8 * 1024


def test_main_alerts_on_real_failed_ledger(tmp_path, monkeypatch):
    """AC2 端到端（临时台账/数据目录，测后自动复原，不碰真实台账）：
    真实 run_audit(temp data_dir, temp 台账) 判据不过 → main() 写 P2 入队列。"""
    dfa = _import_dfa()
    data_dir = tmp_path / "data"
    (data_dir / "assets").mkdir(parents=True)
    # 1 个稳定命名契约资产孤儿文件（scripts/ 无引用 → orphan_producer）
    (data_dir / "assets" / "stable_contract_asset_x1.json").write_text("{}", encoding="utf-8")
    # 台账：该文件归 (b) GC 待执行 → 物理仍在树中 → 计入分子；判据不过（N/D=1/4=25% ≥ 5%）
    ledger_path = tmp_path / "sc005_orphan_ledger.json"
    ledger_path.write_text(json.dumps({
        "judgment_version": "test-fail-scenario-v2",
        "items": [{"file": "assets/stable_contract_asset_x1.json", "disposition": "b"}],
    }), encoding="utf-8")

    queue = tmp_path / "message_queue.json"
    monkeypatch.setattr(dfa, "MSG_QUEUE", queue)
    orig_run_audit = dfa.run_audit
    monkeypatch.setattr(dfa, "run_audit",
                        lambda: orig_run_audit(data_dir=data_dir, ledger_path=ledger_path))
    monkeypatch.setattr(dfa, "write_report", lambda r: None)

    assert dfa.main() == 0
    items = json.loads(queue.read_text(encoding="utf-8"))
    assert len(items) == 1
    entry = items[0]
    assert entry["level"] == "P2"
    assert isinstance(entry["content"], str) and entry["content"].startswith("[P2] ")
    ok, _ = _import_cms()._render_content(entry)
    assert ok is True
    assert entry["orphan_count"] == 1
    assert "stable_contract_asset_x1.json" in entry["orphan_samples"][0]


def test_main_p0_orphan_consumer_compact(tmp_path, monkeypatch):
    """P0 孤儿消费者告警：payload 同步紧凑化（top-20 + orphan_count），content 可渲染。"""
    dfa = _import_dfa()
    queue = tmp_path / "message_queue.json"
    monkeypatch.setattr(dfa, "MSG_QUEUE", queue)
    consumers = [f"/nonexistent/data/probe_{i:02d}.json" for i in range(50)]
    report = {
        "scanned_at": "2026-10-26T00:00:00+00:00",
        "status": "degraded",
        "orphan_producers": [],
        "orphan_consumers": consumers,
        "nodes": [],
        "buckets": {
            "judgment": {"judgment_version": "SC-005-criterion-v2", "pass": True,
                         "denominator": 173, "numerator": 6, "orphan_rate": 0.0347,
                         "post_gc_expected": {"numerator": 2, "orphan_rate": 0.0115, "pass": True}},
            "contract_assets": {"files": 100, "orphans": 0, "orphan_rate": 0.0},
        },
    }
    monkeypatch.setattr(dfa, "run_audit", lambda: report)
    monkeypatch.setattr(dfa, "write_report", lambda r: None)

    assert dfa.main() == 0
    items = json.loads(queue.read_text(encoding="utf-8"))
    assert len(items) == 1, "P0 孤儿消费者不受判据 pass 状态影响，必须告警"
    entry = items[0]
    assert entry["level"] == "P0"
    assert entry["orphan_count"] == 50
    assert entry["orphan_kind"] == "orphan_consumer"
    assert entry["orphan_samples"] == consumers[:20]
    ok, _ = _import_cms()._render_content(entry)
    assert ok is True
    assert len(json.dumps(entry, ensure_ascii=False).encode("utf-8")) < 8 * 1024
