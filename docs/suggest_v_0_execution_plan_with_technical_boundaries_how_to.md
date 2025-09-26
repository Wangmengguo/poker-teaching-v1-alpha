# Suggest v0 · Execution Plan

> 目标：把 v0 SPEC 落成“可执行计划”。包含：里程碑、任务分解、接口签名、脚本命令、测试与验收、技术边界与实现细节。

---

## 0. 里程碑与节奏

- **M1（Week 1–2）**：分桶与转移矩阵 + 抽象下注树 + 叶子EV缓存。
- **M2（Week 3–4）**：LP 求解离线产物 + 策略表导出 + 评测基线。
- **M3（Week 5）**：运行时 suggest 接口 + 教学解释 + 性能优化，达成 P95 ≤ 1s。

每周结束产出可演示工件（artifacts + 报告），并提交到 repo。

---

## 1. 工作分解结构（WBS）

### 1.1 Bucketing & Transitions（Owner: Data/Algo）

- **DoD**：`configs/buckets/*.json` 与 `artifacts/transitions/*.json` 生成且通过单测（漂移 <1%、TV<0.05）。
- **产物**：桶定义、转移矩阵、特征计算模块。

### 1.2 Tree & Leaf EV（Owner: Algo/Infra）

- **DoD**：树 JSON 校验通过（cap/终局一致，节点计数与期望一致），`ev_cache/*.npz` 命中率≥99%。
- **产物**：下注树配置、扁平树、叶子 EV 缓存。

### 1.3 LP Solver（Owner: Algo）

- **DoD**：小型玩具树可复现文档中的解；策略表总和=1、权重∈[0,1]；生成的策略能在评测中跑通。
- **产物**：LP 求解器、策略表导出脚本与产物。

### 1.4 Runtime Suggest（Owner: Backend）

- **DoD**：随机 1000 局面 P95 ≤ 1s，端到端结果含 ≥2 条解释；缺失节点时触发保守回退并落日志。
- **产物**：运行时库、API 封装、尺寸映射表。

### 1.5 Eval & Reports（Owner: QA/Algo）

- **DoD**：≥ +30 BB/100（95% CI>0），报告包含方法、参数与曲线；评测脚本纳入 CI 并支持回归对比。
- **产物**：评测脚本、数据表、评测报告（Markdown）。

---

## 2. 技术边界（Boundaries）

- **博弈规模控制**：6/8/8 桶 + 每街 2‑cap；只到 Turn 显式展开；River 由叶子 EV 推导动作并标记 `derived_from_turn_leaf`。
- **SLA**：
  - 启动预热 200ms 内加载策略；单次查询 P95 ≤ 1s；
  - 运行时不做任何采样/模拟；只查表 + 常数阶逻辑。
- **资源**：单机 CPU，内存 ≤ 1GB；策略文件 ≤ 50MB。
- **一致性**：训练与运行使用同一树、同一桶映射与尺寸映射；随机种子固定；
- **兼容 GTO Plan**：
  - 输出契约：`meta.baseline='GTO'`、`meta.frequency`、`meta.variant=node_key`、`debug.mix`；
  - Exploit 提示层仅文本提示，不改 baseline 行动。

---

## 3. 关键实现细节（How‑To）

### 3.1 桶映射（Flop/Turn）

- 特征：`[strength, potential, is_draw(顺/同), board_texture(onehot)]`；
- 分箱：先按 strength 做等概率分位，再在各分位内按 potential 二分（稳定、可解释）。
- 半诈唬桶：`strength < q25 且 potential > q75` → 标注 `SEMI_BLUFF_BUCKET`。

### 3.2 叶子 EV 计算

- 对 (hero\_bucket, opp\_bucket) 组合，基于 `turn→river` 转移矩阵得到两个分布；
- 展开到 river 桶对（小矩阵乘法），使用预先估计的 river 摊牌胜率表近似；
- 存为 `npz`，运行时 O(1) 查询。

