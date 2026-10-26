# -*- coding: utf-8 -*-
"""
因子注册中心 — 元数据管理、缓存管理、方向记录

职责:
1. 因子元数据注册（ID/名称/类别/方向/IC/IR）
2. 因子缓存管理（计算结果持久化）
3. 因子方向记录（positive/negative/neutral）
4. 因子版本管理（IC衰减追踪）

关键修正:
- 支持负IC因子（反转因子）
- 行业/市值中性化支持
- 滚动样本外验证
"""
import json
import os
import hashlib
import numpy as np
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
# S4 基地化对齐 (2026-10-24 T051 C4): 裸 import core.pipeline.atomic_json 只绑定 core →
# 下方 atomic_json.* 全部 NameError。改 from-import 绑定真源模块名。
from core.pipeline import atomic_json


# ═══════════════════════════════════════════
#  配置常量
# ═══════════════════════════════════════════

REGISTRY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "data", "factor_registry")  # 基地化S3 (2026-10-22): 根锚点(core/scoring→仓库根)
CACHE_DIR = os.path.join(REGISTRY_DIR, "cache")
METADATA_FILE = os.path.join(REGISTRY_DIR, "registry.json")
IC_HISTORY_FILE = os.path.join(REGISTRY_DIR, "ic_history.json")

# ═══════════════════════════════════════════════════════════
#  门禁阈值 —— G4 收敛 (2026-10-17 W1)：唯一真源 = factor_gate_v2.GATE_CONFIG
# ═══════════════════════════════════════════════════════════
# 收敛前四套阈值互相打架：
#   (a) factor_gate_v2.GATE_CONFIG        : ic 0.03 / ir 0.3 / 单调性 0.02
#   (b) factor_registry.MIN_* (本文件)     : ic 0.03 / icir 0.3 / 单调性 0.7
#   (c) config/factor_thresholds.json      : icir停用 -0.2 / |ic| 0.03
#   (d) factors/*/__init__.py              : |ic|>=0.03 and icir>=0.3 (硬编码)
# 选 (a) 为唯一真源的依据（不是凭感觉，逐条实证）：
#   1. 生产实际消费点只有 (a)：evolution_loop._gate_g1_stat / _gate_g2_robust
#      经 make_gate_fn 注入，是新因子进生产 registry 前唯一的门禁；(b) 的
#      check_gate() 全仓零调用方；(c) 只被 tests + calc_risk_metrics 读。
#   2. (a) 的 ic_threshold=0.03 / ir_threshold=0.3 与 132d 权威引擎判定
#      status='valid' 的口径完全复现（实跑 28/28 因子全 MATCH，见 W1 报告）。
#   3. (b) 的 MIN_MONOTONICITY=0.7 是死常量（全仓零引用），且与 (a) 的
#      单调差 0.02 量纲不同，属历史误植，本次随收敛一并纠正为引用真源。
# 因此：本文件不再硬编码任何阈值，全部从真源派生。
# 回灌自 archive/root-py-batch3: 6adbea0a 回滚误删, 2026-10-21 合回根侧
def _load_gate_thresholds():
    """从唯一真源加载阈值。导入失败必须 fail loud，绝不静默回退到本地副本。"""
    from core.scoring.factor_gate_v2 import GATE_CONFIG
    return GATE_CONFIG


_GATE = _load_gate_thresholds()

MIN_IC_POSITIVE = _GATE["ic_threshold"]                 # 0.03  ← 真源
MIN_IC_NEGATIVE = -_GATE["ic_threshold"]                # -0.03 ← 真源
MIN_ICIR = _GATE["ir_threshold"]                        # 0.3   ← 真源
MIN_MONOTONICITY = _GATE["monotonicity_threshold"]      # 0.02  ← 真源(原 0.7 死常量已废弃)


# ═══════════════════════════════════════════
#  因子元数据类
# ═══════════════════════════════════════════

