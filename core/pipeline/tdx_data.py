"""TDX 数据解析模块 — Phase C-1 拆分自 tdx_core.py (2026-08-31)

职责:
- TDX 日线二进制文件读取 (parse_tdx_day / get_tdx_data)
- 股票池过滤 (should_include / is_st_stock)
- 行业映射 (BROAD_INDUSTRY / load_industry_map / get_industry)
- 股票名称缓存 (load_name_cache / save_name_cache / batch_fetch_names)
- 实时行情快照 (fetch_realtime_prices)

兼容性: tdx_core.py 仍作为兼容入口 re-export 本模块所有符号。
"""

import os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import struct
import urllib.request
import json
import sys
from datetime import date

import core.pipeline.atomic_json as atomic_json  # R5 (2026-08-31): 统一 atomic_dump 入口
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

VIPDOC = r"D:\TDX\vipdoc"
ALLOWED_PREFIXES_SH = {"600", "601", "603", "605"}
ALLOWED_PREFIXES_SZ = {"000", "001", "002", "003"}
# P1修复(20261023): 基地化S4迁移后 dirname(__file__)=core/pipeline/, 三个数据文件锚点漂移
# (repo根: stock_names.json / industries.json / data/stock_industry_map.json), 改用L14已锚定的PROJECT_ROOT。
NAME_CACHE_FILE = os.path.join(PROJECT_ROOT, "stock_names.json")
INDUSTRY_FILE = os.path.join(PROJECT_ROOT, "industries.json")
SW_INDUSTRY_MAP_FILE = os.path.join(PROJECT_ROOT, "data", "stock_industry_map.json")


def parse_tdx_day(filepath):
    """高性能解析TDX .day文件（P0优化：NumPy向量化）"""
    import struct
    
    with open(filepath, "rb") as f:
        data = f.read()
    
    n_records = len(data) // 32
    if n_records < 20:
        return []
    
    # 批量解析
    from numpy import empty
    dates = empty(n_records, dtype='<I')
    opens = empty(n_records, dtype='<I')
    highs = empty(n_records, dtype='<I')
    lows = empty(n_records, dtype='<I')
    closes = empty(n_records, dtype='<I')
    volumes = empty(n_records, dtype='<I')
    amounts = empty(n_records, dtype='<f8')
    
    for i in range(n_records):
        offset = i * 32
        # P0修复 2026-09-25: 原结构 "<IIIIIIII" 把 TDX 第6字段(float型成交额)按int读出错值,
        # 且 amount 错误赋值为成交量(股数)。TDX日线标准结构: 5×int(日期/开高低收) + 1×float(成交额) + 2×int(成交量/保留)
        vals = struct.unpack("<IIIIIfII", data[offset:offset+32])
        dates[i] = vals[0]
        opens[i] = vals[1]
        highs[i] = vals[2]
        lows[i] = vals[3]
        closes[i] = vals[4]
        amounts[i] = vals[5]
        volumes[i] = vals[6]
    
    # 过滤有效日期
    mask = (dates >= 19900101) & (dates <= 20300000)
    if mask.sum() < 20:
        return []
    
    records = []
    for i in range(n_records):
        if not mask[i]:
            continue
        d = dates[i]
        s = str(d)
        if len(s) != 8:
            continue
        records.append({
            "date": date(int(s[:4]), int(s[4:6]), int(s[6:8])),
            "open": float(opens[i]) / 100.0,
            "high": float(highs[i]) / 100.0,
            "low": float(lows[i]) / 100.0,
            "close": float(closes[i]) / 100.0,
            "amount": int(amounts[i]),   # 成交额(元) — P0修复2026-09-25
            "volume": int(volumes[i]),   # 成交量(股)
        })
    return records


