/* agent-verdict.js — file:// 双击打开时的数据注入格式（与 agent-verdict.json 内容一致）
   老五评审脚本写盘时保持 window.AGENT_VERDICT = {...} 结构即可，字段契约见 JSON 版 _contract 说明 */
window.AGENT_VERDICT = {
  "version": "1.0",
  "generated_at": "2026-09-26T05:30:00+08:00",
  "run_id": "20260926-0530",
  "pipeline": { "nodes": 8, "parallel": 4, "dur": 22.2, "tokens": 6200, "quality": 88, "retries": 1 },
  "review": {
    "agent": "laowu-review",
    "round": 2,
    "score": 79,
    "threshold": 85,
    "pass": true,
    "failures": [
      { "span": "L7 真突破检测", "artifact": "breakout_filter", "node": "l57",
        "issue": "threshold_too_loose",
        "evidence": "回测窗口 34 只触发真突破，仅 12 只 5 日内站稳（站稳率 35%，门槛 60%）" },
      { "span": "序列风控", "artifact": "sequence_risk", "node": "l57",
        "issue": "cooldown_not_full",
        "evidence": "连续亏损后冷却期 3 日未满即放行 2 笔强信号，违反 sequence_risk 规则" }
    ],
    "patches": [
      { "target": "L7 真突破检测", "param": "breakout_threshold", "from": "8%", "to": "6%" },
      { "target": "序列风控", "param": "cooldown_days", "from": "3", "to": "1" }
    ],
    "round2": { "score": 88, "note": "参数补丁生效：真突破 21 只触发 16 只站稳（76% ≥ 60%）；冷却期修正后无违规放行。第 2 轮评分 88 ≥ 85，审批通过。" }
  },
  "manifest": [
    { "node": "l57", "chapters": [
      { "ch": "L5b 动量评分", "deps": [{"id":"L1评分","t":"b"},{"id":"技术指标","t":"p"}], "ok": true },
      { "ch": "L7 真突破检测", "deps": [{"id":"L1评分","t":"b"},{"id":"breakout_filter","t":"p"}], "ok": false, "tag": "阈值过松" },
      { "ch": "L7 形态过滤", "deps": [{"id":"pattern_filter","t":"p"}], "ok": true },
      { "ch": "序列风控", "deps": [{"id":"L1评分","t":"b"},{"id":"sequence_risk","t":"p"}], "ok": false, "tag": "冷却期未满" }
    ]}
  ]
};
