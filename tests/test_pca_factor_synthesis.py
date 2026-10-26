# -*- coding: utf-8 -*-
"""test_pca_factor_synthesis.py — PCA 因子合成模块 TDD 测试

seam(公共接口) 独立真值断言, 防 tautology(不复用模块算法重算期望):
  - mad_winsorize / cross_section_zscore: 手算向量断言
  - spearman_rank_ic: 完全同序=1.0 / 完全逆序=-1.0
  - icir: 手算
  - pca_eigh: 完全共线双因子 -> PC1 方向 [0.707,0.707], 第二特征值≈0
  - 防泄露: fit_zscore(训练段) 后 transform_zscore(测试段) 必用训练段 mean/std
  - build_factor_panel: 未来收益=close[T+h], 因子值不含 T 之后数据
"""
import math
import pytest

from core.scoring.pca_factor_synthesis import (
    mad_winsorize, cross_section_zscore, spearman_rank_ic, icir,
    pca_eigh, fit_zscore, transform_zscore, grouped_pca,
    build_factor_panel, ic_vs_baseline, DEFAULT_GROUPS,
)
import numpy as np


class TestWinsorizeZscore:
    def test_mad_winsorize_clips_outlier(self):
        # [1,2,3,4,100]: med=3, mad=1, 边界=3±5*1.4826 → [−4.413, 10.413]
        out = mad_winsorize([1, 2, 3, 4, 100])
        assert out[:4] == [1, 2, 3, 4]
        assert out[4] == pytest.approx(10.413, rel=1e-3)  # 100 被 clip

    def test_mad_winsorize_normal_untouched(self):
        out = mad_winsorize([1, 2, 3, 4, 5])
        assert out == pytest.approx([1, 2, 3, 4, 5], rel=1e-3)

    def test_zscore_hand_computed(self):
        out = cross_section_zscore([1, 2, 3, 4, 5])
        # mean=3, std(ddof=0)=sqrt(2)=1.41421
        assert out == pytest.approx([-1.41421, -0.70711, 0.0, 0.70711, 1.41421], abs=1e-4)

    def test_zscore_handles_missing(self):
        out = cross_section_zscore([1, None, 3])
        assert out[1] == 0.0  # 缺失填 0


class TestSpearmanIcir:
    def test_spearman_perfect_positive(self):
        xs = list(range(30))
        assert spearman_rank_ic(xs, xs) == pytest.approx(1.0)

    def test_spearman_perfect_negative(self):
        xs = list(range(30))
        assert spearman_rank_ic(xs, list(reversed(xs))) == pytest.approx(-1.0)

    def test_spearman_too_few_returns_none(self):
        assert spearman_rank_ic([1, 2, 3], [1, 2, 3]) is None  # n<30

    def test_icir_hand_computed(self):
        # [0.1,0.2,0.3,0.4]: mean=0.25, std(ddof=1)=0.129099, ICIR=0.25/0.129099=1.9365
        assert icir([0.1, 0.2, 0.3, 0.4]) == pytest.approx(1.93649, rel=1e-4)

    def test_icir_single_point_none(self):
        assert icir([0.2]) is None


class TestPcaEigh:
    def test_collinear_factors_one_real_component(self):
        # 两因子完全共线 X=[[1,1],[2,2],[3,3]] -> 非零特征值=1(标准化后), 第二≈0
        X = np.array([[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]])
        vecs, eig = pca_eigh(X)
        assert eig[0] > 0
        assert eig[1] == pytest.approx(0.0, abs=1e-8)
        # numpy eigh: vecs[i,j]=因子i在PC_j的载荷. 共线 -> PC1(列0) 两因子载荷相等且同号
        p1 = vecs[:, 0]
        assert abs(p1[0] - p1[1]) < 1e-6   # 完全共线 -> 两因子对 PC1 载荷相等
        assert p1[0] * p1[1] > 0            # 同号

    def test_orthogonal_factors_equal_variance(self):
        # 两独立因子, 特征值之和 = 逐列方差之和(协方差矩阵 trace 不变量, 独立于模块算法)
        rng = np.random.RandomState(0)
        a = rng.randn(200); b = rng.randn(200)
        X = np.column_stack([a, b])
        vecs, eig = pca_eigh(X)
        trace = float(np.var(X[:, 0]) + np.var(X[:, 1]))  # np.var 默认 ddof=0, 与 np.cov(bias=True) 一致
        assert float(eig[0] + eig[1]) == pytest.approx(trace, rel=1e-6)
        # 两个独立因子, 方差近似均分
        assert 0.4 < eig[0] / trace < 0.6


