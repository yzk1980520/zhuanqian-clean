#!/usr/bin/env python
# DEPRECATED → use scripts/check_all.py data-quality
# -*- coding: utf-8 -*-
"""
退市股覆盖审计 —— 把"回测到底有没有考虑退市股"从一个断言变成一个可查的数字。

═══ 为什么需要 ═══
2026-10-17 诊断：`backtest_rotation.py` grep "退市|delist" = 0 处，
看起来完全没覆盖退市股，违反 AGENTS.md:97 铁律。
但深挖发现：`collect_all_stocks()`（`backtest.py:198-231`）已经把
`data/history_daily/`（9442 个文件）并入候选池，其中 157 只是 TDX 已删的退市股。

也就是说：**退市股在池子里，但没人能证明**。全项目 grep 不到"退市"二字，
`rotation_backtest_result.json` 里也没有任何覆盖痕迹 —— 这与"真的没覆盖"
在后果上是一样的：**无法自证，就无法信任**。

本脚本零风险（只读，不改任何生产逻辑），只做三件事：
  1. 算出"扩展库独家代码"集合（= TDX 里没有的那些，含退市股）
  2. 逐只统计记录数与最后交易日，分出「有数据」/「空壳」
  3. 产出 data/delisted_audit.json，供门禁断言与后续决策使用

═══ 语义归属（2026-10-17 老大裁定，写死在此防止后人再混）═══
  · data/delisted_audit.json        = **静态快照**，只用于门禁降级读取
  · 回测结果里的 delisted_coverage  = **该次运行的实算值，是最终权威**
  · 两者不一致时以回测结果为准，且差异必须可解释

═══ 为什么 with_data_count 从 25 改成了 15 ═══
初版只数"文件里有 >=30 根"的票，报 25。但回测器实算只有 15 只真正进入候选池 ——
裂口来自回测器的 ST 过滤：backtest.py:42-47 把 `is_st_stock` 别名到 `is_st_only`，
加载循环里 `if BT.is_st_stock(name): continue` 会把 ST/*ST 前缀的票剔除（本库 66 只）。
本脚本现在**与回测器同一口径**，因此：157 = 15 参与 + 66 ST剔除 + 76 空壳 + 0 稀薄。

⚠️ 极易踩的坑（初版差点搞反）：
  回测器用的是 `is_st_only`，**只排 ST/*ST 前缀，不排含"退"字的票**。
  这是 R9(2026-08-15) 的刻意设计 —— 退市股必须留在池子里，否则幸存者偏差修复就废了。
  `tdx_data.is_st_stock`（含 "退" 判据）是**实盘选股**口径，回测**不沿用**。
  若误用后者，会得到 st_skipped=143 / with_data=4，与回测器差 77 只，且方向是错的。

用法：
    python scripts/audit_delisted_coverage.py
    python scripts/audit_delisted_coverage.py --min-bars 30
"""
import argparse
import datetime
import json
import os
import re
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)
HISTORY_DIR = os.path.join(PROJECT, "data", "history_daily")
OUT_PATH = os.path.join(PROJECT, "data", "delisted_audit.json")

# ── ST 过滤：必须与回测器同一真源，不允许在本脚本里重造判据 ──
# 回测器调的是 BT.is_st_stock，而 backtest.py:47 把它别名到 is_st_only
# （只排 ST/*ST 前缀，不排含"退"的票 —— R9 幸存者偏差修复的刻意设计）。
try:
    import backtest as _BT
    _is_st = _BT.is_st_stock          # ← 权威单一真源
    ST_FILTER_SOURCE = "backtest.is_st_stock (= is_st_only, backtest.py:42-47)"
    NAME_SOURCE = "backtest.load_name_cache() -> stock_names.json"
except Exception as _e:               # 拿不到真源就降级，但必须如实标注，绝不静默
    def _is_st(name):
        return bool(name and (name.startswith("ST") or name.startswith("*ST")))
    ST_FILTER_SOURCE = "inline_fallback (backtest 导入失败: %s)" % _e
    NAME_SOURCE = "stock_names.json (直接读取)"

ST_FILTER_RULE = ('name.startswith("ST") or name.startswith("*ST") —— '
                  '与 backtest.is_st_only 同口径；**不**排除含"退"字的票'
                  '（R9: 退市股必须留在回测池里）')


