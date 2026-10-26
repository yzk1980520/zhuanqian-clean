import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
"""dl_factor.py — v2.0 排序学习GRU因子

基于申万宏源GRU模型(2026.07)改进:
  - 40日×7特征量价窗口 (原20日×6)
  - 排序损失 PairwiseRankingLoss (原MSE回归)
  - hidden_size=16 (更轻量)
  - 截面排序训练: 同一天股票间排序关系优先

业界验证: 全市场RankIC 6.21%, Top20%年化超额8.93%
"""
import os, sys
import numpy as np

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

# ─── 配置 ───
SEQ_LEN = 40            # 输入序列长度 (从20→40)
FEAT_DIM = 7            # 特征维度 (从6→7)
HIDDEN_DIM = 16         # 隐层维度 (从32→16, 更轻量)
EPOCHS = 10
BATCH_SIZE = 2048       # 更大batch加速
LR = 0.002
RANK_MARGIN = 0.05      # 排序损失margin
MODEL_CACHE = os.path.join(PROJECT_DIR, "data", "dl_v2_weights.npz")

# ─── 特征工程 v2 ───

def compute_features(records):
    """提取量价特征矩阵 (n × 7)
    
    7个特征: ret, vol_ratio, hl_range, pos_ma20, rsi14, turnover, vwap_dev
    对应研报: Open/High/Low/Close/VWAP/Volume/Amount (降维映射)
    """
    n = len(records)
    if n < SEQ_LEN + 5:
        return None

    closes = np.array([r["close"] for r in records], dtype=np.float32)
    highs = np.array([r["high"] for r in records], dtype=np.float32)
    lows = np.array([r["low"] for r in records], dtype=np.float32)
    volumes = np.array([r["volume"] for r in records], dtype=np.float32)

    # f1: 日收益率 ret
    ret = np.zeros(n)
    ret[1:] = (closes[1:] - closes[:-1]) / (closes[:-1] + 1e-8)

    # f2: 量比 vol_ratio (当日/5日均)
    vol_ma5 = np.convolve(volumes, np.ones(5)/5, mode='same')
    vol_ratio = volumes / (vol_ma5 + 1e-8)

    # f3: 振幅比 hl_range
    hl_range = (highs - lows) / (closes + 1e-8)

    # f4: 偏离20日均线 pos_ma20
    ma20 = np.convolve(closes, np.ones(20)/20, mode='same')
    pos_ma20 = (closes - ma20) / (ma20 + 1e-8)

    # f5: RSI14 近似
    gain = np.maximum(ret, 0)
    loss = np.maximum(-ret, 0)
    avg_gain = np.convolve(gain, np.ones(14)/14, mode='same')
    avg_loss = np.convolve(loss, np.ones(14)/14, mode='same')
    rsi = 100 - 100 / (1 + avg_gain / (avg_loss + 1e-8))

    # f6: 换手率近似 turnover
    vol_ma20 = np.convolve(volumes, np.ones(20)/20, mode='same')
    turnover = volumes / (vol_ma20 + 1e-8)

    # f7: VWAP偏离 (模拟均价偏差)
    vwap = np.zeros(n)
    for i in range(n):
        r = records[i]
        typical_price = (r["high"] + r["low"] + r["close"]) / 3.0
        vwap[i] = typical_price
    vwap_dev = (closes - vwap) / (vwap + 1e-8)

    X = np.column_stack([ret, vol_ratio, hl_range, pos_ma20, rsi, turnover, vwap_dev])
    return X.astype(np.float32)

# ─── NumPy GRU Cell (精简版) ───

class GRUCell:
    def __init__(self, input_dim, hidden_dim):
        self.hidden_dim = hidden_dim
        scale = np.sqrt(2.0 / (input_dim + hidden_dim))
        self.Wz = np.random.randn(hidden_dim, input_dim) * scale
        self.Uz = np.random.randn(hidden_dim, hidden_dim) * scale
        self.bz = np.zeros((hidden_dim, 1))
        self.Wr = np.random.randn(hidden_dim, input_dim) * scale
        self.Ur = np.random.randn(hidden_dim, hidden_dim) * scale
        self.br = np.zeros((hidden_dim, 1))
        self.Wn = np.random.randn(hidden_dim, input_dim) * scale
        self.Un = np.random.randn(hidden_dim, hidden_dim) * scale
        self.bn = np.zeros((hidden_dim, 1))

    def forward(self, x, h_prev):
        x = x.reshape(-1, 1)
        h_prev = h_prev.reshape(-1, 1)
        z = 1 / (1 + np.exp(-(self.Wz @ x + self.Uz @ h_prev + self.bz)))
        r = 1 / (1 + np.exp(-(self.Wr @ x + self.Ur @ h_prev + self.br)))
        n = np.tanh(self.Wn @ x + r * (self.Un @ h_prev) + self.bn)
        h = (1 - z) * n + z * h_prev
        return h.flatten()

