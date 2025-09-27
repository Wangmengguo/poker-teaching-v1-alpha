# Suggest v0 · Executable SPEC (Aligned with GTO Plan)

> 目标：本地运行、P95 ≤ 1s 响应、对新人有优势、可解释；与 GTO 基线方案（Baseline Engine + 混合策略 + Exploit 提示）**完全对齐**。

---

## 1. 做什么 / 不做什么 / 边界

### 1.1 Must‑Have（v0 范围）
- **流水线**：抽象（分桶+下注树）→ 截断估值 → **离线 LP 求解** → 导出策略表 → **在线查表**。
- **街次**：Preflop / Flop / Turn（River 由 Turn 叶子 EV 推导动作）。
- **分桶（Bucketing）**：
  - Preflop=6 桶；Flop=8 桶；Turn=8 桶；特征=当前强度 + 提升潜力（outs/改良率）。
  - 产物：`/configs/buckets/{preflop,flop,turn}.json`。
- **桶转移**：`flop→turn`、`turn→river` 两张转移矩阵（Monte Carlo 采样）。
  - 产物：`/artifacts/transitions/{flop_to_turn,turn_to_river}.json`。
- **下注树（Action Abstraction）**：HU 100bb，动作集合 `{fold, check/call, bet/raise∈[0.5P,1.0P]}`，**每街最多 2 次加注（2‑cap）**。
  - 产物：`/configs/trees/hu_discrete_2cap.yaml`。
- **截断与叶子 EV**：Turn 截断；叶子 = 使用 `turn→river` 转移 + 摊牌胜率的期望（可采样、可缓存）。
  - 可选缓存：`/artifacts/ev_cache/turn_leaf.npz`。
- **LP 求解（Sequence‑form / 等价 LP）**：离线一次，输出混合策略表。
  - 产物：`/artifacts/policies/{preflop,postflop}.jsonl|.npz`。
- **运行时 API**：`suggest(state) -> {action, size_tag, rationale[], meta}`，P95 ≤ 1s（CPU）。
- **教学解释**：返回 `bucket_id`、桶语义标签、`rationale`（如 `SEMI_BLUFF_BUCKET`、`RAISE_CAP_REACHED`、`PRICE_OK`）、`future_equity_hint`。

### 1.2 Out of Scope（v0 不做）
- 多人桌（>2 人）、多位置；复杂下注网格（如 1/3P, 2/3P 等全谱）；
- 在线实时求解（LP/CFR）；对手建模与自适应剥削；
- 显式 River 展开；分布式/移动端部署；严格最优证明。

### 1.3 边界与假设
- 规则：HU NL，100bb，有效栈与训练一致；
- 评估：确定性评估器（PokerKit/等价），固定随机种子；
- 策略表 ≤ 50MB；在线内存 ≤ 1GB；
- 性能预算：桶映射+查表 ≤ 10ms，其余预算给序列化/日志，整链路 ≤ 1000ms。

---

## 2. 与 GTO Plan 的对齐

### 2.1 架构插槽
- **Baseline Engine**：不依赖在线解算，纯“配置/表”驱动 —— 本 v0 的 LP 产物即作为 **Baseline 策略源**。
- **混合策略落地**：导出为 `mix:[{action,size_tag,weight}]`；运行时使用 **稳定随机**（以 hand_id 为 seed）作确定性混合。
- **输出契约**：对齐 `suggest` payload，`meta.baseline="GTO"`、`meta.frequency`、`meta.variant=node_key`、`debug.mix` 等。
- **Exploit 提示层**：仅做提示，不改变 baseline 动作（包裹层）。

### 2.2 尺寸与封顶映射
- **尺寸映射表（v0）**：`0.5P → half`，`1.0P → pot`；允许等效区间（如 0.45P–0.55P 归 half）。
- **加注封顶**：训练树用 **2‑cap** 控制规模；上线规则层若存在 3rd/4th‑raise 节点，先标注 `approx`（从 2‑cap 频率镜像/插值外推），后续版本再以大树替换。

### 2.3 四街覆盖与派生标记
- River 节点照常提供动作，但标记 `derived_from_turn_leaf=true`，便于 UI/日志透明化；未来可替换为显式 River 解。

### 2.4 锅型覆盖的里程碑
- **M1**：单提标准锅（最常见线）；
- **M2**：limp pot（规则+小 LP 子树）；
- **M3**：3bet/4bet 关键节点（局部细化树）。

---

## 3. 数据结构与文件约定

```
repo/
├─ configs/
│  ├─ trees/hu_discrete_2cap.yaml
│  └─ buckets/{preflop,flop,turn}.json
├─ artifacts/
│  ├─ transitions/{flop_to_turn,turn_to_river}.json
│  ├─ policies/{preflop,postflop}.jsonl|.npz
│  └─ ev_cache/turn_leaf.npz (optional)
├─ lib/
│  ├─ feature_eval.py        # 强度/潜力特征、桶映射
│  ├─ lp_solver.py           # 抽象博弈 → LP → 策略表
│  └─ suggest_runtime.py     # suggest(state) 实现
├─ reports/
│  └─ eval_v0.md
└─ tests/
```

