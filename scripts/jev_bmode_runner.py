#!/usr/bin/env python3
"""Jev B-mode advisory runner for 御龙决.
零成本模拟, 非校准概率. 输出 mode=model_simulation, jev_called=false.
不写 live 旗标, 仅写 advisory result to data/jev_*.json.
场景: 1.P4三闸判定 2.F2复置评估 3.S3-10因子合并分类
"""
import json, os, sys, urllib.request, urllib.error, re
from datetime import datetime

PROFILE_ENV = r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home\profiles\zongguan\.env"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# 多模型 fallback 链：不同 provider，一个 429 自动切下一个（OpenRouter 官方推荐做法）
FALLBACK_MODELS = [
    "poolside/laguna-xs-2.1:free",          # provider: poolside
    "nvidia/nemotron-3.5-lightning:free",   # provider: nvidia（慢但稳）
    "google/gemma-4-31b-it:free",           # provider: google（偶发 429）
]
DEFAULT_MODEL = FALLBACK_MODELS[0]

JEV_SYSTEM_PROMPT = (
    "You simulate TypeSafe Jev. Output ONLY one JSON object, no prose:\n"
    '{"results":{"<qid>":{"value":<criteria key|bool>,...},"reason":"<=10 words"}}.'
)


def load_key():
    if not os.path.exists(PROFILE_ENV):
        return None
    for line in open(PROFILE_ENV, encoding="utf-8"):
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip()
    return None