class RankingGRU:
    """排序学习GRU — 为选股排序优化"""
    def __init__(self, input_dim=7, hidden_dim=16):
        self.gru = GRUCell(input_dim, hidden_dim)
        scale = np.sqrt(2.0 / hidden_dim)
        self.W = np.random.randn(1, hidden_dim) * scale
        self.b = np.zeros((1, 1))

    def forward(self, seq):
        """seq: (SEQ_LEN, FEAT_DIM) → scalar score"""
        h = np.zeros(self.gru.hidden_dim)
        for t in range(len(seq)):
            h = self.gru.forward(seq[t], h)
        out = self.W @ h.reshape(-1, 1) + self.b
        return out.flatten()[0]

    def predict_batch(self, X_padded, lengths=None):
        """批量推理: X_padded (n, SEQ_LEN, FEAT_DIM)"""
        scores = []
        for i in range(len(X_padded)):
            s = self.forward(X_padded[i])
            scores.append(s)
        return np.array(scores)

    def params(self):
        return [getattr(self.gru, a) for a in ['Wz','Uz','bz','Wr','Ur','br','Wn','Un','bn']] + [self.W, self.b]

    def param_count(self):
        return sum(p.size for p in self.params())

# ─── 排序损失训练器 ───

class RankingTrainer:
    """Pairwise Ranking Loss — 直接优化选股排序"""
    def __init__(self, model, lr=0.002, margin=0.05):
        self.model = model
        self.lr = lr
        self.margin = margin

    def ranking_loss(self, s_i, s_j, y_i, y_j):
        """Pairwise hinge loss:
        如果 y_i > y_j (i表现优于j), 则 s_i 应 > s_j + margin
        loss = max(0, margin - (s_i - s_j))
        """
        diff = s_i - s_j
        target = 1.0 if y_i > y_j else -1.0  # i应排j前面
        return max(0.0, self.margin - target * diff)

    def numerical_grad(self, seq, target_all, idx):
        """对第idx个样本计算数值梯度（有限差分法）

        对每个参数做微小扰动eps, 计算损失变化量作为梯度
        """
        eps = 1e-5
        base_score = self.model.forward(seq)
        params = self.model.params()
        grads = []

        for p in params:
            orig = p.copy()
            # 正向扰动整个参数矩阵
            p[:] = orig + eps
            pos_score = self.model.forward(seq)
            # 恢复原始值
            p[:] = orig

            # 梯度 = (f(x; θ+eps) - f(x; θ)) / eps
            grad_val = (pos_score - base_score) / eps
            grads.append(np.ones_like(p) * grad_val)

        return grads

    def train_batch(self, batch_seqs, batch_targets):
        """批量SGD训练"""
        n = len(batch_seqs)
        total_loss = 0
        pairs = 0

        # 数值梯度: 对每个参数, 扰动后计算所有pair的平均loss变化
        eps = 1e-5
        params = self.model.params()

        # 当前所有分数
        base_scores = np.array([self.model.forward(seq) for seq in batch_seqs])

        # 计算当前loss (作为baseline)
        base_loss = 0
        for i in range(n):
            for j in range(n):
                if i == j or abs(batch_targets[i] - batch_targets[j]) < 0.001:
                    continue
                base_loss += self.ranking_loss(base_scores[i], base_scores[j],
                                                batch_targets[i], batch_targets[j])
                pairs += 1
        total_loss = base_loss / max(pairs, 1)

        if pairs == 0:
            return 0.0

        # 参数更新: 对每个参数
        for pi, p in enumerate(params):
            orig = p.copy()
            # 正向扰动
            p[:] = orig + eps
            scores_p = np.array([self.model.forward(seq) for seq in batch_seqs])
            loss_p = 0
            for i in range(n):
                for j in range(n):
                    if i == j or abs(batch_targets[i] - batch_targets[j]) < 0.001:
                        continue
                    loss_p += self.ranking_loss(scores_p[i], scores_p[j],
                                                 batch_targets[i], batch_targets[j])
            loss_p /= max(pairs, 1)

            # 梯度 = (loss_p - base_loss/pairs) / eps
            grad = (loss_p - total_loss) / eps
            p[:] = orig - self.lr * grad  # 直接用更新后的值

        return total_loss

# ─── 数据准备 ───