class TestLeakPrevention:
    def test_transform_uses_train_params_not_test(self):
        train = {"f": [10, 12, 8, 20]}          # mean=12.5, std≈5.1
        test = {"f": [100, 102, 98, 110]}        # 若误用测试段 mean≈102.5 结果会不同
        params = fit_zscore(train)
        ztest = transform_zscore(params, test)
        # 用训练段参数: (100-12.5)/5.1≈17.2, 远大于1 → 证明用的是训练段 scale
        assert ztest["f"][0] > 15
        # 对照组: 若用测试段自身 zscore, (100-102.5)/5.1≈-0.49, 应 <0
        self_z = cross_section_zscore([100, 102, 98, 110])
        assert ztest["f"][0] != pytest.approx(self_z[0], abs=0.5)  # 两者确实不同


class TestGroupedPca:
    def test_group_pca_produces_named_pc_and_cumvar(self):
        rng = np.random.RandomState(1)
        n = 400
        # 组内 3 个强共线因子(都=一个主信号+噪声), 1 个噪声
        base = rng.randn(n)
        panel = {
            "m1": list(base + 0.1 * rng.randn(n)),
            "m2": list(1.2 * base + 0.1 * rng.randn(n)),
            "m3": list(base + 0.05 * rng.randn(n)),
            "noise": list(rng.randn(n)),
        }
        groups = {"momentum": ["m1", "m2", "m3"]}
        res = grouped_pca(panel, groups, n_pc=1)
        assert "momentum" in res
        assert res["momentum"]["pc_chosen"] == 1
        assert len(res["momentum"]["pc1"]) == n
        assert res["momentum"]["cum_var"][0] > 0.8  # 共线 -> PC1 解释大部分方差
        # 载荷: 3 个共线因子对 PC1 载荷同号且高
        ld = res["momentum"]["pcs"][0]["loadings"]
        assert len(ld) == 3
        signs = [1 if v > 0 else -1 for v in ld.values()]
        assert len(set(signs)) == 1  # 同号

    def test_group_missing_factors_skipped(self):
        panel = {"x": [1, 2, 3, 4] * 50}
        res = grouped_pca(panel, {"g": ["x", "y_missing"]})
        assert res["g"]["n_factors"] == 1  # 只 x


class TestBuildFactorPanel:
    def _bars(self, closes):
        return [{"date": f"d{i}", "close": c, "open": c, "high": c, "low": c,
                 "volume": 1000, "amount": 100000} for i, c in enumerate(closes)]

    def test_future_return_is_h_days_ahead(self):
        closes = list(range(1, 60))  # 1..59
        records = {"s1": self._bars([float(c) for c in closes])}
        codes, panel, fut = build_factor_panel(records, horizon=5, factors=["chg5"])
        assert codes == ["s1"]
        # 目标日 T = 有效末根(59) - horizon(5) = 54 (close=54? 索引) -> 未来收益=close[T+5]/close[T]-1
        # closes[T] = T+1, closes[T+5]=T+6 -> (T+6 - (T+1))/(T+1) = 5/(T+1)
        # T=54(0-index: 末根idx=58, T=58-5=53) -> closes[53]=54, closes[58]=59 -> 5/54
        assert fut[0] == pytest.approx(5.0 / 54.0, rel=1e-6)

    def test_factor_value_uses_only_past(self):
        # chg5 at target day uses close[T] and close[T-5]; perturb close after T, chg5 unchanged
        closes = [100.0] * 40 + [100.0] + [1.0] * 5  # 末5根拉到很低, 但目标日在更早
        records = {"s1": self._bars(closes)}
        codes, panel, _ = build_factor_panel(records, horizon=5, factors=["chg5"])
        # 目标日 T = 45-1-5 = 44; close[44]=100, close[39]=100 -> chg5=0
        assert panel["chg5"][0] == pytest.approx(0.0)

    def test_grouped_acceptance_runs(self):
        rng = np.random.RandomState(2)
        n = 350
        sig = rng.randn(n)
        panel = {"m1": list(sig), "m2": list(sig + 0.1 * rng.randn(n))}
        fut = list(0.3 * sig + 0.7 * rng.randn(n))
        rep = ic_vs_baseline(list(sig + 0.2 * rng.randn(n)),
                             {"m1": panel["m1"], "m2": panel["m2"]}, fut)
        assert rep["synthetic"]["rank_ic"] is not None
        assert "best_baseline" in rep


@pytest.mark.factor_ic
def test_default_groups_cover_all_reproducible():
    from core.scoring.pca_factor_synthesis import DEFAULT_FACTORS
    for g, fns in DEFAULT_GROUPS.items():
        for f in fns:
            assert f in DEFAULT_FACTORS, f"{g} 引用了未定义的因子 {f}"
