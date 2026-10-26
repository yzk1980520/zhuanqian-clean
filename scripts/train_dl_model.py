"""
train_dl_model.py - CNN-LSTM-Attention 深度学习模型训练脚本
==============================================================
任务ID: DL-2026-09-24  |  优先级: P1
拍板决策: DL-2026-09-24-P1

架构: CNN-LSTM-Attention (纯NumPy实现，无需torch)
特征: [daily_return, turnover, rsi, volume_ratio, qfq_ratio]
序列: 60天
标签: OC1d (T+1开盘收益率)
门禁: IC>0.03 + IR>0.3 + 单调性检验 + 132日全量确认

DL权重: 20% (保守起步，后续可上调)
"""

import sys
import os
import json
import time
import pickle
import logging
from datetime import datetime
from pathlib import Path
from collections import OrderedDict

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

LOG_DIR = PROJECT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR = PROJECT / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "train_dl_model.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("train_dl_model")

# ---------------------------------------------------------------------------
# Hyper-parameters  (拍板确认值)
# ---------------------------------------------------------------------------
SEQ_LEN          = 60
N_FEATURES       = 5
FEATURES         = ["daily_return", "turnover", "rsi", "volume_ratio", "qfq_ratio"]

CNN_FILTERS      = 4      # 极简滤波器
CNN_KERNEL       = 3
LSTM_HID         = 8      # 最小LSTM维度
DENSE_HID        = 16     # 最小Dense维度
ATTENTION_HID    = 8      # 最小Attention维度
DROPOUT_RATE     = 0.05   # 极低dropout

LR_INIT          = 1e-3
BATCH_SIZE       = 2048   # 极大批次
MAX_EPOCHS       = 5      # 最少轮数
PATIENCE         = 2      # 积极早停
EARLY_STOP_TOL   = 1e-2

TRAIN_RATIO      = 0.75
VAL_RATIO        = 0.15
TEST_RATIO       = 0.10
CNN_OUT_LEN      = None  # Computed in model init as seq_len - CNN_KERNEL + 1

# 门禁标准（老大拍板）
IC_THRESHOLD     = 0.03
IR_THRESHOLD     = 0.3
MIN_ROLLING_POS  = 3          # ≥3个滚动窗口IC>0
ROLLING_WIN      = 60         # 滚动窗口大小（交易日）

MODEL_PATH       = MODEL_DIR / "dl_predictor.pkl"
METRICS_PATH     = MODEL_DIR / "training_metrics.json"
SCALER_PATH      = MODEL_DIR / "feature_scaler.pkl"

# TDX数据路径
TDX_BASE = Path("D:/TDX/vipdoc")


# ============================================================================
# 1.  特征工程
# ============================================================================

def _pct(a):
    """array版pct_change"""
    return np.concatenate([[np.nan], (a[1:] - a[:-1]) / (a[:-1] + 1e-12)])

def _ema(series, span):
    """指数移动平均 (numpy)"""
    α = 2.0 / (span + 1)
    out = np.empty_like(series, dtype=np.float64)
    out[0] = series[0] if not np.isnan(series[0]) else 0.0
    for i in range(1, len(series)):
        out[i] = α * series[i] + (1 - α) * out[i - 1]
    return out

def compute_rsi(close, window=14):
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    ema_g = _ema(gain, window)
    ema_l = _ema(loss, window)
    rs = ema_g / (ema_l + 1e-12)
    return 100.0 - 100.0 / (1.0 + rs)

def compute_volume_ratio(volume, window=5):
    ma = volume.rolling(window=window, min_periods=1).mean().values
    return volume.values / (ma + 1e-12)

def extract_features(records):
    """从TDX records列表构建特征矩阵 (n_days, N_FEATURES)。

    records: list of dict  {date, open, high, low, close, volume, amount}
    """
    if not records or len(records) < SEQ_LEN + 10:
        return None

    closes = np.array([r["close"] for r in records], dtype=np.float64)
    opens  = np.array([r["open"]  for r in records], dtype=np.float64)
    vols   = np.array([r["volume"] for r in records], dtype=np.float64)
    amounts = np.array([r["amount"] for r in records], dtype=np.float64)

    daily_ret  = _pct(closes)
    avg_price  = (opens + closes) / 2.0
    turnover   = amounts / (avg_price * vols + 1e-12)
    rsi        = compute_rsi(closes, window=14)
    vol_ratio  = compute_volume_ratio(pd.Series(vols), window=5)
    qfq_ratio  = _pct(closes) + 1.0   # close[t]/close[t-1]

    feats = np.column_stack([daily_ret, turnover, rsi, vol_ratio, qfq_ratio])
    valid = ~np.any(np.isnan(feats), axis=1)
    feats = feats[valid]

    return feats if feats.shape[0] >= SEQ_LEN + 5 else None


# ============================================================================
# 2.  数据加载
# ============================================================================