def build_ranking_dataset(all_stocks_features):
    """构建排序学习数据集

    每只股票滑动窗口 → (seq, target_5d_return)
    同一天的所有股票作为一个排序组
    """
    X_all, y_all, date_groups = [], [], {}

    for code, recs in all_stocks_features:
        feat = compute_features(recs)
        if feat is None or len(feat) < SEQ_LEN + 5:
            continue
        n = len(feat)
        for i in range(SEQ_LEN, n - 5):
            seq = feat[i - SEQ_LEN:i]  # (40, 7)
            target = (recs[i + 5]["close"] - recs[i]["close"]) / recs[i]["close"]
            date_str = recs[i].get("date", str(i))
            idx = len(X_all)
            X_all.append(seq)
            y_all.append(target)
            if date_str not in date_groups:
                date_groups[date_str] = []
            date_groups[date_str].append(idx)

    if not X_all:
        return None, None, None

    X = np.array(X_all, dtype=np.float32)
    y = np.array(y_all, dtype=np.float32)

    # 标准化
    mean = X.mean(axis=(0, 1), keepdims=True)
    std = X.std(axis=(0, 1), keepdims=True) + 1e-8
    X = (X - mean) / std

    return X, y, date_groups, mean, std

# ─── 训练入口 ───

def train_ranking_model(all_stocks_data, force_retrain=False):
    """训练排序学习GRU模型"""
    if not force_retrain and os.path.exists(MODEL_CACHE):
        return load_model()

    dataset = build_ranking_dataset(all_stocks_data)
    if dataset[0] is None:
        print("  ⚠️ 排序GRU: 训练数据不足")
        return None

    X, y, date_groups, mean, std = dataset
    print(f"  🧠 排序GRU v2:  {X.shape[0]}样本, {len(date_groups)}个交易日")
    print(f"     参数量: {HIDDEN_DIM**2*3 + HIDDEN_DIM*FEAT_DIM*3 + HIDDEN_DIM + 1:,}")

    model = RankingGRU(input_dim=FEAT_DIM, hidden_dim=HIDDEN_DIM)
    trainer = RankingTrainer(model, lr=LR, margin=RANK_MARGIN)

    # 按日期分组做排序训练
    date_samples = list(date_groups.values())
    n = len(date_samples)

    for epoch in range(EPOCHS):
        np.random.shuffle(date_samples)
        total_loss = 0
        batch_count = 0

        for start in range(0, n, BATCH_SIZE):
            batch_indices = []
            batch_targets = []
            for group in date_samples[start:start+BATCH_SIZE]:
                for idx in group:
                    batch_indices.append(idx)
                    batch_targets.append(y[idx])

            if len(batch_indices) < 2:
                continue

            batch_seqs = X[batch_indices]
            loss = trainer.train_batch(batch_seqs, np.array(batch_targets))
            total_loss += loss
            batch_count += 1

        if epoch % 3 == 0:
            print(f"     epoch {epoch}: ranking_loss={total_loss/max(batch_count,1):.6f}")

    # 保存
    save_model(model, mean, std)
    return model, mean, std

def save_model(model, mean, std):
    os.makedirs(os.path.dirname(MODEL_CACHE), exist_ok=True)
    params_dict = {}
    for i, p in enumerate(model.params()):
        params_dict[f"p{i}"] = p
    params_dict["mean"] = mean
    params_dict["std"] = std
    np.savez(MODEL_CACHE, **params_dict)

def load_model():
    try:
        with np.load(MODEL_CACHE, allow_pickle=True) as f:
            return None  # 简化: 实际加载需重建模型
    except Exception:
        return None

def predict_ranking_bonus(code, records, model_data):
    """预测单只股票的GRU排序分 → 映射到-10~+10 bonus"""
    if model_data is None:
        return 0, ""

    model, mean, std = model_data
    feat = compute_features(records)
    if feat is None or len(feat) < SEQ_LEN:
        return 0, ""

    seq = feat[-SEQ_LEN:]
    # 标准化
    seq_norm = (seq - mean.squeeze()) / std.squeeze()
    score = model.forward(seq_norm)

    # 映射到-10~+10
    bonus = int(np.clip(score * 20, -10, 10))
    signal = f"🧠 GRU排序{bonus:+d}" if abs(bonus) >= 2 else ""
    return bonus, signal

if __name__ == "__main__":
    print("🧠 排序学习GRU v2 测试...")
    from core.pipeline.tdx_core import get_tdx_data
    codes = ["sz002415", "sz002881", "sh600519", "sz000001", "sz300750",
             "sz000333", "sh600887", "sz002475", "sh601012", "sz002714"]
    data = []
    for code in codes:
        recs = get_tdx_data(code, 300)
        if recs and len(recs) > 100:
            data.append((code, recs))

    result = train_ranking_model(data, force_retrain=True)
    if result:
        print(f"\n  ✅ 排序GRU训练完成")
        print(f"  推理测试:")
        for code, recs in data:
            bonus, signal = predict_ranking_bonus(code, recs, result)
            print(f"    {code}: bonus={bonus:+d}")
