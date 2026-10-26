# -*- coding: utf-8 -*-
"""test_suppress_priority_layering.py — 告警抑制「优先级分层」行为级测试

背景 (为什么必须有这个文件):
  cron_message_sender.py (QSP_MsgDrain 每 5 分钟驱动) 的抑制窗口按优先级分层:
    P0 = SUPPRESS_WINDOW_P0_MIN (10min) | P1 = SUPPRESS_WINDOW_P1_MIN (30min)
    P2 及以下 = SUPPRESS_WINDOW_MIN (60min, 旧行为)
  该实现 10-20 回滚丢失, 10-21 自 archive 回灌 (commit 1a428b9b)。

  既有防线只有 scripts/guard_assertion_effectiveness.py 的 G6/G7 **源码正则**:
    G6 只查 SUPPRESS_WINDOW_P0_MIN < SUPPRESS_WINDOW_MIN (数值大小);
    G7 只查 "_priority_of" 与 'skey = prio + "#" + _suppress_key' 字样存在。
  → 典型「伪分层」可同时骗过正则和人: 把 P0 窗口从 10 改成 59,
    G6 仍绿 (59 < 60), 但 P0 紧急告警会被压 59 分钟 —— 分层名存实亡,
    正是本项目头号病史「过滤器存在但静默不生效」的活样本。只有行为测试能抓。

本文件四组防线 (对应任务书四项必覆盖):
  1. TestPriorityWindowValues      —— _priority_window_min() 对 P0/P1/P2/无优先级
                                     分别返回 10/30/60/60, 且 P0 必须「显著」小于 P2;
  2. TestPriorityOfExtraction      —— _priority_of() 提取正确, 覆盖 emoji 前缀场景
                                     (G7 动因: 文本带 emoji 时 _suppress_key 会退化);
  3. TestSuppressKeyPriorityPrefix —— 抑制键含优先级前缀, 同文本不同优先级不得互抑;
  4. TestP0ActualSuppressDuration  —— 集成级 (真调 drain_queue): P0 的实际抑制时长
                                     是 10 分钟量级而不是 60 分钟 (最关键一条)。
  5. TestSuppressStateEdgeCases    —— 边界/异常: 状态文件损坏、非 dict、空/缺队列。

实现要点 (安全边界):
  - 只做纯函数级 / 状态文件级测试; drain_queue 的 send_with_fallback 被替换为
    记录器, **绝不真发飞书**; 队列/抑制状态/死信全部注入 tempfile, 不碰生产 data/。
  - 抑制时间戳按「距 now N 分钟」预置, drain_queue 内部用 now 与窗口比较,
    分钟级窗口下毫秒级执行延迟无感知。

降级自证 (2026-10-21, 见交付报告):
  绿 → 把根 cron_message_sender.py 的 SUPPRESS_WINDOW_P0_MIN 从 10 改成 59
  (伪分层) → 本文件 P0 相关用例转红 → 备份还原 → 回绿; 还原后 git diff 为空。
"""
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_cms():
    """按文件路径加载 cron_message_sender (与 tests/test_ops2_write_side.py 同式,
    独立模块名避免与其它测试文件的导入互相污染)。"""
    spec = importlib.util.spec_from_file_location(
        "cms_suppress_priority_test", ROOT / "cron_message_sender.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CMS = _load_cms()


def _compose_skey(mod, msg):
    """按 drain_queue() 内部的真实组合方式复现抑制键 (L442-443):
        prio = _priority_of(msg)
        clean = _strip_dirty_age_segments(_render_content(msg)[1])[0]
        skey = prio + "#" + _suppress_key(clean)
    测试需要预置/核对抑制状态, 必须与生产组合方式逐字一致, 否则测的是空气。"""
    ok, text = mod._render_content(msg)
    assert ok, "测试消息必须可渲染 (层2 契约)"
    clean, _had_dirty = mod._strip_dirty_age_segments(text)
    return mod._priority_of(msg) + "#" + mod._suppress_key(clean)


def _seed(skey, age_min):
    """构造「skey 在 age_min 分钟前投递过」的抑制状态片段。"""
    return {skey: datetime.now().timestamp() - age_min * 60}


# ---------------------------------------------------------------- 组1: 窗口分层值
class TestPriorityWindowValues:
    """_priority_window_min(msg) 签名实为 (msg: dict) —— 从 priority/severity 字段取值,
    不是 (priority_str)。本组钉死分层数值: 伪分层 (P0=59) 会在这里第一条转红。"""

    def test_p0_window_is_10_min(self):
        # 为什么测这个: 10-19 断裂3 的修复目标就是「P0 只做最小去重(10min)」。
        # 若被改成 59 (正则 G6 仍绿), P0 告警被压 59 分钟, 资金安全系统不接受。
        assert CMS._priority_window_min({"priority": "P0"}) == 10

    def test_p1_window_is_30_min(self):
        assert CMS._priority_window_min({"priority": "P1"}) == 30

    def test_p2_window_is_60_min(self):
        assert CMS._priority_window_min({"priority": "P2"}) == 60

    def test_missing_priority_defaults_to_60(self):
        # 无优先级 = 旧行为 60min (P2 兜底), 不是 0 (不抑制) 也不是 10 (过紧)
        assert CMS._priority_window_min({}) == 60
        assert CMS._priority_window_min({"content": "没有优先级字段的消息"}) == 60

    def test_severity_alias_used(self):
        # severity 是 priority 的别名 (写侧契约两种字段都有人用)
        assert CMS._priority_window_min({"severity": "P0"}) == 10
        assert CMS._priority_window_min({"severity": "P1"}) == 30
        assert CMS._priority_window_min({"severity": "P2"}) == 60

    def test_case_and_space_normalized(self):
        # 边界: 大小写/空白不得影响分层 (否则 " p0 " 会掉到 60min 分支)
        assert CMS._priority_window_min({"priority": " p0 "}) == 10
        assert CMS._priority_window_min({"priority": "p1"}) == 30

    def test_priority_field_wins_over_severity(self):
        # or 链顺序: priority 优先于 severity。防有人调换顺序导致显式 priority 被
        # severity 覆盖 (P0 消息带 severity=P2 时被压 60min)。
        assert CMS._priority_window_min({"priority": "P0", "severity": "P2"}) == 10

    def test_unknown_priority_falls_to_60(self):
        # 异常: 未知优先级 (P3/空串/None) 不得抛错, 按 P2 兜底 60min
        assert CMS._priority_window_min({"priority": "P3"}) == 60
        assert CMS._priority_window_min({"priority": ""}) == 60
        assert CMS._priority_window_min({"priority": None}) == 60

    def test_p0_significantly_less_than_p2(self):
        # 与 G6 判据的行为级镜像, 且更严: G6 只查 P0 < P2 (59 < 60 也过 = 伪分层),
        # 这里要求 P0 <= P2/2 ——「显著小于」才配叫分层, 10 <= 30 过, 59 不过。
        p0 = CMS._priority_window_min({"priority": "P0"})
        p2 = CMS._priority_window_min({"priority": "P2"})
        assert p0 < p2
        assert p0 <= p2 // 2, f"P0 窗口 {p0}min 未显著小于 P2 {p2}min (伪分层)"

    def test_window_monotonic_p0_lt_p1_lt_p2(self):
        # 分层单调性: 紧急程度越高窗口越短。防「P1 比 P0 还短」的倒序分层。
        p0 = CMS._priority_window_min({"priority": "P0"})
        p1 = CMS._priority_window_min({"priority": "P1"})
        p2 = CMS._priority_window_min({"priority": "P2"})
        assert p0 < p1 < p2


# ---------------------------------------------------------------- 组2: 优先级提取
class TestPriorityOfExtraction:
    """_priority_of(msg) 同样收 (msg: dict)。G7 的动因是 emoji 前缀消息的文本解析
    退化, 但 dict 里的 priority 字段不受影响 —— 本组同时钉死两层。"""

    def test_plain_p0_p1_p2(self):
        assert CMS._priority_of({"priority": "P0"}) == "P0"
        assert CMS._priority_of({"priority": "P1"}) == "P1"
        assert CMS._priority_of({"priority": "P2"}) == "P2"

    def test_missing_defaults_p2(self):
        assert CMS._priority_of({}) == "P2"
        assert CMS._priority_of({"content": "🔴 [P0] 只有文本带优先级"}) == "P2"

    def test_normalization(self):
        assert CMS._priority_of({"priority": " p1 "}) == "P1"
        assert CMS._priority_of({"severity": "p0"}) == "P0"

    def test_emoji_prefixed_p0_p1_p2(self):
        # G7 动因场景: 消息文本带 emoji 前缀 (🚨 [P0]…)。早期实现从**文本**解析
        # 优先级, emoji 导致解析失败退化成无优先级 → P0 被当 P2 压 60min。
        # 现行实现从 dict 字段取, 必须对 emoji 前缀消息同样正确。
        cases = [("🔴", "P0"), ("🟠", "P1"), ("🟡", "P2"),
                 ("🚨", "P0"), ("⚠️", "P1")]
        for emoji, prio in cases:
            msg = {"priority": prio,
                   "content": "%s [%s] gitsync_check 演示消息" % (emoji, prio)}
            assert CMS._priority_of(msg) == prio, "emoji=%s" % emoji

    def test_emoji_prefixed_severity_alias(self):
        msg = {"severity": "P0", "content": "🔴 [P0] gitsync_check 演示消息"}
        assert CMS._priority_of(msg) == "P0"

    def test_window_for_emoji_prefixed_p0_is_10(self):
        # 端到端钉死历史坑: emoji 前缀 + dict priority=P0 → 窗口仍是 10 而非 60。
        # 若 _priority_of 改成从文本解析, 这条会红 (文本解析对 emoji 退化)。
        msg = {"priority": "P0", "content": "🔴 [P0] gitsync_check 环断裂"}
        assert CMS._priority_window_min(msg) == 10


# ---------------------------------------------------------------- 组3: 抑制键优先级前缀
class TestSuppressKeyPriorityPrefix:
    """drain_queue: skey = prio + "#" + _suppress_key(clean)。
    prio 前缀是 load-bearing 的: 没有它, 同文本不同优先级共享同一把键,
    P0 的告警会被 P2 的抑制状态挡住 (或反之) —— 这正是 G7 要防的。"""

    TEXT = "[P0] gitsync_check 代码同步环断裂"

    def _msg(self, prio, mid="m1"):
        return {"id": mid, "priority": prio, "content": self.TEXT}

    def test_same_text_different_priority_different_skey(self):
        # 核心断言: 同文本不同优先级 → 不同抑制键 → 不跨级互相抑制
        k_p0 = _compose_skey(CMS, self._msg("P0", "a"))
        k_p2 = _compose_skey(CMS, self._msg("P2", "b"))
        assert k_p0.startswith("P0#")
        assert k_p2.startswith("P2#")
        assert k_p0 != k_p2

    def test_all_priority_pairs_produce_distinct_keys(self):
        keys = {p: _compose_skey(CMS, self._msg(p, "id-" + p))
                for p in ("P0", "P1", "P2")}
        assert len(set(keys.values())) == 3

    def test_emoji_prefixed_keys_also_differ(self):
        # 历史坑复现: emoji 前缀使 _suppress_key 走 plain| 分支 (文本解析退化),
        # 此时键的「优先级信息」完全来自 skey 的 prio 前缀。若前缀被删,
        # P0/P2 的键会逐字相同 → P0 被 P2 噪音压 60min。
        text = "🔴 [P0] gitsync_check 代码同步环断裂"
        k_p0 = _compose_skey(CMS, {"id": "a", "priority": "P0", "content": text})
        k_p2 = _compose_skey(CMS, {"id": "b", "priority": "P2", "content": text})
        # 先确认文本解析确实退化 (plain| 分支), 否则本用例的场景不成立
        assert CMS._suppress_key(text).startswith("plain|")
        assert k_p0 == "P0#plain|" + text
        assert k_p0 != k_p2

    def test_suppress_key_is_text_only_so_prefix_is_load_bearing(self):
        # 特征化断言 (文档化失效模式, 使上几条的非空性可验证):
        # _suppress_key 只吃文本、不认识优先级 —— 同样文本必然得到同样的键。
        # 这就是「旧实现 (skey 无 prio 前缀) 下同文本跨优先级必然互互相抑制」
        # 的根因; 若未来 _suppress_key 自身开始区分优先级, 本断言仍成立
        # (它只陈述 text-only 这一事实), 而 drain_queue 的前缀组合仍受
        # test_same_text_different_priority_different_skey 保护。
        text = "🔴 [P0] gitsync_check 代码同步环断裂"
        assert CMS._suppress_key(text) == CMS._suppress_key(text)

    def test_suppress_key_parses_plain_alert_line(self):
        # 无 emoji 时 _suppress_key 仍走 [Pn]|checker| 分支 (回归锚)
        k = CMS._suppress_key(self.TEXT)
        assert k.startswith("[P0]|gitsync_check|")


# ---------------------------------------------------------------- 组4: 集成级 (drain_queue)
@pytest.fixture
def drain_env(tmp_path, monkeypatch):
    """隔离的 drain 环境: 队列/抑制状态/死信全部指到 tmp_path;
    send_with_fallback 换成记录器 (只记录文本, 返回 True) —— 绝不真发飞书。"""
    mod = _load_cms()
    env = SimpleNamespace(
        mod=mod,
        queue=tmp_path / "message_queue.json",
        sup=tmp_path / "drain_suppress_state.json",
        dead=tmp_path / "drain_dead_letter.jsonl",
        sent=[],
    )
    monkeypatch.setattr(mod, "QUEUE_FILE", str(env.queue))
    monkeypatch.setattr(mod, "SUPPRESS_STATE", str(env.sup))
    monkeypatch.setattr(mod, "DEAD_LETTER", str(env.dead))
    monkeypatch.setattr(
        mod, "send_with_fallback",
        lambda text: (env.sent.append(text), True)[1])
    return env


def _run_drain(env, messages, seed_state=None):
    """写队列 → (可选) 预置抑制状态 → 跑真 drain_queue → 返回四元组。"""
    env.queue.write_text(json.dumps(messages, ensure_ascii=False), encoding="utf-8")
    if seed_state is not None:
        env.sup.write_text(json.dumps(seed_state, ensure_ascii=False), encoding="utf-8")
    elif env.sup.exists():
        env.sup.unlink()
    sent, fail, stats = env.mod.drain_queue()
    remaining = json.loads(env.queue.read_text(encoding="utf-8"))
    return sent, fail, stats, remaining


_ZERO_STATS = {"unrenderable": 0, "dirty_only": 0, "suppressed": 0}


class TestP0ActualSuppressDuration:
    """最关键一组: 经真 drain_queue 验证「P0 的实际抑制时长 = 10 分钟量级」。
    实现方式: 预置抑制状态 (skey → now-Nmin), 让 drain_queue 用自己的
    _priority_window_min 与时间戳比较; send_with_fallback 记录是否真投递。
    G6 正则抓不到的伪分层 (P0=59) 会在这里转红: 11min < 59min → 被误抑制。"""

    TEXT = "[P0] gitsync_check 代码同步环断裂"
    MSG = {"id": "gitsync-1", "priority": "P0", "content": TEXT}

    def test_p0_redelivered_after_11_min(self, drain_env):
        # 11min > P0 窗口(10min): 必须放行重发。伪分层 (59min) / 旧行为 (60min) 下
        # 这条会被压住 → sent=0 → 红。这是「P0 不被过度抑制」的主断言。
        skey = _compose_skey(drain_env.mod, self.MSG)
        sent, fail, stats, remaining = _run_drain(
            drain_env, [self.MSG], seed_state=_seed(skey, 11))
        assert (sent, fail) == (1, 0), stats
        assert stats["suppressed"] == 0
        assert len(drain_env.sent) == 1  # 记录器收到了投递文本
        assert remaining == []           # 已投递条目移出队列

    def test_p0_suppressed_within_10_min(self, drain_env):
        # 反向边界: 9min < 10min 仍须抑制 (防「只测放行」掩盖窗口被改成 0 的退化),
        # 且抑制条目保留队列、窗口过后再发 (层4 语义)。
        skey = _compose_skey(drain_env.mod, self.MSG)
        sent, fail, stats, remaining = _run_drain(
            drain_env, [self.MSG], seed_state=_seed(skey, 9))
        assert (sent, fail) == (0, 0)
        assert stats["suppressed"] == 1
        assert len(remaining) == 1
        assert drain_env.sent == []

    def test_p2_still_suppressed_at_11_min(self, drain_env):
        # 同一时间尺度 (11min) 下 P2 必须仍被 60min 窗口压住 —— 证明 P0 放行不是
        # 「窗口整体失效」, 而是分层真生效 (防有人把 60min 一律改成 10min 降噪)。
        msg = dict(self.MSG, id="p2-1", priority="P2")
        skey = _compose_skey(drain_env.mod, msg)
        sent, fail, stats, remaining = _run_drain(
            drain_env, [msg], seed_state=_seed(skey, 11))
        assert (sent, fail) == (0, 0)
        assert stats["suppressed"] == 1
        assert len(remaining) == 1

    def test_p2_redelivered_after_61_min(self, drain_env):
        # P2 窗口钉死 60: 61min 后放行 (防 P2 窗口被改成无限大)
        msg = dict(self.MSG, id="p2-2", priority="P2")
        skey = _compose_skey(drain_env.mod, msg)
        sent, _, stats, _ = _run_drain(
            drain_env, [msg], seed_state=_seed(skey, 61))
        assert sent == 1 and stats["suppressed"] == 0

    def test_p1_layering_25_suppressed_31_delivered(self, drain_env):
        # P1 取半程 30min: 25min 抑制 / 31min 放行, 两侧边界都钉
        msg = dict(self.MSG, id="p1-1", priority="P1")
        skey = _compose_skey(drain_env.mod, msg)
        sent_in, _, stats_in, _ = _run_drain(
            drain_env, [msg], seed_state=_seed(skey, 25))
        assert sent_in == 0 and stats_in["suppressed"] == 1
        sent_out, _, stats_out, _ = _run_drain(
            drain_env, [msg], seed_state=_seed(skey, 31))
        assert sent_out == 1 and stats_out["suppressed"] == 0

    def test_emoji_prefixed_p0_gets_10min_window_end_to_end(self, drain_env):
        # 历史坑端到端: emoji 前缀的 P0 消息, 11min 后必须重发。若优先级提取或
        # 分层对 emoji 消息退化 (P0 被当 P2), 11min < 60min → 被压 → 红。
        msg = {"id": "gitsync-emoji", "priority": "P0",
               "content": "🔴 [P0] gitsync_check 代码同步环断裂"}
        skey = _compose_skey(drain_env.mod, msg)
        assert "#plain|" in skey  # 键后半段确实走 plain 分支 (文本解析退化已发生)
        sent, fail, stats, _ = _run_drain(
            drain_env, [msg], seed_state=_seed(skey, 11))
        assert (sent, fail) == (1, 0), stats
        assert stats["suppressed"] == 0

    def test_cross_priority_no_mutual_suppression(self, drain_env):
        # 跨级不互抑 (集成级): P0 先投递写 P0#key=T; 11min 后同文本 P2 到来,
        # P2 有自己的键 (无状态) → 必须放行。若 skey 的 prio 前缀被删, 共享键
        # 11min < 60min → P2 被 P0 的抑制状态挡住 → 红。
        p0 = {"id": "a", "priority": "P0", "content": self.TEXT}
        sent0, _, _, _ = _run_drain(drain_env, [p0])
        assert sent0 == 1  # 首投, 状态写 P0#key=now
        skey0 = _compose_skey(drain_env.mod, p0)
        state = json.loads(drain_env.sup.read_text(encoding="utf-8"))
        assert skey0 in state
        # 把 P0 的投递时间改到 11min 前, 模拟「11 分钟后同文本 P2 到达」
        state[skey0] = datetime.now().timestamp() - 11 * 60
        p2 = dict(p0, id="b", priority="P2")
        sent2, _, stats2, _ = _run_drain(drain_env, [p2], seed_state=state)
        assert sent2 == 1 and stats2["suppressed"] == 0

    def test_first_delivery_never_suppressed(self, drain_env):
        # 无任何抑制状态时首投必须放行 (防状态表预填/默认值挡首投)
        sent, fail, stats, _ = _run_drain(drain_env, [self.MSG])
        assert (sent, fail) == (1, 0)
        assert stats["suppressed"] == 0


# ---------------------------------------------------------------- 组5: 边界/异常
class TestSuppressStateEdgeCases:
    """状态文件损坏/形态错误时的 fail-open 行为 + 空队列边界。"""

    MSG = {"id": "e1", "priority": "P0", "content": "[P0] edge_check 演示"}

    def test_corrupt_state_file_fails_open(self, drain_env):
        # 异常: 状态文件不是合法 JSON → 按空表处理 (loud 打印), 不崩退,
        # 消息正常投递。防「读状态失败=整条队列卡死」。
        drain_env.queue.write_text(
            json.dumps([self.MSG], ensure_ascii=False), encoding="utf-8")
        drain_env.sup.write_text("{this-is-not-json", encoding="utf-8")
        sent, fail, stats = drain_env.mod.drain_queue()
        assert (sent, fail) == (1, 0)
        assert stats["suppressed"] == 0

    def test_state_not_dict_fails_open(self, drain_env):
        # 异常: 状态文件是 list 而非 dict → 按空表处理
        drain_env.queue.write_text(
            json.dumps([self.MSG], ensure_ascii=False), encoding="utf-8")
        drain_env.sup.write_text('["not", "a", "dict"]', encoding="utf-8")
        sent, fail, stats = drain_env.mod.drain_queue()
        assert (sent, fail) == (1, 0)

    def test_empty_queue_noop(self, drain_env):
        # 边界: 空队列 → 零投递零抑制, 不崩
        drain_env.queue.write_text("[]", encoding="utf-8")
        assert drain_env.mod.drain_queue() == (0, 0, _ZERO_STATS)

    def test_missing_queue_file_noop(self, drain_env):
        # 边界: 队列文件不存在 → 零投递零抑制, 不崩 (生产首日/被清空的场景)
        if drain_env.queue.exists():
            drain_env.queue.unlink()
        assert drain_env.mod.drain_queue() == (0, 0, _ZERO_STATS)

    def test_unrenderable_entry_dead_lettered_not_suppressed(self, drain_env):
        # 异常: 无法渲染的条目 (无 content/msg/title/body) → 死信移出,
        # 不计投递不计抑制; 同时验证死信写到注入的 tmp 路径 (不碰生产)。
        bad = {"id": "bad-1", "priority": "P0"}
        good = dict(self.MSG, id="good-1")
        sent, fail, stats, remaining = _run_drain(drain_env, [bad, good])
        assert sent == 1
        assert stats["unrenderable"] == 1
        assert drain_env.dead.exists()
        lines = [json.loads(x) for x in
                 drain_env.dead.read_text(encoding="utf-8").splitlines() if x.strip()]
        assert lines and lines[-1]["reason"] == "unrenderable"
        assert [m["id"] for m in remaining] == []


# ---------------------------------------------------------------- P2#5(a): bad-1 生产隔离防线
class TestBad1ProductionIsolation:
    """P2#5(a) @opencode 隔离复查机器防线 (10/25 总管裁定件, 与 @laoliu (b)(c) 同批消费):

    bad-1 unrenderable 死信 fixture 只写 drain_env 注入的 tmp 路径
    (monkeypatched QUEUE_FILE/DEAD_LETTER), 绝不触碰生产
    data/message_queue.json 与 data/drain_dead_letter.jsonl。

    背景 (10/21~10/24 假 P0 刷屏根因, 见 @laowu P2#5 数据面体检): 该隔离一旦失效
    (drain_env 的 monkeypatch 被删/被回滚覆盖), bad-1 会落进生产队列 → 每 drain 轮被
    unrenderable 死信 + 元告警继承 P0 标签 → 刷屏。本组钉死「隔离在位」:
    跑 bad-1 drain 前后, 生产队列/死信的 bad-1 计数不变; 且 bad-1 确实落到注入的 tmp 死信。"""

    def _bad1_count(self, path):
        if not path.exists():
            return 0
        try:
            return sum(1 for ln in path.read_text(encoding="utf-8").splitlines()
                       if "bad-1" in ln)
        except Exception:
            return 0

    def test_bad1_drain_leaves_production_untouched(self, drain_env):
        prod_queue = ROOT / "data" / "message_queue.json"
        prod_dead = ROOT / "data" / "drain_dead_letter.jsonl"
        before_q = self._bad1_count(prod_queue)
        before_d = self._bad1_count(prod_dead)

        bad = {"id": "bad-1", "priority": "P0"}
        good = {"id": "good-1", "priority": "P0", "content": "[P0] edge_check 演示"}
        sent, fail, stats, _ = _run_drain(drain_env, [bad, good])

        # bad-1 死信到注入 tmp, good-1 正常投递 (隔离路径工作正常)
        assert sent == 1
        assert stats["unrenderable"] == 1
        assert drain_env.dead.exists()

        # 隔离断言: 生产队列/死信的 bad-1 计数不变 (fixture 未泄漏进生产)
        assert self._bad1_count(prod_queue) == before_q, \
            "bad-1 泄漏进生产队列 data/message_queue.json (drain_env 隔离失效)"
        assert self._bad1_count(prod_dead) == before_d, \
            "bad-1 泄漏进生产死信 data/drain_dead_letter.jsonl (drain_env 隔离失效)"