def load_all_stocks(max_stocks=None):
    """从 TDX vipdoc 目录加载日线，返回 {code: features_array}。max_stocks限制数量"""
    from tdx_data import parse_tdx_day, load_name_cache

    log.info("开始加载 TDX 历史数据...")
    name_cache = load_name_cache()
    all_data = {}
    total = 0
    valid = 0

    for market in ("sh", "sz"):
        d = TDX_BASE / market / "lday"
        if not d.exists():
            continue
        for fp in d.glob("*.day"):
            code = fp.stem
            total += 1
            # 跳过指数
            if (code.startswith("sh000") and len(code) <= 6) or \
               (code.startswith("sz399") and len(code) <= 6):
                continue
            recs = parse_tdx_day(str(fp))
            if not recs:
                continue
            feats = extract_features(recs)
            if feats is None:
                continue
            all_data[code] = feats
            valid += 1
            if valid % 500 == 0:
                log.info(f"  进度: {total}文件, 有效{valid}只...")
            # 早停：达到目标数量即可
            if max_stocks and valid >= max_stocks:
                log.info(f"  已加载{valid}只，达到目标，提前停止...")
                break
        if max_stocks and valid >= max_stocks:
            break

    log.info(f"TDX数据加载完成: {total} 文件 → {valid} 只有效股票")
    return all_data


def build_sequences(all_data, max_stocks=None):
    """构建 (samples, seq_len, n_features) 序列和 OC1d 标签。

    标签: OC1d = (open[t+1] / close[t] - 1)
    由于extract_features已丢弃原始价格，用daily_return[t+1]近似OC1d。
    """
    # 限制股票数量以控制内存
    if max_stocks and len(all_data) > max_stocks:
        codes = list(all_data.keys())
        np.random.seed(42)
        sampled = np.random.choice(codes, max_stocks, replace=False)
        codes = sorted(sampled.tolist() if hasattr(sampled, 'tolist') else sampled)
        log.info(f"采样 {max_stocks} 只股票（共{len(all_data)}只可用）")
        all_data = {c: all_data[c] for c in codes}

    # 先统计样本数
    n_samples = 0
    for code, feats in all_data.items():
        n = len(feats)
        if n >= SEQ_LEN + 5:
            n_samples += n - SEQ_LEN - 1
    log.info(f"预计样本数: {n_samples}")

    X_list, y_list, codes_list, dates_list = [], [], [], []

    for code, feats in all_data.items():
        n = len(feats)
        if n < SEQ_LEN + 5:
            continue
        for i in range(SEQ_LEN, n - 1):
            seq = feats[i - SEQ_LEN: i]
            label = feats[i, 0]          # daily_return at t+1 (OC1d近似)
            X_list.append(seq)
            y_list.append(label)
            codes_list.append(code)
            dates_list.append(i)

    X = np.array(X_list, dtype=np.float32)   # float32节省一半内存
    y = np.array(y_list, dtype=np.float32)
    log.info(f"序列构建完成: {len(X)} samples, shape={X.shape}")
    return X, y, codes_list, dates_list


# ============================================================================
# 3.  纯NumPy CNN-LSTM-Attention 模型
# ============================================================================

# --- 激活函数 ---
def _relu(x):      return np.maximum(0, x)
def _relu_g(x):     return (x > 0).astype(np.float64)
def _sigmoid(x):    return 1.0 / (1.0 + np.exp(-np.clip(x, -500, 500)))
def _sigmoid_g(s):  return s * (1.0 - s)
def _tanh(x):       return np.tanh(x)
def _tanh_g(t):     return 1.0 - t ** 2


def _layer_norm(x, γ, β, eps=1e-8):
    μ = np.mean(x, axis=-1, keepdims=True)
    σ = np.std(x, axis=-1, keepdims=True) + eps
    return γ * (x - μ) / σ + β

def _layer_norm_g(dout, x, γ, β, eps=1e-8):
    """Layer norm backward for 2D or 3D tensors."""
    orig_shape = dout.shape
    N = int(np.prod(orig_shape[:-1]))
    M = orig_shape[-1]
    dout_flat = dout.reshape(N, M)
    x_flat = x.reshape(N, M)
    μ = np.mean(x_flat, axis=-1, keepdims=True)
    σ = np.std(x_flat, axis=-1, keepdims=True) + eps
    xh = (x_flat - μ) / σ
    dγ = np.sum(dout_flat * xh, axis=0, keepdims=True)
    dβ = np.sum(dout_flat, axis=0, keepdims=True)
    dx = dout_flat * γ / σ
    dx -= np.mean(dx, axis=-1, keepdims=True)
    dx -= xh * np.mean(dx * xh, axis=-1, keepdims=True)
    dx /= σ
    return dx.reshape(orig_shape), dγ.reshape(-1), dβ.reshape(-1)


# --- CNN Block ---
class CNNBlock:
    def __init__(self, n_filters, kernel, in_ch):
        self.n_filters = n_filters
        self.kernel    = kernel
        self.in_ch     = in_ch
        sc = np.sqrt(2.0 / (kernel * in_ch))
        self.W = np.random.randn(n_filters, kernel, in_ch) * sc
        self.b = np.zeros(n_filters)
        self._in = None
        self._pre = None

    def forward(self, x):
        self._in  = x
        B, T, C   = x.shape
        out_T     = T - self.kernel + 1
        out       = np.zeros((B, self.n_filters, out_T))
        self._pre = np.zeros_like(out)
        for f in range(self.n_filters):
            Wf = self.W[f]
            for t in range(out_T):
                w = x[:, t:t+self.kernel, :]
                s = np.sum(w * Wf[None], axis=(1, 2)) + self.b[f]
                out[:, f, t] = s
                self._pre[:, f, t] = s
        return _relu(out)

    def backward(self, dout):
        dx   = np.zeros(self._in.shape)
        dW   = np.zeros_like(self.W)
        db   = np.zeros_like(self.b)
        B, T, C = self._in.shape
        out_T = dout.shape[2]
        dr   = dout * _relu_g(self._pre)

        for f in range(self.n_filters):
            for t in range(out_T):
                w   = self._in[:, t:t+self.kernel, :]
                dW[f] += np.sum(dr[:, f, t:t+1, None] * w, axis=0)
                db[f]  += np.sum(dr[:, f, t:t+1])
                dx[:, t:t+self.kernel, :] += dr[:, f, t:t+1, None] * self.W[f][None]

        self.dW, self.db = dW, db
        return dx

    def update(self, lr):
        self.W -= lr * self.dW
        self.b -= lr * self.db

    def save(self):
        return {"W": self.W.copy(), "b": self.b.copy()}
    def load(self, s):
        self.W = s["W"].copy(); self.b = s["b"].copy()


