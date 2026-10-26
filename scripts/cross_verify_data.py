import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
"""交叉验证: 智妍数据源(东财/新浪/腾讯) vs 本机TDX (2026-08-13)"""
import sys, io, json, urllib.request, os
if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.path.insert(0, r"D:\open code\zhuanqian")
    os.chdir(r"D:\open code\zhuanqian")

def em_realtime(code):
    """东财实时: code 6位, 转 1.xxx/0.xxx"""
    em_code = ("1." if code.startswith("6") else "0.") + code
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={em_code}&fields=f43,f57,f58,f169,f170"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        if d.get("data"):
            return {"price": d["data"].get("f43", 0) / 100 if d["data"].get("f43") else None,
                    "name": d["data"].get("f58", "")}
    except Exception as ex:
        return {"error": str(ex)[:80]}
    return None

def sina_realtime(code):
    """新浪实时"""
    prefix = "sh" if code.startswith("6") else "sz"
    url = f"http://hq.sinajs.cn/list={prefix}{code}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"})
    raw = urllib.request.urlopen(req, timeout=10).read().decode("gb2312", errors="ignore")
    parts = raw.split('"')[1].split(",")
    if len(parts) > 3:
        return {"price": float(parts[3]) if parts[3] else None, "name": parts[0]}
    return None

def tdx_price(code):
    """TDX本地最新收盘 (需带前缀 sh/sz)"""
    from core.pipeline.tdx_core import get_tdx_data
    prefix = "sh" if code.startswith("6") else "sz"
    recs = get_tdx_data(prefix + code, 5)
    if recs:
        return {"price": float(recs[-1]["close"]), "date": str(recs[-1]["date"])}
    return None

if __name__ == "__main__":
    for code, name in [("600276", "恒瑞医药"), ("002979", "雷赛智能")]:
        print("=" * 50)
        print(f"{code} {name}")
        t = tdx_price(code)
        e = em_realtime(code)
        s = sina_realtime(code)
        print(f"  TDX本地: {t}")
        print(f"  东财:    {e}")
        print(f"  新浪:    {s}")
        # 一致性判断 (现价3源对比, TDX用最新收盘)
        prices = [x["price"] for x in (t, e, s) if x and x.get("price")]
        if len(prices) >= 2:
            diff = max(prices) - min(prices)
            print(f"  ✅ 差异: {diff:.2f}元 ({'一致' if diff < 0.01 else '⚠️有差异'})")