def call_b_mode(state, questions, model=None, max_retries=2):
    """带多模型 fallback 链的 B-mode 调用。
    当一个 provider 返回 429 时自动尝试下一个模型（不同 provider）。
    """
    if model is None:
        model = DEFAULT_MODEL
    # 构建完整的 fallback 链：从指定模型开始，追加其后的所有模型
    try:
        model_idx = FALLBACK_MODELS.index(model)
    except ValueError:
        model_idx = 0
    model_chain = FALLBACK_MODELS[model_idx:]
    key = load_key()
    if not key:
        return {"error": "OPENROUTER_API_KEY not found in .env",
                "mode": "model_simulation", "jev_called": False}
    for attempt_model in model_chain:
        for attempt in range(max_retries + 1):
            payload = json.dumps({
                "model": attempt_model,
                "messages": [
                    {"role": "system", "content": JEV_SYSTEM_PROMPT},
                    {"role": "user", "content": "JSON only.\n" + json.dumps(
                        {"state": state, "questions": questions}, ensure_ascii=False
                    )},
                ],
                "temperature": 0,
                "max_tokens": 800,
            })
            req = urllib.request.Request(
                OPENROUTER_URL,
                data=payload.encode(),
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    resp = json.loads(r.read())
                content = resp["choices"][0]["message"]["content"]
                # 取第一个完整 {...} 块（模型可能追加解释文本）
                depth = 0
                for i, ch in enumerate(content):
                    if ch == '{':
                        if depth == 0: start = i
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            try:
                                result = json.loads(content[start:i+1])
                                result["_model_used"] = attempt_model
                                return result
                            except json.JSONDecodeError:
                                print(f"🔴 [scripts\jev_bmode_runner.py] CR-01: except json.JSONDecodeError:", file=sys.stderr)
                result = {"raw": content, "_model_used": attempt_model}
                return result
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < max_retries:
                    import time
                    wait = 2 ** attempt  # 1s, 2s
                    time.sleep(wait)
                    continue
                # 非 429 错误或重试耗尽：记录并尝试下一个模型
                if attempt >= max_retries or e.code != 429:
                    last_error = f"HTTP {e.code} ({attempt_model})"
                    if attempt_model != model_chain[-1]:
                        continue  # 尝试下一个模型
                    return {"error": last_error,
                            "mode": "model_simulation", "jev_called": False,
                            "_model_used": attempt_model}
            except Exception as e:
                if attempt >= max_retries or "429" not in str(e):
                    last_error = str(e)
                    if attempt_model != model_chain[-1]:
                        continue  # 尝试下一个模型
                    return {"error": last_error,
                            "mode": "model_simulation", "jev_called": False,
                            "_model_used": attempt_model}
    return {"error": "all models exhausted", "mode": "model_simulation",
            "jev_called": False}


def run_p4_gate(state_path="data/market_adaptation_decision.json"):
    try:
        d = json.load(open(state_path, encoding="utf-8"))
    except Exception as e:
        return {"error": f"read decision.json: {e}"}
    g = d.get("gate", {})
    state = {
        "task": "P4三闸自动判定",
        "gate_a": {
            "open": g.get("open", False),
            "sh_close": g.get("sh_close"),
            "ma250": g.get("ma250"),
            "gap_pct": round(
                ((g.get("sh_close") or 0) - (g.get("ma250") or 1)) / max(g.get("ma250") or 1, 1) * 100, 2
            ),
        },
        "s3_08": {"laowu_approved": False, "verdict": "NO_RELEASE"},
        "review_status": {"laowu_approved": False, "frozen_until": "2026-12-27"},
    }
    questions = {
        "p4_action": {
            "type": "choice",
            "instructions": "从证据判断P4状态",
            "criteria": {
                "unlock": "三闸全绿可建仓",
                "monitor": "阈值模糊需观察",
                "hold": "任一闸红不建仓",
            },
        },
        "confidence": {
            "type": "score",
            "min": 1,
            "max": 10,
            "instructions": "信心程度",
            "criteria": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        },
        "needs_human_review": {
            "type": "noul",
            "instructions": "是否需老大拍板",
            "criteria": {"true": "闸门模糊需拍板", "false": "闸门明确红无需拍板"},
        },
    }
    result = call_b_mode(state, questions)
    out = {
        "mode": "model_simulation",
        "jev_called": False,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "state_path": state_path,
        "result": result,
    }
    out_path = "data/jev_p4_ruling.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return out


def run_f2_eval(backtest_path="data/rotation_backtest_result.v2on_r1.json"):
    try:
        d = json.load(open(backtest_path, encoding="utf-8"))
        results = d.get("results", [])
        configs = []
        for r in results:
            configs.append({
                "name": r.get("config", "unknown"),
                "trades": r.get("trades"),
                "win_rate": r.get("win_rate"),
                "pf": r.get("profit_factor"),
                "total_return": r.get("total_return_pct"),
                "max_dd": r.get("max_drawdown_pct"),
            })
    except Exception as e:
        return {"error": f"read backtest: {e}"}

    state = {
        "task": "F2复置条件评估",
        "configs": configs,
        "thresholds": {"win_rate": 40, "unique": 50, "pf": 1.5, "return": 0},
    }
    questions = {
        "any_full_green": {
            "type": "noul",
            "instructions": "是否有≥1配置全绿？",
            "criteria": {"true": "存在配置满足全部门禁", "false": "所有配置均未全绿"},
        },
        "best_config": {
            "type": "choice",
            "instructions": "最接近全绿的配置",
            "criteria": {k: v["name"] for k, v in enumerate(configs)},
        },
        "recommendation": {
            "type": "choice",
            "instructions": "对flag的建议",
            "criteria": {
                "keep_false": "维持false冻结至12-27",
                "request_revote": "要求老五重出全量终审",
                "hold_pending": "等待新配置出现",
            },
        },
    }
    result = call_b_mode(state, questions)
    out = {
        "mode": "model_simulation",
        "jev_called": False,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "result": result,
    }
    out_path = "data/jev_f2_ruling.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return out


def run_s310_merge(backtest_path="data/s3-10-p2-backtest-result.json"):
    """场景3: S3-10因子合并分类. 读 results 列表, 按 variant_id 拆分 baseline/V2/V3/V4.
    转正标准 (P3老五裁决): ①超baseline(胜率+收益) ②去肥尾正(win132 total_pnl>0) ③≥10笔近窗样本.
    """
    try:
        d = json.load(open(backtest_path, encoding="utf-8"))
        results = d.get("results", [])
        # 按 variant_id 分组
        by_variant = {}
        for r in results:
            vid = r.get("variant_id", r.get("config", "unknown"))
            by_variant[vid] = {
                "trades": r.get("trades"),
                "win_rate": r.get("win_rate"),
                "total_return_pct": r.get("total_return_pct"),
                "pf": r.get("profit_factor"),
                "max_dd": r.get("max_drawdown_pct"),
                "win132": r.get("win132", {}),
            }
        baseline = by_variant.get("baseline", {})
    except Exception as e:
        return {"error": f"read s3-10 result: {e}"}

    state = {
        "task": "S3-10因子合并分类",
        "baseline": baseline,
        "variants": {k: v for k, v in by_variant.items() if k != "baseline"},
        "merge_criteria": {
            "merge": "超baseline(胜率+收益)且win132 total_pnl>0且≥10笔近窗样本",
            "observe": "未达转正但方向正确(胜率接近或收益正)",
            "reject": "负收益或回撤超标或胜率明显低于baseline",
        },
    }
    questions = {
        "V3_action": {
            "type": "choice",
            "instructions": "评估V3因子是否应合并到S3主候选",
            "criteria": {"merge": "超baseline且win132正且≥10笔", "observe": "未达标但观察", "reject": "负收益或回撤超标"},
        },
        "V3_validity": {
            "type": "noul",
            "instructions": "V3是否仍有价值待验证?",
            "criteria": {"true": "win132 trades≥10笔有统计力", "false": "win132 trades<10笔无统计力"},
        },
        "V2_action": {
            "type": "choice",
            "instructions": "评估V2(低波反转)是否应合并",
            "criteria": {"merge": "超baseline", "observe": "方向可观察", "reject": "负收益"},
        },
        "V4_action": {
            "type": "choice",
            "instructions": "评估V4(交互项)是否应合并",
            "criteria": {"merge": "超baseline", "observe": "方向可观察", "reject": "负收益或回撤超标"},
        },
    }
    result = call_b_mode(state, questions)
    out = {
        "mode": "model_simulation",
        "jev_called": False,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "result": result,
    }
    out_path = "data/jev_s310_ruling.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", choices=["p4_gate", "f2_eval", "s310_merge"], default="p4_gate")
    args = ap.parse_args()

    if args.task == "p4_gate":
        r = run_p4_gate()
    elif args.task == "f2_eval":
        r = run_f2_eval()
    elif args.task == "s310_merge":
        r = run_s310_merge()
    else:
        r = {"error": f"unknown task: {args.task}"}

    sys.exit(0 if "error" not in r else 1)