# --- LSTM Block ---
class LSTMBlock:
    def __init__(self, inp, hid):
        self.inp = inp
        self.hid = hid
        sc = np.sqrt(2.0 / (inp + hid))
        self.Wx = np.random.randn(4*hid, inp) * sc
        self.Wh = np.random.randn(4*hid, hid) * sc
        self.b  = np.zeros(4*hid)
        # Layer norm
        self.γh = np.ones(hid); self.βh = np.zeros(hid)
        self._cache = {}

    def forward(self, x):
        B, T, _ = x.shape
        h, c = np.zeros((B, T+1, self.hid)), np.zeros((B, T+1, self.hid))
        Wx = self.Wx; Wh = self.Wh; b = self.b
        for t in range(T):
            xt, hp, cp = x[:,t,:], h[:,t,:], c[:,t,:]
            gates = xt @ Wx.T + hp @ Wh.T + b            # (B, 4*hid)
            f = _sigmoid(gates[:, :self.hid])
            i = _sigmoid(gates[:, self.hid:2*self.hid])
            o = _sigmoid(gates[:, 2*self.hid:3*self.hid])
            ct_ = _tanh(gates[:, 3*self.hid:])
            c[:, t+1] = f * cp + i * ct_
            h[:, t+1] = o * _tanh(c[:, t+1])
        self._cache = {"x": x, "h": h, "c": c,
                       "f": _sigmoid(x @ Wx[:self.hid].T + h[:,:-1] @ Wh[:self.hid].T + b[:self.hid]),
                       "i": _sigmoid(x @ Wx[self.hid:2*self.hid].T + h[:,:-1] @ Wh[self.hid:2*self.hid].T + b[self.hid:2*self.hid]),
                       "o": _sigmoid(x @ Wx[2*self.hid:3*self.hid].T + h[:,:-1] @ Wh[2*self.hid:3*self.hid].T + b[2*self.hid:3*self.hid]),
                       "ct": _tanh(x @ Wx[3*self.hid:].T + h[:,:-1] @ Wh[3*self.hid:].T + b[3*self.hid:]),
                       "h_prev": h[:, :-1]}
        out = _layer_norm(h[:, 1:], self.γh, self.βh)
        return out

    def backward(self, dout):
        c = self._cache
        x, h, C = c["x"], c["h"], c["c"]
        f, i, o, ct_ = c["f"], c["i"], c["o"], c["ct"]
        hp = c["h_prev"]
        B, T, hid = x.shape
        inp = self.inp

        dx  = np.zeros_like(x)
        dWx = np.zeros_like(self.Wx)
        dWh = np.zeros_like(self.Wh)
        db  = np.zeros(4*hid)
        dγh, dβh = np.zeros(hid), np.zeros(hid)

        dh_out, dγh, dβh = _layer_norm_g(dout, h[:, 1:], self.γh, self.βh)
        # Actual batch size may differ from cached (e.g. last batch)
        B_actual = dh_out.shape[0]
        T_actual = T  # Use cached T (from forward pass)
        dh_next = np.zeros((B_actual, 1, hid))
        dc_next = np.zeros((B_actual, 1, hid))

        Wx_f, Wx_i, Wx_o, Wx_c = np.split(self.Wx, 4, axis=0)
        b_f, b_i, b_o, b_c = np.split(self.b, 4)
        Wh_f, Wh_i, Wh_o, Wh_c = np.split(self.Wh, 4, axis=0)

        # Initialize per-gate accumulators
        dWx_f = np.zeros_like(Wx_f); dWx_i = np.zeros_like(Wx_i)
        dWx_o = np.zeros_like(Wx_o); dWx_c = np.zeros_like(Wx_c)
        dWh_f = np.zeros_like(Wh_f); dWh_i = np.zeros_like(Wh_i)
        dWh_o = np.zeros_like(Wh_o); dWh_c = np.zeros_like(Wh_c)
        db_f = np.zeros_like(b_f);   db_i = np.zeros_like(b_i)
        db_o = np.zeros_like(b_o);   db_c = np.zeros_like(b_c)

        for t in reversed(range(T)):
            ht, ct_pre = h[:, t+1], C[:, t]
            dh = dh_out[:, t] + dh_next[:, 0]  # (B_actual, hid)
            dtanh_ct = _tanh(C[:, t+1])         # (B_actual, hid)

            # Clip dh to prevent gradient explosion
            dh = np.clip(dh, -1.0, 1.0)

            # df/di/do/dct_ should be (B_actual,)
            term_f = dh * dtanh_ct * _sigmoid_g(f[:, t])
            df = term_f.sum(-1)  # (B_actual,)
            term_i = dh * ct_[:, t] * _sigmoid_g(i[:, t])
            di = term_i.sum(-1)  # (B_actual,)
            term_o = dh * dtanh_ct * _sigmoid_g(o[:, t])
            do = term_o.sum(-1)  # (B_actual,)
            term_c = dh * i[:, t] * _tanh_g(ct_[:, t])
            dct_ = term_c.sum(-1)   # (B_actual,)

            dc = dh * o[:, t] * _tanh_g(dtanh_ct) + dc_next[:, 0]  # (B_actual, hid)
            dc = np.clip(dc, -1.0, 1.0)  # Clip dc

            xt, hpt = x[:B_actual, t], hp[:B_actual, t]

            # df/di/do/dct_ are (B_actual,) scalars - use them directly with dc
            # dWx shape: (4*inp, hid) = (inp, hid) for each gate
            dWx_f += xt.T @ (df[:, None] * dc)      # (inp, B_actual) @ (B_actual, hid) = (inp, hid)
            dWx_i += xt.T @ (di[:, None] * dc)
            dWx_o += xt.T @ (do[:, None] * dc)
            dWx_c += xt.T @ (dct_[:, None] * ct_[:B_actual, t])  # ct_ is (B_actual, hid)

            # dWh shape: (hid, hid) for each gate
            dWh_f += hpt.T @ (df[:, None] * dc)     # (hid, B_actual) @ (B_actual, hid) = (hid, hid)
            dWh_i += hpt.T @ (di[:, None] * dc)
            dWh_o += hpt.T @ (do[:, None] * dc)
            dWh_c += hpt.T @ (dct_[:, None] * ct_[:B_actual, t])

            # Bias gradients: sum over batch → (hid,)
            # df, di, do, dct_ are (B_actual,), dc is (B_actual, hid)
            db_f  += (df[:, None] * dc).sum(axis=0)  # (B, hid) -> sum B -> (hid,)
            db_i  += (di[:, None] * dc).sum(axis=0)
            db_o  += (do[:, None] * dc).sum(axis=0)
            db_c  += (dct_[:, None] * ct_[:B_actual, t]).sum(axis=0)

            # dx: (B_actual, inp) from Wx gradients
            dx[:B_actual, t] = (df[:, None] * dc) @ Wx_f.T + \
                       (di[:, None] * dc) @ Wx_i.T + \
                       (do[:, None] * dc) @ Wx_o.T + \
                       (dct_[:, None] * ct_[:B_actual, t]) @ Wx_c.T

            # dh_next: propagate to previous timestep
            dh_next = ((df[:, None] * dc)[:, None] @ Wh_f.T +
                       (di[:, None] * dc)[:, None] @ Wh_i.T +
                       (do[:, None] * dc)[:, None] @ Wh_o.T +
                       (dct_[:, None] * ct_[:B_actual, t])[:, None] @ Wh_c.T)

        dWx = np.vstack([dWx_f, dWx_i, dWx_o, dWx_c])
        dWh = np.vstack([dWh_f, dWh_i, dWh_o, dWh_c])
        db  = np.concatenate([db_f, db_i, db_o, db_c])
        self.dWx, self.dWh, self.db = dWx, dWh, db
        self.dγh, self.dβh = dγh, dβh
        return dx

    def update(self, lr):
        grad_clip = 5.0
        for g in (self.dWx, self.dWh, self.db):
            np.clip(g, -grad_clip, grad_clip, out=g)
        self.Wx -= lr * self.dWx; self.Wh -= lr * self.dWh; self.b -= lr * self.db
        self.γh -= lr * self.dγh; self.βh -= lr * self.dβh

    def save(self):
        return {"Wx": self.Wx.copy(), "Wh": self.Wh.copy(), "b": self.b.copy(),
                "γh": self.γh.copy(), "βh": self.βh.copy()}
    def load(self, s):
        self.Wx=s["Wx"].copy(); self.Wh=s["Wh"].copy(); self.b=s["b"].copy()
        self.γh=s["γh"].copy(); self.βh=s["βh"].copy()