def get_tdx_data(code, days=150):
    # P1-12(2026-08-08): 无前缀代码容错 — TDX指数文件带市场前缀(sh000001.day),
    # 股票文件无前缀(sz/lday/000001.day)。无前缀时尝试 sh/sz 两市场(股票优先)。
    market = code[:2]
    if market not in ("sh", "sz"):
        for m in ("sz", "sh"):  # 股票优先(sz000001平安银行), 指数次之(sh000001上证)
            for fp in (
                os.path.join(VIPDOC, m, "lday", f"{code}.day"),
                os.path.join(VIPDOC, m, f"{code}.day"),
            ):
                if os.path.exists(fp):
                    r = parse_tdx_day(fp)
                    return r[-days:] if len(r) > days else r
        return None
    for fp in (
        os.path.join(VIPDOC, market, "lday", f"{code}.day"),
        os.path.join(VIPDOC, market, f"{code}.day"),
    ):
        if os.path.exists(fp):
            r = parse_tdx_day(fp)
            return r[-days:] if len(r) > days else r
    return None


def get_latest_tdx_date(code):
    """快速获取股票最新交易日（只读最后一条32字节记录）"""
    market = code[:2]
    for fp in (
        os.path.join(VIPDOC, market, "lday", f"{code}.day"),
        os.path.join(VIPDOC, market, f"{code}.day"),
    ):
        if os.path.exists(fp):
            size = os.path.getsize(fp)
            if size < 32:
                return None
            with open(fp, "rb") as f:
                f.seek(-32, 2)
                d = f.read(32)
                if len(d) >= 32:
                    di = struct.unpack("<I", d[:4])[0]
                    s = str(di)
                    if len(s) == 8:
                        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    return None


def should_include(code):
    cn = code[2:] if code[:2].isalpha() else code
    prefix = cn[:3]
    mkt = code[:2] if code[:2].isalpha() else ("sh" if code[0] in "56" else "sz")
    return (mkt == "sh" and prefix in ALLOWED_PREFIXES_SH) or \
           (mkt == "sz" and prefix in ALLOWED_PREFIXES_SZ)


def is_st_stock(name):
    return bool(name and (name.startswith("ST") or name.startswith("*ST") or "退" in name))


def is_tradable_code(code, name=""):
    """主板前缀白名单 ∧ (传了 name 则) 非ST/非退市 —— 实盘选股剔除的原子判定。

    复用 should_include(主板前缀白名单) + is_st_stock, 不重造逻辑。
    生产路径 (auto_live_pipeline / daily_pick) 统一调此函数, 防"各写各的"再漂移。
    不传 name 时仅按板块白名单判定(纯函数, 无外部依赖): 剔创业板/科创/北证/ETF/基金。
    code 形如 sh600519/sz300001/bj430047 或裸码。
    """
    if not should_include(code):
        return False
    if name and is_st_stock(name):
        return False
    return True


def should_exclude_delisted(code, name_cache=None):
    """过滤退市股（在名称缓存中已标注为退市的股票）"""
    if name_cache and code in name_cache:
        name = name_cache[code].get('name', '')
        if '退' in name:
            return True
    return False


BROAD_INDUSTRY = {
    "600000":"金融","600015":"金融","600016":"金融","600030":"金融","601":"金融",
    "600036":"金融","601166":"金融","601318":"金融","601398":"金融","601939":"金融",
    "601288":"金融","601328":"金融","601988":"金融","601601":"金融","601628":"金融",
    "600519":"白酒","600809":"白酒","000858":"白酒","000568":"白酒","002304":"白酒",
    "600887":"食品","600882":"食品","002597":"食品","600600":"食品",
    "600585":"建材","000786":"建材","600801":"建材","000401":"建材",
    "600104":"汽车","000625":"汽车","601238":"汽车","600741":"汽车","002594":"汽车",
    "600031":"机械","000157":"机械","600169":"机械","002353":"机械",
    "600690":"家电","000651":"家电","002032":"家电","000333":"家电",
    "600276":"医药","000538":"医药","600196":"医药","002007":"医药",
    "600588":"软件","000977":"软件","002230":"软件","002415":"科技",
    "600570":"软件","600845":"软件","002881":"科技",
    "600050":"通信","000063":"通信","600941":"通信",
    "600900":"电力","600011":"电力","600023":"电力","600025":"电力",
    "600028":"石化","600019":"钢铁","600010":"钢铁","600022":"钢铁",
    "600048":"地产","000002":"地产","001979":"地产",
    "601111":"航空","600029":"航空","600115":"航空",
    "601800":"基建","601390":"基建","601668":"基建","600068":"基建",
}