### 3.1 node_key（与 GTO Plan 对齐）
- 组成：`street/pot_type/role/{ip|oop}/texture/spr/hand_class`。
- `hand_class` 由 `bucket_id` 与若干离散特征派生（如 `semi_bluff` 标志）。

### 3.2 策略表记录（JSONL 示例）
```json
{
  "node_key": "flop/std/ip/ttx:dry/spr:7/b:5",
  "mix": [
    {"action": "bet",  "size_tag": "half", "weight": 0.62},
    {"action": "check",                     "weight": 0.38}
  ],
  "meta": {
    "derived_from_turn_leaf": false,
    "cap": 2,
    "bucket": 5,
    "explain": ["SEMI_BLUFF_BUCKET", "PRICE_OK"]
  }
}
```

---

## 4. 运行时 API 与解释字段

### 4.1 `suggest(state)` 输入（精简）
- `street, hero_pos, pot, eff_stack, board, hole_cards, action_history`。

### 4.2 输出
```ts
{
  action: "bet|raise|call|check|fold",
  size_tag: "half|pot",
  rationale: ["BUCKET:5(强度中上/潜力一般)", "SEMI_BLUFF_BUCKET", "RAISE_CAP_REACHED"],
  meta: {
    baseline: "GTO",
    frequency: 0.62,            // 选中臂的混合权重
    variant: "<node_key>",
    debug: { bucket: 5, mix: [{bet,half,0.62},{check,0.38}] }
  }
}
```

---

## 5. 离线产出流程（可直接执行）

1) **分桶与转移**  
```bash
python -m tools.build_buckets --streets preflop,flop,turn --bins 6,8,8 \
  --features strength,potential --out configs/buckets
python -m tools.estimate_transitions --from flop --to turn --samples 200000 \
  --out artifacts/transitions/flop_to_turn.json
python -m tools.estimate_transitions --from turn --to river --samples 200000 \
  --out artifacts/transitions/turn_to_river.json
```

2) **构建抽象树与叶子 EV**  
```bash
python -m tools.build_tree --config configs/trees/hu_discrete_2cap.yaml \
  --out artifacts/tree_flat.json
python -m tools.cache_turn_leaf_ev --trans artifacts/transitions/turn_to_river.json \
  --out artifacts/ev_cache/turn_leaf.npz
```

3) **LP 求解并导出策略表**  
```bash
python -m tools.solve_lp --tree artifacts/tree_flat.json \
  --buckets configs/buckets --transitions artifacts/transitions \
  --leaf_ev artifacts/ev_cache/turn_leaf.npz \
  --solver highs --out artifacts/policies
```

4) **评测与回归**  
```bash
python -m tools.eval_baselines --policy artifacts/policies \
  --opponents always_call,always_raise,rule_based --hands 200000 \
  --report reports/eval_v0.md
```

---

## 6. 成功标准（验收）
- **性能**：本地 CPU，1000 次随机查询，`P95 ≤ 1s/次`；内存 ≤ 1GB；
- **对战**：对 `Always-Call / Always-Raise / Rule-Based`，平均 **≥ +30 BB/100** 且置信区间显著；
- **教学**：每次建议 ≥2 条解释（桶语义 + 行动/封顶原因/未来股权提示）；
- **鲁棒**：异常信息集可降级（保守兜底 `CONS_FALLBACK`），并记录日志；
- **可复现**：固定随机种子 + 完整命令，可从零复刻策略表。

---

## 7. 风险与缓解
- **LP 规模过大**：从 6/8/8 桶 + 2‑cap 起步；仅对关键分支细化桶；必要时切分子树求解再拼接。
- **叶子 EV 偏差**：提供采样强度开关与缓存；在报告中对比不同采样带来的策略稳定性。
- **SLA 抖动**：策略热加载 + 进程常驻内存 + LRU 最近信息集缓存；大文件用 npz/mmap。
- **“保守感”**：UI 提供“稳健线/进攻线”两档建议（同一 mix 中概率 Top‑2 动作），不改变 baseline，保持教学友好。

---

## 8. 里程碑（与 GTO Plan 同步）
- **M1（当前）**：单提标准锅；turn 截断；2‑cap；half/pot 两档；评测达标。
- **M2**：补 limp pot；扩尺寸 `third/two_third`；关键 turn 节点细化桶至 12。
- **M3**：3bet/4bet 关键线；可选 3‑cap；显式 River 于少量高频节点；引入对手画像的提示层（仍不改 baseline）。