# --- Attention Block ---
class AttentionBlock:
    def __init__(self, dim, attn_dim=32):
        """
        dim: input/output dimension (context vector size = dim)
        attn_dim: dimension for Q, K projections (used for computing attention scores)
        """
        self.dim = dim
        self.attn_d = attn_dim
        sc = np.sqrt(2.0 / dim)
        # Q, K project to attn_dim (for computing attention scores)
        self.Wq = np.random.randn(attn_dim, dim) * sc
        self.Wk = np.random.randn(attn_dim, dim) * sc
        # V projects to dim (context output preserves input dimension)
        self.Wv = np.random.randn(dim, dim) * sc
        self.ba = np.zeros(1)  # Scalar bias for scores
        self._in = None

    def forward(self, x):
        self._in = x
        B, T, D = x.shape  # D = dim
        Q = x @ self.Wq.T                                  # (B, T, attn_dim)
        K = x @ self.Wk.T                                  # (B, T, attn_dim)
        V = x @ self.Wv.T                                  # (B, T, dim)
        scores = (Q * K).sum(-1) / np.sqrt(self.attn_d) + self.ba  # (B, T)
        exp_s  = np.exp(scores - scores.max(axis=1, keepdims=True))
        attn   = exp_s / exp_s.sum(axis=1, keepdims=True)
        ctx    = (attn[:, :, None] * V).sum(axis=1)       # (B, dim)
        self._cache = {"Q": Q, "K": K, "V": V, "attn": attn, "scores": scores}
        return ctx

    def backward(self, dout):
        """
        dout shape: (B, dim) - from dense_mid
        Returns: dx shape: (B, T, dim)
        """
        c = self._cache
        B, T, D = c["V"].shape  # D = dim

        # 1. dL/dV: ctx = sum_t(attn_t * V_t)
        dV = c["attn"][:, :, None] * dout[:, None, :]      # (B, T, dim)

        # 2. dL/d_scores via softmax backward
        # d_attn_scalar[b,t] = sum_d dout[b,d] * V[b,t,d]
        d_attn = (dout[:, None, :] * c["V"]).sum(-1)       # (B, T)
        # Softmax Jacobian
        d_scores = (d_attn * c["attn"]
                    - c["attn"] * (d_attn * c["attn"]).sum(-1, keepdims=True))  # (B, T)

        # 3. Gradients for Wq, Wk, ba
        # Q = x @ Wq.T → dQ[b,t,k] = d_scores[b,t] * K[b,t,k] / sqrt(d)
        # dWq[k,m] = sum_{b,t} x[b,t,m] * dQ[b,t,k]
        dQ_scaled = d_scores[:, :, None] * c["K"] / np.sqrt(self.attn_d)  # (B, T, attn_dim)
        dK_scaled = d_scores[:, :, None] * c["Q"] / np.sqrt(self.attn_d)  # (B, T, attn_dim)
        x = c["Q"] @ np.linalg.inv(self.Wq.T) if False else self._in    # (B, T, dim)
        self.dWq = np.einsum('btm,btk->km', self._in, dQ_scaled)         # (attn_dim, dim)
        self.dWk = np.einsum('btm,btk->km', self._in, dK_scaled)         # (attn_dim, dim)
        self.db = d_scores.sum((0, 1))                                    # (attn_dim,)

        # 4. Gradient for Wv
        # V = x @ Wv.T → dWv[m,n] = sum_{b,t} x[b,t,m] * dV[b,t,n]
        self.dWv = np.einsum('btm,btn->mn', self._in, dV)                # (dim, dim)

        # 5. Input gradient dx
        # dx = dQ_scaled @ Wq.T + dK_scaled @ Wk.T + dV @ Wv.T
        dx = (dQ_scaled @ self.Wq.T + dK_scaled @ self.Wk.T
              + dV @ self.Wv.T)                                          # (B, T, dim)

        return dx

    def update(self, lr):
        for g in (self.dWq, self.dWk, self.dWv):
            np.clip(g, -5, 5, out=g)
        self.Wq -= lr * self.dWq; self.Wk -= lr * self.dWk
        self.Wv -= lr * self.dWv; self.ba -= lr * self.db

    def save(self):
        return {"Wq":self.Wq.copy(),"Wk":self.Wk.copy(),"Wv":self.Wv.copy(),"ba":self.ba.copy()}
    def load(self, s):
        self.Wq=s["Wq"].copy(); self.Wk=s["Wk"].copy()
        self.Wv=s["Wv"].copy(); self.ba=s["ba"].copy()


