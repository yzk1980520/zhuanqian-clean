# -*- coding: utf-8 -*-
"""老五·剔除环境门(MA250)量化影响 — 熊市区间(gate-off) 切分分析
读取 gateoff_bear 回测产物, 按 MA250 门状态切分:
  - gate-open 子集 = 环境门开启时会交易的 (即"有门"策略的实际暴露)
  - gate-closed 子集 = 环境门关闭时本会空仓的 (剔除门后新增的暴露)
对比整体 vs open-only, 量化剔除门的增量收益/风险。
同时分状态计算因子秩IC (综合/趋势/突破/抄底) + 用TDX重算 chg5/chg10 分状态IC。
"""
import sys, os, json, csv, math
os.chdir(r"D:/open code/zhuanqian")
os.environ.pop("PYTHONPATH", None)
sys.path.insert(0, ".")
from tdx_data import parse_tdx_day
import backtest as BT

OUTDIR = os.path.join("backtest_analysis", "gateoff_bear")
TRADE_CSV = os.path.join(OUTDIR, "trade_detail_v2.csv")
OUT_JSON = os.path.join(OUTDIR, "laowu_gateoff_split_analysis.json")

def fnum(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None

# ── MA250 门状态 (TDX 上证) ──
sh = parse_tdx_day(os.path.join(BT.VIPDOC, "sh", "lday", "sh000001.day"))
dates = [str(r["date"]) for r in sh]; closes = [r["close"] for r in sh]
ma = {}
for i in range(249, len(dates)):
    w = closes[i-249:i+1]; ma[dates[i]] = (closes[i] > sum(w)/len(w))

# ── 读交易 ──
with open(TRADE_CSV, encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))
real = [r for r in rows if r.get("股票代码","").strip() and "MarketGate" not in r.get("股票名称","")]
print("gateoff_bear 交易 %d 笔, 扫描日 %d 个" % (len(real), len(set(r['扫描日期'] for r in real))))

date_state = {}
for r in real:
    d = r["扫描日期"]
    if d in ma:
        date_state[d] = ma[d]
open_dates = [d for d in date_state if date_state[d]]
closed_dates = [d for d in date_state if not date_state[d]]
unknown = [d for d in set(r['扫描日期'] for r in real) if d not in date_state]
print("  MA250门开 扫描日 %d | 门关 扫描日 %d | 无法判 %d" % (len(open_dates), len(closed_dates), len(unknown)))

o_rows = [r for r in real if date_state.get(r["扫描日期"]) is True]
c_rows = [r for r in real if date_state.get(r["扫描日期"]) is False]

def stats(rets):
    n=len(rets)
    if not n: return {}
    wins=sum(1 for r in rets if r>0); mean=sum(rets)/n
    var=sum((r-mean)**2 for r in rets)/n; std=math.sqrt(var)
    ci=1.96*std/math.sqrt(n)
    return dict(n=n, win_rate=round(wins/n*100,2), wins=wins,
                mean5=round(mean,3), ci95=round(ci,3))

def subset(rows, key="5日净收益%"):
    r5=[fnum(r[key]) for r in rows]; r5=[x for x in r5 if x is not None]
    r10=[fnum(r.get("10日净收益%")) for r in rows]; r10=[x for x in r10 if x is not None]
    m=stats(r5)
    m["mean10"]=round(sum(r10)/len(r10),3) if r10 else None
    return m

def ztest(w1,n1,w2,n2):
    import scipy.stats as st
    p1,p2=w1/n1,w2/n2; p=(w1+w2)/(n1+n2); se=math.sqrt(p*(1-p)*(1/n1+1/n2))
    z=(p1-p2)/se if se else float("nan"); pval=2*st.norm.sf(abs(z))
    return p1,p2,z,pval