def load_industry_map():
    if os.path.exists(INDUSTRY_FILE):
        try:
            with open(INDUSTRY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def get_industry(code, name="", cache=None):
    """获取股票行业，优先使用申万行业映射"""
    # 优先使用申万行业映射（覆盖旧缓存）
    try:
        if os.path.exists(SW_INDUSTRY_MAP_FILE):
            with open(SW_INDUSTRY_MAP_FILE, "r", encoding="utf-8") as f:
                sw_map = json.load(f)
            industry = sw_map.get("map", {}).get(code)
            if industry:
                return industry
    except Exception:
        pass
    # 兜底：旧缓存/关键词匹配/硬编码
    if cache and code in cache:
        return cache[code]
    if name:
        for kw, ind in {"银行":"金融","证券":"金融","保险":"金融","科技":"科技",
                         "海康":"科技","医药":"医药","地产":"地产","钢铁":"钢铁",
                         "电力":"电力","汽车":"汽车","通信":"通信","软件":"软件",
                         "机械":"机械","食品":"食品","白酒":"白酒","航空":"航空",
                         "化工":"化工","煤炭":"煤炭","有色":"有色","建材":"建材","家电":"家电"}.items():
            if kw in name:
                return ind
    cn = code[2:] if code[:2].isalpha() else code
    for prefix, ind in BROAD_INDUSTRY.items():
        if cn.startswith(prefix):
            return ind
    prefix3 = cn[:3]
    if prefix3 in ("600","601","603","605","000","001","002","003"):
        return "主板"
    return "其他"


def load_name_cache():
    if os.path.exists(NAME_CACHE_FILE):
        try:
            with open(NAME_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_name_cache(cache):
    atomic_json.atomic_dump(cache, NAME_CACHE_FILE, ensure_ascii=False, encoding="utf-8")


def batch_fetch_names(codes, cache):
    missing = [c for c in codes if c not in cache]
    if not missing:
        return cache
    for i in range(0, len(missing), 50):
        batch = missing[i:i + 50]
        try:
            url = f"http://hq.sinajs.cn/list={','.join(batch)}"
            req = urllib.request.Request(url, headers={
                "Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0",
            })
            resp = urllib.request.urlopen(req, timeout=30)
            data = resp.read().decode("gbk")
            for line in data.strip().split("\n"):
                line = line.strip()
                if line and '="' in line:
                    try:
                        cp = line.split("hq_str_")[1].split("=")[0]
                        cache[cp] = line.split('="')[1].split(",")[0]
                    except Exception:
                        pass
            print(f"    📡 批量获取名称: +{len(batch)}只 ({i + len(batch)}/{len(missing)})")
        except Exception as e:
            print(f"    ⚠️ 获取名称失败: {e}")
    save_name_cache(cache)
    return cache


def fetch_realtime_prices(codes):
    """返回 {code: {price, chg_pct, high, low, open, prev_close}}"""
    if not codes:
        return {}
    result = {}
    for i in range(0, len(codes), 50):
        batch = codes[i:i + 50]
        try:
            url = f"http://hq.sinajs.cn/list={','.join(batch)}"
            req = urllib.request.Request(url, headers={
                "Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0",
            })
            resp = urllib.request.urlopen(req, timeout=15)
            data = resp.read().decode("gbk")
            for line in data.strip().split("\n"):
                line = line.strip()
                if line and '="' in line:
                    try:
                        cp = line.split("hq_str_")[1].split("=")[0]
                        p = line.split('="')[1].split(",")
                        prev = float(p[2]) if p[2] else 0
                        cur = float(p[3]) if p[3] else 0
                        # 修复(2026-08-07): 盘前/停牌时cur=0 → 用昨收代替, 避免0价误报"跌破止损"
                        if cur <= 0 and prev > 0:
                            cur = prev
                        chg = (cur - prev) / prev * 100 if prev > 0 and cur > 0 else 0
                        result[cp] = {
                            "price": cur, "chg_pct": round(chg, 2),
                            "high": float(p[4]) if p[4] else 0,
                            "low": float(p[5]) if p[5] else 0,
                            "open": float(p[1]) if p[1] else 0,
                            "prev_close": prev,
                        }
                    except Exception:
                        pass
        except Exception as e:
            print(f"    ⚠️ 获取实时行情失败: {e}")
    return result