# --- Dense Block ---
class DenseBlock:
    def __init__(self, inp, outp):
        sc = np.sqrt(2.0 / inp)
        self.W = np.random.randn(outp, inp) * sc
        self.b = np.zeros(outp)
        self._in = None

    def forward(self, x):
        self._in = x
        return x @ self.W.T + self.b

    def backward(self, dout):
        dx = dout @ self.W
        self.dW = dout.T @ self._in
        self.db = dout.sum(0)
        return dx

    def update(self, lr):
        np.clip(self.dW, -5, 5, out=self.dW)
        np.clip(self.db,  -5, 5, out=self.db)
        self.W -= lr * self.dW; self.b -= lr * self.db

    def save(self):
        return {"W": self.W.copy(), "b": self.b.copy()}
    def load(self, s):
        self.W = s["W"].copy(); self.b = s["b"].copy()


# --- Dropout ---
class DropBlock:
    def __init__(self, rate=0.3):
        self.rate = rate
        self._mask = None
    def forward(self, x, training=False):
        if not training or self.rate <= 0:
            return x
        self._mask = (np.random.rand(*x.shape) > self.rate).astype(np.float64)
        return x * self._mask / (1 - self.rate + 1e-12)
    def backward(self, dout):
        if self._mask is None or self.rate <= 0:
            return dout
        return dout * self._mask / (1 - self.rate + 1e-12)


# ============================================================================
# 主模型
# ============================================================================