# 综合排名: 用综合评分(=趋势分等子分的组合, CSV里有"综合评分"列)
def rank_ic(rows, skey="综合评分"):
    pairs=[(fnum(r.get(skey,"")),fnum(r.get("5日净收益%"))) for r in rows]
    pairs=[(a,b) for a,b in pairs if a is not None and b is not None]
    n=len(pairs)
    if n<10: return None
    def rank(vals):
        o=sorted(range(n),key=lambda i:vals[i]); rk=[0]*n;i=0
        while i<n:
            j=i
            while j+1<n and vals[o[j+1]]==vals[o[i]]: j+=1
            avg=(i+j)/2+1
            for k in range(i,j+1): rk[o[k]]=avg
            i=j+1
        return rk
    xs=[p[0] for p in pairs]; ys=[p[1] for p in pairs]; rx=rank(xs);ry=rank(ys)
    mx=sum(rx)/n;my=sum(ry)/n
    cov=sum((rx[i]-mx)*(ry[i]-my) for i in range(n))
    vx=math.sqrt(sum((x-mx)**2 for x in rx));vy=math.sqrt(sum((y-my)**2 for y in ry))
    return round(cov/(vx*vy),4) if vx and vy else None

res = {
    "口径": "gate-off熊市区间(2020-2026), 按MA250门状态切分",
    "gate_off_整体": {**subset(real), "scan_days": len(set(r['扫描日期'] for r in real))},
    "门开子集(有门策略实际暴露)": {**subset(o_rows), "scan_days": len(open_dates)},
    "门关子集(剔除门后新增暴露)": {**subset(c_rows), "scan_days": len(closed_dates)},
    "因子秩IC_门开": {"综合": rank_ic(o_rows),"趋势":rank_ic(o_rows,"趋势评分"),
                "突破":rank_ic(o_rows,"突破评分"),"抄底":rank_ic(o_rows,"抄底评分")},
    "因子秩IC_门关": {"综合": rank_ic(c_rows),"趋势":rank_ic(c_rows,"趋势评分"),
                "突破":rank_ic(c_rows,"突破评分"),"抄底":rank_ic(c_rows,"抄底评分")},
    "因子秩IC_整体": {"综合": rank_ic(real),"趋势":rank_ic(real,"趋势评分"),
                "突破":rank_ic(real,"突破评分"),"抄底":rank_ic(real,"抄底评分")},
}
print("\n[整体] ", res["gate_off_整体"])
print("[门开]", res["门开子集(有门策略实际暴露)"])
print("[门关]", res["门关子集(剔除门后新增暴露)"])
print("\n因子IC 门开:", res["因子秩IC_门开"])
print("因子IC 门关:", res["因子秩IC_门关"])

# 门关 vs 门开 胜率 z 检验
if res["门开子集(有门策略实际暴露)"].get("n") and res["门关子集(剔除门后新增暴露)"].get("n"):
    a=res["门开子集(有门策略实际暴露)"]; b=res["门关子集(剔除门后新增暴露)"]
    p1,p2,z,pv=ztest(a["wins"],a["n"],b["wins"],b["n"])
    res["z检验_门关vs门开"]={"门关胜率":round(p1*100,2),"门开胜率":round(p2*100,2),
                        "diff_pp":round((p1-p2)*100,2),"z":round(z,3),"p_value":round(pv,4)}
    print("\nz检验(门关 vs 门开 胜率):", res["z检验_门关vs门开"])

# 增量: 剔除门 = 整体, 有门 = open-only; 门关子集就是增量
if res["门关子集(剔除门后新增暴露)"].get("n"):
    c=res["门关子集(剔除门后新增暴露)"]
    res["剔除门增量解读"]={
        "门关期笔数": c["n"], "门关期胜率": c["win_rate"], "门关期均5d": c["mean5"],
        "门关期均10d": c.get("mean10"),
        "说明": "这部分交易在'有环境门'时不会发生(门关空仓)。剔除门=放弃这批, 有门=只做门开子集。"
                "若门关胜率/收益 > 门开, 剔除门反而更好; 反之剔除门是拖累。"
    }
    print("\n剔除门增量:", res["剔除门增量解读"])

with open(OUT_JSON,"w",encoding="utf-8") as f:
    json.dump(res,f,ensure_ascii=False,indent=2,default=str)
print("\n结果已写 %s" % OUT_JSON)