### 3.3 LP 变量与约束（v0 近似版）

- 变量：每节点的行为策略 `π(a|I)`；对手对偶变量 `v(I)`；
- 约束：
  - `sum_a π(a|I)=1, π≥0`；
  - 期望收益对偶上界：`u ≤ sum_{终局} P(路径; π, 对手best)·payoff`；
- 目标：最大化最小收益或最小化 exploit 上界（具体以实现可行为主）。

> 备注：v1 升级为严格 sequence‑form（序列流守恒、对偶约束齐备）；v0 先以可运行和稳定混合为第一目标。

### 3.4 稳定混合（确定性随机）

- `seed_key = hash(hand_id || node_key)`；
- `stable_weighted_choice(seed_key, weights)` → 选择动作；
- 记录 `meta.frequency = chosen_weight`，用于 UI 档位文案（稳健线/进攻线可取 mix Top‑2）。

### 3.5 错误与回退

- 查不到 node\_key → 退化到保守策略（如 `check/call`），打上 `CONS_FALLBACK`；
- cap 已达成仍请求加注 → 强制改为 `call`，标注 `RAISE_CAP_REACHED`。

---

## 4. 接口与数据格式

### 4.1 `node_key` 生成

- 组成：`street/pot_type/role/{ip|oop}/texture/spr/hand_class`；
- `hand_class` 由 `bucket_id` + 若干离散标志（draw, pair, overpair 等）。

### 4.2 策略表 JSONL

```json
{
  "node_key": "flop/std/ip/dry/spr:7/b:5",
  "mix": [
    {"action":"bet","size_tag":"half","weight":0.62},
    {"action":"check","weight":0.38}
  ],
  "meta": {"cap":2,"bucket":5,"derived_from_turn_leaf":false,"explain":["SEMI_BLUFF_BUCKET","PRICE_OK"]}
}
```

---

## 5. 测试与验收（CI/QA）

- **单测**：
  - `feature_eval_test.py`：同一牌面/手牌 → 桶映射稳定性（漂移 < 1%）。
  - `transitions_test.py`：行归一化、样本量变化下矩阵差异可控（TV 距离 < 0.05）。
  - `tree_builder_test.py`：2‑cap 约束正确；终局节点计数一致。
  - `solver_test.py`：小型玩具树可解，混合概率合规（∈[0,1] 且和=1）。
- **集成测试**：
  - 随机 1000 局面批量 `suggest`，P95 ≤ 1s；
  - 缺失节点/越界尺寸触发回退并记录日志。
- **对战评测**：
  - `Always-Call/Always-Raise/Rule-Based`：≥ +30 BB/100，95% CI 不跨 0；
  - 稳定性：不同随机种子下策略差异对胜率影响 < 10% 相对误差。

---

## 6. 工具与依赖

- Python 3.11+；`numpy`, `pandas`, `numba`（可选），`scipy`（linprog/highs），评估库（PokerKit 或同等）。
- 可选：`pulp/cvxpy` + `highs`/`glpk`；
- 任务脚本统一入口：`pyproject.toml` 中定义 `tool.poetry.scripts`。

---

## 7. 路线图（对齐 GTO Plan）

- **M1**：最小闭环（分桶/转移/2‑cap/turn 截断/half & pot）。
- **M2**：limp pot + 尺寸扩展（third/two\_third）+ Turn 关键节点 12 桶细化。
- **M3**：3bet/4bet 关键线 + 可选 3‑cap + 少量 River 显式节点（高频）+ Exploit 提示模版化。

---

## 8. 风险与备选方案

- **LP 难以收敛/规模超标** → 降桶或分块求解（子树独立求解 + 拼接）；提供 v0.5：纯规则近似代替 LP，但保留相同策略表接口。
- **叶子 EV 偏差** → 增加采样强度开关与交叉验证；对比不同采样量下的策略稳定性。
- **SLA 超标** → 预热 + mmap + LRU；必要时将策略表转 `npz` 并使用内存映射数组。