class CNNLSTMAttention:
    def __init__(self, n_features=N_FEATURES, seq_len=SEQ_LEN):
        self.seq_len = seq_len
        self.n_features = n_features
        # CNN输出 (B, CNN_FILTERS, T')
        cnn_flat    = CNN_FILTERS * (SEQ_LEN - CNN_KERNEL + 1)  # = 16 * 58 = 928
        lstm_out_len = SEQ_LEN - CNN_KERNEL + 1                 # = 58

        self.cnn       = CNNBlock(CNN_FILTERS, CNN_KERNEL, n_features)
        self.dense_in  = DenseBlock(cnn_flat,    lstm_out_len * LSTM_HID)  # 输出 T' * HID
        self.lstm      = LSTMBlock(LSTM_HID,     LSTM_HID)
        self.attention = AttentionBlock(LSTM_HID, ATTENTION_HID)
        self.dense_mid = DenseBlock(LSTM_HID,    DENSE_HID)  # Fix: attention outputs dim=LSTM_HID
        self.dropout   = DropBlock(DROPOUT_RATE)
        self.dense_out = DenseBlock(DENSE_HID,   OUTPUT_DIM := 1)
        self.output_dim = OUTPUT_DIM

        self.train_losses = []
        self.val_losses   = []
        self.best_val     = float("inf")
        self.best_epoch   = 0

    # -- forward --
    def forward(self, X, training=False):
        # CNN
        h = self.cnn.forward(X)                              # (B, F, T')
        B = X.shape[0]
        h = h.reshape(B, -1)                                 # flatten
        h = self.dense_in.forward(h)                         # (B, T'*HID)
        T_pr = (SEQ_LEN - CNN_KERNEL + 1)                    # = 58
        h = h.reshape(B, T_pr, LSTM_HID)                    # (B, T', LSTM_HID)
        self._attn_in_shape = h.shape                        # Save for backward
        log.info(f"  Attention输入shape: {h.shape}")
        h = self.lstm.forward(h)                             # (B, T_pr, HID)
        self._lstm_out_len = h.shape[1]                      # Record for backward
        h = self.attention.forward(h)                        # (B, dim)
        h = self.dense_mid.forward(h)                        # (B, DENSE_HID)
        h = _relu(h)
        h = self.dropout.forward(h, training=training)
        out = self.dense_out.forward(h)                      # (B, 1)
        self._last_out = out
        self._last_h   = h
        self._last_batch = B
        return out

    # -- backward --
    def backward(self):
        # 全局梯度裁剪防止爆炸
        dout = np.ones((self._last_batch, self.output_dim))
        dout = self.dense_out.backward(dout)
        dout = _relu_g(self._last_h) * dout
        dout = self.dropout.backward(dout)
        dout = self.dense_mid.backward(dout)               # (B, dim)
        dout = self.attention.backward(dout)               # (B, T_pr, dim)
        B, T_pr, HID = self._attn_in_shape
        dout = self.lstm.backward(dout)
        dout = self.dense_in.backward(dout.reshape(B, -1)).reshape(B, CNN_FILTERS, T_pr)
        self.cnn.backward(dout)

    def update(self, lr):
        # 全局梯度裁剪
        for g in (self.cnn.dW, self.dense_in.dW, self.lstm.dWx,
                  self.lstm.dWh, self.attention.dWq, self.dense_mid.dW,
                  self.dense_out.dW):
            np.clip(g, -5.0, 5.0, out=g)
        self.cnn.update(lr); self.dense_in.update(lr); self.lstm.update(lr)
        self.attention.update(lr); self.dense_mid.update(lr); self.dense_out.update(lr)

    def loss(self, pred, target):
        return np.mean((pred.ravel() - target) ** 2)

    def save(self, path):
        state = {
            "cnn": self.cnn.save(), "dense_in": self.dense_in.save(),
            "lstm": self.lstm.save(), "attention": self.attention.save(),
            "dense_mid": self.dense_mid.save(), "dense_out": self.dense_out.save(),
            "train_losses": self.train_losses, "val_losses": self.val_losses,
            "best_epoch": self.best_epoch,
            "hyper": dict(seq_len=self.seq_len, n_features=self.n_features,
                          cnn_filters=CNN_FILTERS, cnn_kernel=CNN_KERNEL,
                          lstm_hid=LSTM_HID, dense_hid=DENSE_HID,
                          attention_hid=ATTENTION_HID, dropout=DROPOUT_RATE),
        }
        with open(path, "wb") as f:
            pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)
        log.info(f"模型已保存: {path}")

    def load(self, path):
        with open(path, "rb") as f:
            st = pickle.load(f)
        self.cnn.load(st["cnn"]); self.dense_in.load(st["dense_in"])
        self.lstm.load(st["lstm"]); self.attention.load(st["attention"])
        self.dense_mid.load(st["dense_mid"]); self.dense_out.load(st["dense_out"])
        self.train_losses = st.get("train_losses", [])
        self.val_losses   = st.get("val_losses",   [])
        self.best_epoch   = st.get("best_epoch",   0)
        log.info(f"模型已加载: {path}")


# ============================================================================
# 标准化器
# ============================================================================

class FeatureScaler:
    """特征标准化器"""
    def __init__(self):
        self._mean = None
        self._std = None
        self._count = 0
        self._sum = None
        self._sum_sq = None

    def partial_fit(self, X_chunk):
        """增量更新均值和方差（Welford算法）"""
        flat = X_chunk.reshape(-1, X_chunk.shape[-1])
        n = flat.shape[0]
        if self._count == 0:
            self._sum = flat.sum(axis=0)
            self._sum_sq = (flat ** 2).sum(axis=0)
            self._count = n
        else:
            self._sum += flat.sum(axis=0)
            self._sum_sq += (flat ** 2).sum(axis=0)
            self._count += n
        return self

    def fit(self, X):
        """一次性fit（兼容旧接口）"""
        flat = X.reshape(-1, X.shape[-1])
        self._sum = flat.sum(axis=0)
        self._sum_sq = (flat ** 2).sum(axis=0)
        self._count = flat.shape[0]
        m = self._sum / self._count
        var = self._sum_sq / self._count - m ** 2
        self._mean = m.astype(np.float32)
        self._std = np.sqrt(np.maximum(var, 1e-8)).astype(np.float32)
        return self

    def fit_transform(self, X):
        """fit + transform convenience"""
        self.fit(X)
        return self.transform(X)

    def transform(self, X):
        if self._mean is None:
            raise RuntimeError("必须先调用partial_fit或fit")
        return (X - self._mean) / self._std

    def fit_transform(self, X):
        """fit then transform in one call"""
        self.fit(X)
        return self.transform(X)

    def fit_transform_stream(self, seq_iter, batch_size=100000):
        """流式fit+transform，处理大规模数据"""
        # First pass: compute stats
        for chunk in seq_iter:
            self.partial_fit(chunk)
        log.info(f"Scaler拟合完成: count={self._count}, mean={self.mean.round(4)}, std={self.std.round(4)}")
        # Reset and second pass: transform
        self._count = 0
        self._sum = None
        self._sum_sq = None

    def save(self, p):
        with open(p, "wb") as f:
            pickle.dump({"mean": self._mean, "std": self._std}, f)

    def load(self, p):
        with open(p, "rb") as f:
            st = pickle.load(f)
        self._mean = st["mean"]
        self._std = st["std"]
        self._count = 1


