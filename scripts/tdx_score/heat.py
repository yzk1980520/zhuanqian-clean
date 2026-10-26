"""
行业热度数据模块 — 从 tdx_score.py 提取 (2026-09-23)
"""
import os
import json
from datetime import date

# 缓存
_INDUSTRY_HEAT_CACHE = None
_INDUSTRY_HEAT_DATE = None
_INDUSTRY_HEAT_FILE = None


def get_industry_heat(force_refresh=False):
    """
    获取东财行业板块涨跌幅排名热度。
    返回: {industry_name: rank_percentile(0~1)}
    """
    global _INDUSTRY_HEAT_CACHE, _INDUSTRY_HEAT_DATE, _INDUSTRY_HEAT_FILE

    today = str(date.today())
    if _INDUSTRY_HEAT_FILE is None:
        _INDUSTRY_HEAT_FILE = os.path.join(os.path.dirname(__file__), "data", "industry_heat.json")
        os.makedirs(os.path.dirname(_INDUSTRY_HEAT_FILE), exist_ok=True)

    # 尝试从文件缓存加载
    if not force_refresh and _INDUSTRY_HEAT_CACHE is None:
        try:
            with open(_INDUSTRY_HEAT_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f)
                if cached.get("date") == today:
                    _INDUSTRY_HEAT_CACHE = cached.get("data", {})
                    _INDUSTRY_HEAT_DATE = today
                    return _INDUSTRY_HEAT_CACHE
        except Exception as e:
            print(f"🔴 [heat.py:35] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", flush=True)
            pass

    if not force_refresh and _INDUSTRY_HEAT_CACHE and _INDUSTRY_HEAT_DATE == today:
        return _INDUSTRY_HEAT_CACHE

    result = {}
    try:
        import urllib.request
        hosts = [
            "push2delay.eastmoney.com",
            "82.push2.eastmoney.com",
            "push2.eastmoney.com",
        ]
        for host in hosts:
            try:
                url = f"https://{host}/api/qt/clist/get?pn=1&pz=50&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3&fs=m%3A90%2Bt%3A2&fields=f1,f2,f3,f4,f12,f13,f14"
                resp = urllib.request.urlopen(url, timeout=5)
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("data") and data["data"].get("diff"):
                    for item in data["data"]["diff"]:
                        name = item.get("f14", "")
                        rank = item.get("f2", 0)
                        total = item.get("f3", 1)
                        if name and total > 0:
                            result[name] = rank / total
                    break
            except Exception as e:
                print(f"🔴 [heat.py:62] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", flush=True)
                continue
    except Exception as e:
        print(f"⚠️ 行业热度获取失败: {e}")

    # 缓存结果
    if result:
        _INDUSTRY_HEAT_CACHE = result
        _INDUSTRY_HEAT_DATE = today
        try:
            with open(_INDUSTRY_HEAT_FILE, "w", encoding="utf-8") as f:
                json.dump({"date": today, "data": result}, f, ensure_ascii=False)
        except Exception as e:
            print(f"🔴 [heat.py:74] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", flush=True)
            pass

    return result