class FactorMetadata:
    """因子元数据"""
    
    def __init__(self, 
                 factor_id: str,
                 name: str,
                 category: str,
                 description: str,
                 direction: str = "neutral",  # positive/negative/neutral
                 ic_mean: float = 0.0,
                 icir: float = 0.0,
                 forward_horizon: int = 5,
                 formula: str = "",
                 dependencies: List[str] = None):
        self.factor_id = factor_id
        self.name = name
        self.category = category
        self.description = description
        self.direction = direction
        self.ic_mean = ic_mean
        self.icir = icir
        self.forward_horizon = forward_horizon
        self.formula = formula
        self.dependencies = dependencies or []
        self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()
        self.version = 1
        self.is_valid = False
        self.gate_status = "pending"  # pending/pass/fail
    
    def to_dict(self) -> Dict:
        return {
            "factor_id": self.factor_id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "direction": self.direction,
            "ic_mean": round(self.ic_mean, 6) if self.ic_mean is not None else None,
            "icir": round(self.icir, 4) if self.icir is not None else None,
            "forward_horizon": self.forward_horizon,
            "formula": self.formula,
            "dependencies": self.dependencies,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "version": self.version,
            "is_valid": self.is_valid,
            "gate_status": self.gate_status
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "FactorMetadata":
        f = cls(
            factor_id=data["factor_id"],
            name=data["name"],
            category=data["category"],
            description=data.get("description", ""),
            direction=data.get("direction", "neutral"),
            ic_mean=data.get("ic_mean"),
            icir=data.get("icir"),
            forward_horizon=data.get("forward_horizon", 5),
            formula=data.get("formula", ""),
            dependencies=data.get("dependencies", [])
        )
        f.created_at = data.get("created_at", f.created_at)
        f.updated_at = data.get("updated_at", f.updated_at)
        f.version = data.get("version", 1)
        f.is_valid = data.get("is_valid", False)
        f.gate_status = data.get("gate_status", "pending")
        return f


# ═══════════════════════════════════════════
#  因子注册中心类
# ═══════════════════════════════════════════

class FactorRegistry:
    """因子注册中心"""

    def __init__(self, registry_dir: str = REGISTRY_DIR):
        self.registry_dir = registry_dir
        self.cache_dir = os.path.join(registry_dir, "cache")
        # 使用实例级路径，而非全局常量（支持测试注入）
        self._metadata_file = os.path.join(registry_dir, "registry.json")
        self._ic_history_file = os.path.join(registry_dir, "ic_history.json")
        self.registry: Dict[str, FactorMetadata] = {}
        self._extras: Dict[str, Dict] = {}  # passthrough: 保留原始完整dict，扩展字段透传不丢失
        self.ic_history = []   # R5: 运行时 ic_history, 实际 schema 由 _load 按磁盘类型装载(dict{"history":{...}} / record-list)
        self._load()
    
    def _load(self):
        """加载注册表和IC历史"""
        os.makedirs(self.registry_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)

        if os.path.exists(self._metadata_file):
            with open(self._metadata_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            _failed = []
            for fid, meta_data in data.get("factors", {}).items():
                try:
                    self.registry[fid] = FactorMetadata.from_dict(meta_data)
                    # passthrough: 保存原始完整dict（含扩展字段），_save时透传不丢
                    self._extras[fid] = dict(meta_data)
                except Exception as _e:   # per-factor 隔离: 一条坏不连累整体, 但 loud 诊断(静默吞=埋雷)
                    _failed.append((fid, _e))
            if _failed:
                for _fid, _e in _failed:
                    print(f"⚠️ [registry._load] 因子 {_fid} 加载失败({type(_e).__name__}: {_e}) — 已跳过, 需修复该因子 schema")
                print(f"⚠️ [registry._load] {len(_failed)}/{len(data.get('factors', {}))} 因子加载失败, 请核查 schema (非静默吞)")
        
        if os.path.exists(self._ic_history_file):
            with open(self._ic_history_file, 'r', encoding='utf-8') as f:
                _loaded = json.load(f)
            # R5 修复: ic_history.json 真 schema 是 dict {"history":{factor:[ic,...]}} (factor_ic_monitor 主写),
            # 根版此前误当 record-list → update_ic 崩/日监控假绿。此处按磁盘实际类型装载, 不改盘上形态:
            #   dict  → 原样保留(不动 factor_ic_monitor 的 {history,last_updated} 结构, 不丢数据)
            #   list  → record-list 旧形态, 保留
            #   其它  → 损坏/空, 置空 list + loud 诊断(不静默吞)
            if isinstance(_loaded, dict):
                self.ic_history = _loaded
            elif isinstance(_loaded, list):
                self.ic_history = _loaded
            else:
                self.ic_history = []
                print(f"⚠️ [registry._load] ic_history.json 类型异常({type(_loaded).__name__}), 已置空 list (不静默吞)")
    
    def _save(self):
        """保存注册表（passthrough: 扩展字段不透传丢失）

        策略：以原始完整dict（self._extras）为基底，用当前FactorMetadata标准字段覆盖。
        标准字段更新为新值，不在标准字段中的扩展字段（strong_line等）原样保留。
        """
        data = {
            "version": "1.0.0",
            "updated_at": datetime.now().isoformat(),
            "factors": {}
        }
        # 标准15字段列表（to_dict输出）
        _STANDARD_FIELDS = {
            "factor_id", "name", "category", "description", "direction",
            "ic_mean", "icir", "forward_horizon", "formula", "dependencies",
            "created_at", "updated_at", "version", "is_valid", "gate_status"
        }
        for fid, f in self.registry.items():
            # 基底：原始完整dict（含扩展字段）
            saved = dict(self._extras.get(fid, {}))
            # 只覆盖标准字段（不碰扩展字段）
            std_dict = f.to_dict()
            for k in _STANDARD_FIELDS:
                if k in std_dict:
                    saved[k] = std_dict[k]
            # 同步更新 _extras（保持内存与磁盘一致）
            self._extras[fid] = saved
            data["factors"][fid] = saved
        atomic_json.atomic_dump(data, self._metadata_file, ensure_ascii=False, encoding='utf-8')
    
    def _save_ic_history(self):
        """保存IC历史"""
        atomic_json.atomic_dump(self.ic_history, self._ic_history_file, ensure_ascii=False, encoding='utf-8')
    
    def register(self, metadata: FactorMetadata) -> bool:
        """注册新因子"""
        if metadata.factor_id in self.registry:
            # 更新已有因子
            old = self.registry[metadata.factor_id]
            metadata.version = old.version + 1
            metadata.created_at = old.created_at
        self.registry[metadata.factor_id] = metadata
        self._save()
        return True
    
    def get(self, factor_id: str) -> Optional[FactorMetadata]:
        """获取因子元数据"""
        return self.registry.get(factor_id)
    
    def list_factors(self, category: str = None, direction: str = None,
                     min_ic: float = None, min_icir: float = None) -> List[FactorMetadata]:
        """列出因子（支持过滤）"""
        results = []
        for f in self.registry.values():
            if category and f.category != category:
                continue
            if direction and f.direction != direction:
                continue
            if min_ic is not None:
                if f.ic_mean is None:
                    continue   # 隔离因子无法对阈值排序, 直接排除
                if f.direction == "positive" and f.ic_mean < min_ic:
                    continue
                if f.direction == "negative" and f.ic_mean > -min_ic:
                    continue
            if min_icir is not None:
                if f.icir is None:
                    continue   # 隔离因子无法对阈值排序, 直接排除
                if f.icir < min_icir:
                    continue
            results.append(f)
        return results
    
    def get_valid_factors(self) -> List[FactorMetadata]:
        """获取通过门禁的因子"""
        return [f for f in self.registry.values() if f.is_valid]
    
    def get_by_direction(self, direction: str) -> List[FactorMetadata]:
        """按方向获取因子"""
        return [f for f in self.registry.values() if f.direction == direction]
    
    def update_ic(self, factor_id: str, ic: float, icir: float = None,
                  date_str: str = None, window: str = "full"):
        """更新因子IC（带时间戳）。

        R5 修复: ic_history 实际 schema 是 dict {"history":{factor:[ic,...]}} (factor_ic_monitor 主写),
        旧代码把它当 record-list 直接 .append → AttributeError + 日监控缺 icir 参 TypeError,
        叠在 try/except 里被吞 = "已同步"假绿。现按实际类型感知:
          - dict: 追加 ic 到 self.ic_history["history"][factor_id] (round-trip 保 last_updated)
          - list: 追加 record dict (旧 record-list 形态, 向后兼容)
        icir 可选: 不传则保持原值(不洗成 None), 避免把未重算的 icir 置空。
        """
        if factor_id not in self.registry:
            return

        if isinstance(self.ic_history, dict):
            series = self.ic_history.setdefault("history", {}).setdefault(factor_id, [])
            series.append(ic)
            self.ic_history["last_updated"] = datetime.now().isoformat()
        else:
            record = {
                "factor_id": factor_id,
                "ic": ic,
                "icir": icir,
                "date": date_str or date.today().isoformat(),
                "window": window,
                "timestamp": datetime.now().isoformat()
            }
            self.ic_history.append(record)

        # 更新元数据 (icir 可选: 不传则不动, 不洗成 None)
        f = self.registry[factor_id]
        f.ic_mean = ic
        if icir is not None:
            f.icir = icir
        f.updated_at = datetime.now().isoformat()

        self._save()
        self._save_ic_history()
    
    def check_gate(self, factor_id: str) -> Tuple[bool, str]:
        """
        门禁检查（修正版：支持负IC因子）
        
        Returns:
            (pass: bool, reason: str)
        """
        if factor_id not in self.registry:
            return False, "因子未注册"
        
        f = self.registry[factor_id]
        
        # Kimi-41 Q1: ic_mean/icir 隔离为 None(旧 IC 移 ic_history) → 不可用于门禁, 直接 fail(不 crash, 不误 pass)
        if f.ic_mean is None or f.icir is None:
            return False, f"{f.factor_id} IC已隔离(ic_mean={f.ic_mean}, 见 ic_history), 待独立复核后不可通过门禁"
        
        # 检查IC
        if f.direction == "positive":
            if f.ic_mean < MIN_IC_POSITIVE:
                return False, f"正向因子IC={f.ic_mean:.4f} < {MIN_IC_POSITIVE}"
        elif f.direction == "negative":
            if f.ic_mean > MIN_IC_NEGATIVE:  # -0.03
                return False, f"反转因子IC={f.ic_mean:.4f} > {MIN_IC_NEGATIVE}"
        else:
            if abs(f.ic_mean) < MIN_IC_POSITIVE:
                return False, f"中性因子|IC|={abs(f.ic_mean):.4f} < {MIN_IC_POSITIVE}"
        
        # 检查ICIR
        if f.icir < MIN_ICIR:
            return False, f"ICIR={f.icir:.2f} < {MIN_ICIR}"
        
        # 通过
        f.gate_status = "pass"
        f.is_valid = True
        self._save()
        return True, "通过门禁"
    
    def compute_cache_key(self, factor_id: str, date_str: str, codes: List[str]) -> str:
        """计算缓存键"""
        data = f"{factor_id}:{date_str}:{'|'.join(sorted(codes))}"
        return hashlib.md5(data.encode()).hexdigest()[:16]
    
    def get_cache(self, factor_id: str, date_str: str, codes: List[str]) -> Optional[Dict]:
        """从缓存获取因子值"""
        cache_key = self.compute_cache_key(factor_id, date_str, codes)
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.json")
        
        if not os.path.exists(cache_file):
            return None
        
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None
    
    def set_cache(self, factor_id: str, date_str: str, codes: List[str], 
                  values: Dict[str, float]):
        """设置因子缓存"""
        cache_key = self.compute_cache_key(factor_id, date_str, codes)
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.json")
        
        data = {
            "factor_id": factor_id,
            "date": date_str,
            "codes": codes,
            "values": values,
            "cached_at": datetime.now().isoformat()
        }
        
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    
    def generate_report(self) -> str:
        """生成注册表报告"""
        lines = []
        lines.append("=" * 60)
        lines.append("因子注册中心报告")
        lines.append("=" * 60)
        lines.append(f"注册时间: {datetime.now().isoformat()}")
        lines.append(f"注册因子数: {len(self.registry)}")
        lines.append(f"通过门禁数: {sum(1 for f in self.registry.values() if f.is_valid)}")
        lines.append("")
        
        # 按方向统计
        positive = [f for f in self.registry.values() if f.direction == "positive"]
        negative = [f for f in self.registry.values() if f.direction == "negative"]
        neutral = [f for f in self.registry.values() if f.direction == "neutral"]
        
        lines.append("## 按方向统计")
        lines.append(f"- 正向因子: {len(positive)}")
        lines.append(f"- 反转因子: {len(negative)}")
        lines.append(f"- 中性因子: {len(neutral)}")
        lines.append("")
        
        # 按类别统计
        categories = defaultdict(int)
        for f in self.registry.values():
            categories[f.category] += 1
        lines.append("## 按类别统计")
        for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
            lines.append(f"- {cat}: {count}")
        lines.append("")
        
        # 通过门禁的因子
        valid = self.get_valid_factors()
        if valid:
            lines.append("## 通过门禁的因子 (Top 20)")
            valid_sorted = sorted(valid, key=lambda x: abs(x.ic_mean) if x.ic_mean is not None else -1.0, reverse=True)
            for i, f in enumerate(valid_sorted[:20], 1):
                ic_s = "isolated" if f.ic_mean is None else f"{f.ic_mean:.4f}"
                ir_s = "isolated" if f.icir is None else f"{f.icir:.2f}"
                lines.append(f"  {i}. {f.factor_id} ({f.direction}) IC={ic_s} IR={ir_s}")
        
        return "\n".join(lines)


# ═══════════════════════════════════════════
#  便捷函数
# ═══════════════════════════════════════════

_registry = None

def get_registry() -> FactorRegistry:
    global _registry
    if _registry is None:
        _registry = FactorRegistry()
    return _registry

def register_factor(factor_id: str, name: str, category: str, 
                   direction: str = "neutral", ic_mean: float = 0.0,
                   icir: float = 0.0, forward_horizon: int = 5,
                   formula: str = "") -> FactorMetadata:
    """便捷注册因子"""
    meta = FactorMetadata(
        factor_id=factor_id,
        name=name,
        category=category,
        description=f"{name}因子",
        direction=direction,
        ic_mean=ic_mean,
        icir=icir,
        forward_horizon=forward_horizon,
        formula=formula
    )
    get_registry().register(meta)
    return meta


if __name__ == "__main__":
    reg = FactorRegistry()
    
    # 注册一些测试因子
    test_factors = [
        FactorMetadata("VR5_20", "量比(5/20)", "volume_ratio", "近期成交量与20日均量比值", 
                      "positive", 0.045, 0.38, 5),
        FactorMetadata("RSI14", "RSI14", "momentum", "14日相对强弱指标", 
                      "negative", -0.038, 0.32, 5),
        FactorMetadata("MDD60", "60日最大回撤", "drawdown", "近60日最大回撤幅度", 
                      "positive", 0.045, 0.38, 10),
    ]
    
    for f in test_factors:
        reg.register(f)
    
    print(reg.generate_report())