# ============================================================================
# 训练器
# ============================================================================

class Trainer:
    def __init__(self, model, lr=LR_INIT, batch_size=BATCH_SIZE, patience=PATIENCE):
        self.model = model; self.lr = lr; self.batch_size = batch_size; self.patience = patience

    def _batches(self, X, y, shuffle=True):
        n = X.shape[0]; idx = np.random.permutation(n) if shuffle else np.arange(n)
        for s in range(0, n, self.batch_size):
            e = min(s + self.batch_size, n)
            yield X[idx[s:e]], y[idx[s:e]]

    def train_epoch(self, X, y):
        total, cnt = 0.0, 0
        for xb, yb in self._batches(X, y):
            pred = self.model.forward(xb, training=True)
            total += self.model.loss(pred, yb) * len(yb)
            self.model.backward()
            self.model.update(self.lr * (0.95 ** cnt))
            cnt += 1
        return total / len(X)

    def validate(self, X, y):
        pred = self.model.forward(X, training=False)
        return self.model.loss(pred, y)

    def fit(self, Xt, yt, Xv, yv, max_ep=MAX_EPOCHS):
        log.info(f"训练: {len(Xt)} train / {len(Xv)} val | lr={self.lr} batch={self.batch_size}")
        best_loss, no_imp, epoch_log = float("inf"), 0, []
        for ep in range(1, max_ep + 1):
            tl = self.train_epoch(Xt, yt)
            vl = self.validate(Xv, yv)
            self.model.train_losses.append(tl)
            self.model.val_losses.append(vl)
            if ep % 5 == 0 or ep == 1:
                log.info(f"  Epoch {ep:3d}: train={tl:.6f} val={vl:.6f}")
            epoch_log.append(dict(epoch=ep, train_loss=tl, val_loss=vl))
            if vl < best_loss - EARLY_STOP_TOL:
                best_loss = vl; no_imp = 0
                self.model.best_val = best_loss
                self.model.best_epoch = ep
                self.model.save(MODEL_PATH)
            else:
                no_imp += 1
                if no_imp >= self.patience:
                    log.info(f"早停 epoch={ep}, best_epoch={self.model.best_epoch}, best_val={best_loss:.6f}")
                    break
        return epoch_log


# ============================================================================
# IC / IR 评估
# ============================================================================

def rank_ic(x, y):
    """Spearman rank correlation"""
    xr = np.argsort(np.argsort(x)) + 1
    yr = np.argsort(np.argsort(y)) + 1
    xm, ym = xr.mean(), yr.mean()
    cov  = np.mean((xr - xm) * (yr - ym))
    sx, sy = xr.std(), yr.std()
    return cov / (sx * sy + 1e-12)

def compute_ic_ir(predictions, targets, window=ROLLING_WIN):
    """滚动窗口计算IC均值和IR"""
    n = len(predictions)
    ic_vals = []
    for i in range(window, n):
        ic = rank_ic(predictions[i-window:i], targets[i-window:i])
        ic_vals.append(ic)
    if not ic_vals:
        return 0.0, 0.0, []
    arr = np.array(ic_vals)
    return float(arr.mean()), float(arr.std()), ic_vals

def check_monotonicity(predictions, targets, n_groups=5):
    """分组收益单调性检验"""
    order = np.argsort(predictions)
    grp_sz = len(order) // n_groups
    group_means = []
    for g in range(n_groups):
        s, e = g * grp_sz, (g+1) * grp_sz if g < n_groups-1 else len(order)
        grp_ret = targets[order[s:e]]
        group_means.append(grp_ret.mean())
    inc  = all(group_means[i] <= group_means[i+1] for i in range(n_groups-1))
    dec  = all(group_means[i] >= group_means[i+1] for i in range(n_groups-1))
    if inc or dec:
        return True
    same_dir = sum(1 for i in range(n_groups-1)
                   if (group_means[i] < group_means[i+1]) == (group_means[0] < group_means[-1]))
    return same_dir / (n_groups - 1) >= 0.7

def rolling_positive_windows(predictions, targets, win=ROLLING_WIN, step=30):
    """≥3个独立滚动窗口IC>0"""
    pos = total = 0
    for i in range(0, len(predictions) - win, step):
        total += 1
        if rank_ic(predictions[i:i+win], targets[i:i+win]) > 0:
            pos += 1
    return pos, total


# ============================================================================
# 主流程
# ============================================================================