def _load_names():
    """名称表：优先用与回测器同一个函数，保证口径零漂移。"""
    try:
        return _BT.load_name_cache()
    except Exception as e:
        print(f"🔴 [audit_delisted_coverage.py:79] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
        pass
    p = os.path.join(PROJECT, "stock_names.json")
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (ValueError, OSError) as e:
        print(f"🔴 [audit_delisted_coverage.py:85] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 (ValueError, OSError) → 兜底, 异常={e}", file=sys.stderr)
        return {}

# TDX 本地日线目录（当前仍上市的票）
TDX_LDAY = {
    "sh": r"D:\TDX\vipdoc\sh\lday",
    "sz": r"D:\TDX\vipdoc\sz\lday",
}
# 与 tdx_data.py:27-29 一致的白名单
ALLOWED_PREFIX = {"sh": ("600", "601", "603", "605"), "sz": ("000", "001", "002", "003")}

CODE_RE = re.compile(r"^(sh|sz)(\d{6})\.(?:day|json)$", re.I)


def _scan_tdx():
    """返回 TDX lday 里存在的股票代码集合（即"当前仍上市"的近似）。"""
    found = set()
    missing_dirs = []
    for mkt, d in TDX_LDAY.items():
        if not os.path.isdir(d):
            missing_dirs.append(d)
            continue
        for name in os.listdir(d):
            m = CODE_RE.match(name)
            if not m:
                continue
            mk, num = m.group(1).lower(), m.group(2)
            if not num.startswith(ALLOWED_PREFIX.get(mk, ())):
                continue
            found.add(mk + num)
    return found, missing_dirs


def _scan_history():
    """返回 {code: (记录数, 最后日期str)}；扩展历史库。"""
    info = {}
    if not os.path.isdir(HISTORY_DIR):
        return info, "%s 不存在" % HISTORY_DIR
    for name in os.listdir(HISTORY_DIR):
        if not name.endswith(".json"):
            continue
        code = name[:-5]
        full = os.path.join(HISTORY_DIR, name)
        try:
            with open(full, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (ValueError, OSError):
            info[code] = (0, None)
            continue
        # 兼容三种形态: [] / {"data":[...]} / {"records":[...]}
        if isinstance(raw, list):
            rows = raw
        elif isinstance(raw, dict):
            rows = raw.get("data") or raw.get("records") or raw.get("bars") or []
        else:
            rows = []
        if not rows:
            info[code] = (0, None)
            continue
        last = None
        try:
            last = str(rows[-1].get("date", ""))[:10] or None
        except (AttributeError, IndexError, TypeError) as e:
            print(f"🔴 [audit_delisted_coverage.py:147] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 (AttributeError, IndexError, TypeError) → 兜底, 异常={e}", file=sys.stderr)
            pass
        info[code] = (len(rows), last)
    return info, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-bars", type=int, default=30,
                    help='判定"有可用数据"的最少K线数（对齐 backtest_rotation.py:1092）')
    # W2(2026-10-17) 新增：empty_sample 在 JSON 里被截断到 50 条，补数据需要全量清单。
    # 复用本脚本同一套分类逻辑（含 ALLOWED_PREFIX 主板白名单 + 回测同口径 ST 过滤），
    # 绝不另起炉灶重造判据 —— 否则 157 会膨胀到 6232。
    ap.add_argument("--dump-empty", metavar="PATH", default=None,
                    help="把**全量**空壳代码(0根K线)写入指定路径（纯文本，一行一个 code）")
    ap.add_argument("--dump-json", metavar="PATH", default=None,
                    help="把全量分类明细写为 JSON（empty/with_data/st_skipped/thin 全量，不截断）")
    a = ap.parse_args()

    print("=" * 62)
    print("退市股覆盖审计  %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    print("=" * 62)

    tdx_codes, missing = _scan_tdx()
    if missing:
        print("⚠️ TDX 目录不可达: %s（'当前上市'集合会不完整，结论偏保守）" % missing)
    print("TDX lday 当前上市代码: %d 只" % len(tdx_codes))

    hist, err = _scan_history()
    if err:
        print("❌ %s" % err)
        return 2
    print("扩展历史库文件: %d 只" % len(hist))

    # 扩展库必须先按同一套白名单过滤 —— 否则会把指数(sh000001 上证指数等)、
    # 科创板/创业板等非主板票算进来, 把"退市股"数字放大几十倍。
    def _in_universe(code):
        if len(code) != 8:
            return False
        mk, num = code[:2].lower(), code[2:]
        if not re.fullmatch(r"\d{6}", num):
            return False
        return num.startswith(ALLOWED_PREFIX.get(mk, ()))

    hist_main = {c: v for c, v in hist.items() if _in_universe(c)}
    print("扩展库主板票（已过滤指数/科创/创业）: %d 只" % len(hist_main))

    # 扩展库独家 = 不在 TDX 里 → 含退市股（也可能含长期停牌/数据源独家）
    exclusive = sorted(set(hist_main) - tdx_codes)
    print("扩展库独家（TDX 已无，含退市）: %d 只" % len(exclusive))

    # ── 分类必须与回测器加载段同构：先过 ST 过滤，再按记录数分档 ──
    # 顺序不能反：回测器是 ST 先 continue，ST 票即使有数据也不进池。
    name_cache = _load_names()
    print("名称表: %d 只 | 过滤口径: %s" % (len(name_cache), ST_FILTER_SOURCE))
    if not name_cache:
        print("⚠️ 名称表为空 —— 无法做 ST 过滤, with_data_count 会偏高(等同未过滤), 以回测器实算为准")

    with_data, empty, thin, st_skipped = [], [], [], []
    raw_with_data = 0   # 未过 ST 过滤的原始值，保留以便溯源(初版报的 25 就是这个数)
    for code in exclusive:
        n, last = hist.get(code, (0, None))
        if n >= a.min_bars:
            raw_with_data += 1
        if _is_st(name_cache.get(code, "")):
            st_skipped.append({"code": code, "bars": n, "name": name_cache.get(code, "")})
            continue
        if n >= a.min_bars:
            with_data.append({"code": code, "bars": n, "last_date": last})
        elif n > 0:
            thin.append({"code": code, "bars": n, "last_date": last})
        else:
            empty.append(code)

    print("-" * 62)
    print("  参与回测 (>=%d 根且非ST): %d 只  ← 真正进入候选池的部分" % (a.min_bars, len(with_data)))
    print("  ST/*ST 剔除          : %d 只  ← 回测器 is_st_only 过滤" % len(st_skipped))
    print("  数据稀薄 (1~%d 根)    : %d 只  ← 会被 len>=%d 过滤掉" % (a.min_bars - 1, len(thin), a.min_bars))
    print("  空壳文件 (0 根)       : %d 只  ← 拿不到数据，真正的幸存者偏差缺口" % len(empty))
    print("  （未过ST过滤的原始值  : %d 只  ← 仅供溯源，勿对外引用）" % raw_with_data)
    print("-" * 62)
    _parts = len(with_data) + len(st_skipped) + len(thin) + len(empty)
    print("  恒等式校验: %d + %d + %d + %d = %d (exclusive %d) %s"
          % (len(with_data), len(st_skipped), len(thin), len(empty), _parts, len(exclusive),
             "✅" if _parts == len(exclusive) else "❌ 对不上，分类逻辑有漏"))

    # ── W2(2026-10-17) 全量导出：仅供补数据使用，不影响门禁语义 ──
    if a.dump_empty:
        with open(a.dump_empty, "w", encoding="utf-8") as fh:
            fh.write("\n".join(empty))
            if empty:
                fh.write("\n")
        print("📝 全量空壳清单已写入 %s (%d 只)" % (a.dump_empty, len(empty)))
    if a.dump_json:
        with open(a.dump_json, "w", encoding="utf-8") as fh:
            json.dump({
                "generated": datetime.datetime.now().isoformat(timespec="seconds"),
                "min_bars": a.min_bars,
                "exclusive_count": len(exclusive),
                "empty": empty,
                "with_data": with_data,
                "st_skipped": st_skipped,
                "thin": thin,
            }, fh, ensure_ascii=False, indent=2)
        print("📝 全量分类明细已写入 %s" % a.dump_json)

    if with_data:
        dates = sorted(x["last_date"] for x in with_data if x["last_date"])
        print("有数据者最后交易日区间: %s ~ %s" % (dates[0], dates[-1]) if dates else "")
        print("样例(前5): " + ", ".join(
            "%s(%d根,%s)" % (x["code"], x["bars"], x["last_date"]) for x in with_data[:5]))

    result = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "min_bars": a.min_bars,
        "tdx_current_count": len(tdx_codes),
        "history_file_count": len(hist),
        # ── 以下 5 个计数满足恒等式 ──
        #   exclusive_count = with_data_count + st_skipped + empty_count + thin_count
        # 语义与回测器 backtest_rotation.py 加载段完全一致（同一 ST 口径）。
        # ⚠️ 但本文件只是**静态快照**；与回测结果的 delisted_coverage 冲突时以回测结果为准。
        "exclusive_count": len(exclusive),
        "with_data_count": len(with_data),      # 过 ST 过滤后仍有 >=min_bars 根 = 真正参与回测
        "st_skipped": len(st_skipped),          # 被 is_st_only(ST/*ST 前缀) 剔除
        "thin_count": len(thin),
        "empty_count": len(empty),              # 空壳，真实幸存者偏差缺口
        # ── 溯源与口径声明 ──
        "with_data_before_st_filter": raw_with_data,  # 未过 ST 过滤的原始值(初版误报的 25)，仅供溯源
        "st_filter_applied": bool(name_cache),
        "st_filter_source": ST_FILTER_SOURCE,
        "st_filter_rule": ST_FILTER_RULE,
        "name_source": NAME_SOURCE,
        "identity_ok": _parts == len(exclusive),
        "verdict": {
            "delisted_in_pool": len(exclusive) > 0,
            "effectively_covered": len(with_data),
            "survivorship_gap": len(empty),
            "note": ("退市股已并入候选池，但只有部分有可用数据；"
                     "空壳部分为真实幸存者偏差缺口，需单独补数据（P1）。"
                     "数字口径已与回测器对齐(同一 ST 过滤)；本文件为静态快照，"
                     "与回测结果 delisted_coverage 冲突时以后者为准。"),
        },
        "with_data_sample": with_data[:50],
        "st_skipped_sample": st_skipped[:50],
        "empty_sample": empty[:50],
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print("✅ 已产出 %s" % os.path.relpath(OUT_PATH, PROJECT))

    # 门禁语义：至少要有退市股在池子里，否则证明不了
    if len(exclusive) == 0:
        print("❌ 候选池中没有任何 TDX 已删代码 —— 退市覆盖不成立")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