def main():
    t0 = time.time()
    log.info("=" * 60)
    log.info("CNN-LSTM-Attention 模型训练")
    log.info(f"任务: DL-2026-09-24  |  DL权重: 20%  |  标签: OC1d")
    log.info(f"门禁: IC>{IC_THRESHOLD}  IR>{IR_THRESHOLD}  滚动窗口≥{MIN_ROLLING_POS}正贡献")
    log.info("=" * 60)

    # 1. 加载数据（直接限制数量，避免扫全库）
    MAX_STOCKS = int(os.environ.get('MAX_STOCKS', '10'))
    all_data = load_all_stocks(max_stocks=MAX_STOCKS)
    if not all_data:
        log.error("❌ 无可用数据，退出")
        return None
    log.info(f"实际加载 {len(all_data)} 只股票")
    X_all, y_all, codes_all, _ = build_sequences(all_data, max_stocks=MAX_STOCKS)
    if len(X_all) == 0:
        log.error("❌ 无有效序列，退出")
        return None
    log.info(f"序列: {len(X_all)} samples, shape={X_all.shape}")

    # 3. 时间顺序划分（前75%训练/15%验证/10%测试）
    n = len(X_all)
    n_tr = int(n * TRAIN_RATIO)
    n_va = int(n * VAL_RATIO)
    # 按时间顺序，不打乱，确保前瞻偏差
    Xt, y_tr = X_all[:n_tr], y_all[:n_tr]
    Xv, y_v  = X_all[n_tr:n_tr+n_va], y_all[n_tr:n_tr+n_va]
    Xte, y_te = X_all[n_tr+n_va:], y_all[n_tr+n_va:]
    log.info(f"划分: train={len(Xt)} val={len(Xv)} test={len(Xte)}")

    # 4. 标准化
    scaler = FeatureScaler()
    Xt = scaler.fit_transform(Xt)
    Xv = scaler.transform(Xv)
    Xte = scaler.transform(Xte)
    scaler.save(SCALER_PATH)

    # 5. 初始化模型
    np.random.seed(42)
    model = CNNLSTMAttention(n_features=N_FEATURES, seq_len=SEQ_LEN)

    # 6. 训练
    trainer = Trainer(model, lr=LR_INIT, batch_size=BATCH_SIZE, patience=PATIENCE)
    epoch_log = trainer.fit(Xt, y_tr, Xv, y_v)

    # 7. 测试集评估
    log.info("\n" + "-" * 40)
    log.info("测试集评估")
    log.info("-" * 40)
    preds_te = model.forward(Xte, training=False).ravel()
    ic_mean, ic_std, ic_series = compute_ic_ir(preds_te, y_te, window=ROLLING_WIN)
    icir = ic_mean / (ic_std + 1e-12)
    mono = check_monotonicity(preds_te, y_te)
    pos_wins, tot_wins = rolling_positive_windows(preds_te, y_te)

    ic_pass   = abs(ic_mean)  > IC_THRESHOLD
    ir_pass   = abs(icir)     > IR_THRESHOLD
    mono_pass = mono
    roll_pass = pos_wins >= MIN_ROLLING_POS

    log.info(f"  IC_mean = {ic_mean:.4f}  {'✅' if ic_pass else '❌'}  (阈值>{IC_THRESHOLD})")
    log.info(f"  ICIR    = {icir:.4f}  {'✅' if ir_pass else '❌'}  (阈值>{IR_THRESHOLD})")
    log.info(f"  单调性  = {'✅' if mono_pass else '❌'}")
    log.info(f"  滚动正IC= {pos_wins}/{tot_wins}  {'✅' if roll_pass else '❌'}  (要求≥{MIN_ROLLING_POS})")

    gate_pass = ic_pass and ir_pass and mono_pass and roll_pass

    # 8. 保存
    metrics = {
        "model": "CNN-LSTM-Attention",
        "features": FEATURES,
        "seq_len": SEQ_LEN,
        "n_stocks": len(all_data),
        "n_samples": len(X_all),
        "train_samples": len(Xt),
        "val_samples": len(Xv),
        "test_samples": len(Xte),
        "best_epoch": model.best_epoch,
        "best_val_loss": model.best_val,
        "final_train_loss": model.train_losses[-1] if model.train_losses else None,
        "final_val_loss": model.val_losses[-1] if model.val_losses else None,
        "ic_mean": round(ic_mean, 6),
        "ic_std":  round(ic_std,  6),
        "icir":    round(icir,   4),
        "monotonicity": mono_pass,
        "rolling_pos_windows": pos_wins,
        "rolling_total_windows": tot_wins,
        "gate_pass": gate_pass,
        "epoch_log": epoch_log,
        "timestamp": datetime.now().isoformat(),
    }
    with open(METRICS_PATH, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2, default=str)

    if gate_pass:
        log.info("\n🎉 门禁通过！模型已就绪，可进行132日全量回测")
    else:
        log.info("\n⚠️ 门禁未通过，降级为统计fallback（不阻塞主流程）")

    elapsed = time.time() - t0
    log.info(f"\n训练总耗时: {elapsed/60:.1f} 分钟")

    # JSON摘要输出（供后续脚本解析）
    print(json.dumps({
        "gate_pass": gate_pass,
        "ic_mean":   round(ic_mean,  6),
        "icir":      round(icir,    4),
        "best_epoch": model.best_epoch,
        "n_samples": len(X_all),
        "timestamp": metrics["timestamp"],
    }, indent=2, ensure_ascii=False))

    return metrics


if __name__ == "__main__":
    main()
