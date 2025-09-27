# GTO-suggest Feature Specify (Rebuild)

## 背景与目标
- 面向四条街输出“基于GTO的基准策略”建议，将抽象原理落在具体局面，并用易懂的解释支撑。
- 为学习者建立稳定的决策基线，缩小“懂理论但不会用”的差距，增强决策自信与参与感。

## 价值主张
- 理论到实践的桥接：在真实决策节点直观呈现“理论如何指导实践”。
- 强化思维基线：提供稳健、可复用的基准参照。
- 提升学习效率：交互式即时反馈，相较静态内容更易内化与记忆。

## 范围与覆盖
- 街别覆盖
  - 前注前、翻牌、转牌、河牌均输出建议；教学深度保持一致，不因街别弱化解释。
- 底池类型
  - 常见场景必须深入并全覆盖：未入池加注、过牌入池、单次加注、3bet/4bet节点。
  - 多次再加注：按不同“频率/倾向”给出口语化覆盖建议（不承诺逐一还原完整混合频率）。
  - 极端/边界场景：结合上下文给出保守建议；安全兜底范围要足够小（尺寸保守、风险可控），并明确“为何保守”。

## 建议输出（对用户可见）
- 主线建议（行动+尺度）
  - 输出“一条清晰的主线建议”；金额与动作严格可行，落在合法区间内。
  - 若需调整（如提升至最小合法再加注额），明确提示“已调整至合法最小值”（或同义表述）。
- 原因与频率（口语化）
  - 先给能看懂的理由，再给能用的结论（主线动作与尺度）。
  - 频率/倾向以口语化描述融入解释文本（如“此处GTO建议≈75%频率以1/3池持续下注”）。
  - 解释维度统一：位置/角色（IP/OOP、PFR/Caller）、筹码深度/SPR、牌面纹理、面对尺寸与MDF/价格、底池类型、历史行动。
  - 频率通过随机数的方式，映射行为到UI上，确保不会被剥削。

## 对手信息（纳入GTO基准）
- 对手侧信息是“基准建议”的重要依据：位置、已知尺寸/倾向、可合理假设的范围等，均影响基准建议与频率描述。
- 无对手数据时，采用默认的均衡/池均值模型，并在解释中标注“使用基准模型”。

## 教学呈现风格
- 语言简洁直观，少术语或配合必要括注；解释结构与口径一致。
- 示例风格：
  - “GTO建议在这里用75%的频率下注1/3底池。这是因为在这个干燥的K高面上，你的范围优势明显，小注可以低成本地让对手大量的弱牌弃牌。”
- 暂不提供“下一步计划/后续分支”；专注当前节点的基准打法与背后原理。

## “保守建议”的定义与优先级（内部原则）
- 定义：在信息缺失/异常或极端边界场景下，遵循“安全、可行、可解释”的降级建议，限制风险暴露与错误成本。
- 保持后备逻辑的极度简单。例如，当规则缺失时，严格遵循“有位置就过牌，没位置面对小注就跟注，面对大注就弃牌”这类硬编码规则，并明确告知用户“信息不足，采取最保守路线”。

## 边界与降级策略
- 合法与可行优先：永不输出非法动作/越界金额；任何必要规整均附简短解释。
- 多次再加注与少见节点：给出覆盖性的主线建议，并以频率/倾向口语化补足；明确为何不全面混合执行。
- 信息缺失/异常：快速降级为“保守建议”（按上述优先级），并提示原因；兜底尺寸小、风险可控。

## 非功能约束
- 信息完整性（展示必要项）
  - 至少包含：街别、位置/角色、底池类型、SPR要点、牌面结构要点、面对尺寸要点（若有）、主线行动与尺度、简洁解释（含频率/倾向）。
- 一致性与确定性
  - 同输入同输出；解释口径与先后顺序一致；四街教学深度保持一致。
- 性能与互动性
  - 面向交互教学，响应接近实时；异常/缺失快速回退，不阻塞体验。
- 可解释与可追溯
  - 解释含结构化要点/标签，便于可视化与复盘；标注策略版本与关键上下文，便于对比与复现实验。
- 合规与隐私
  - 对手数据仅用于必要推断；不泄露敏感信息；不暗示收益保证或结果确定性。

## 暂不覆盖
- 实时求解器级的精确混合频率与全量多街联动计划。
- 多人底池/多桌位的全面精细化（当前聚焦双人与常见节点，其余给出谨慎边界与保守兜底）。

## 术语与口径（约定）
- 位置：IP（有位置）/OOP（无位置）。
- 角色：PFR（前注前加注者）/Caller（跟注者）。
- 尺寸标签：如 1/3 池、1/2 池、2/3+ 池等（教学口径可与UI保持一致）。
- SPR：筹码/底池比，用于解释控池或极化倾向。
- MDF：最小防守频率，用于解释“为何需要继续”。

## 版本与里程碑（建议）
- M1：四街一致口径的GTO基准建议与解释、常见底池类型全覆盖、保守建议优先级落地。
- M2：多次再加注节点的频率/倾向覆盖增强、更多牌面纹理与角色细化解释。
- M3：引入更丰富的对手信息维度（仍以GTO基准为主线），以及可选的更细粒度频率描述。

---

## 与 GTO Plan 的对齐（落地）
- Baseline Engine：不依赖在线求解，纯“配置/表”驱动；离线解出的策略表作为基准策略源。
- 混合策略落地：导出 `mix:[{action,size_tag,weight}]`；运行时以稳定随机（用 hand_id 等确定性 seed）选择具体臂，既可解释又避免被剥削。
- 输出契约对齐：`meta.baseline = "GTO"`、`meta.frequency`（选中臂权重）、`meta.variant=node_key`、`debug.mix`（便于教学与回放）。
- Exploit 提示：仅作提示与教学点缀，不改变 baseline 动作（包裹层实现）。

## v0 范围与边界（Must/Out of Scope）
### Must‑Have（v0）
- 流水线：抽象（分桶+下注树）→ 截断估值 → 离线 LP 求解 → 导出策略表 → 在线查表。
- 街次：Preflop / Flop / Turn；River 由 Turn 叶子 EV 派生动作（标注 derived）。
- 分桶（Bucketing）：Preflop=6，Flop=8，Turn=8；特征=当前强度 + 提升潜力（outs/改良率）。
- 桶转移：`flop→turn`、`turn→river` 两张转移矩阵（Monte Carlo 采样）。
- 下注树（Action Abstraction）：HU 100bb，动作 `{fold, check/call, bet/raise∈[0.5P,1.0P]}`，每街最多 2 次加注（2‑cap）。
- 叶子 EV：Turn 截断；用 `turn→river` 转移 + 摊牌胜率期望（可采样、可缓存）。
- 运行时 API：`suggest(state) -> {action, size_tag, rationale[], meta}`，本地 CPU P95 ≤ 1s。
- 教学解释：返回 `bucket_id`、桶语义标签、`rationale`（如 `SEMI_BLUFF_BUCKET`、`RAISE_CAP_REACHED`、`PRICE_OK`）、`future_equity_hint`。

### Out of Scope（v0 不做）
- 多人桌（>2 人）、多位置；复杂下注网格（如 1/3P, 2/3P 全谱）；
- 在线实时求解（LP/CFR）；对手建模与自适应剥削；
- 显式 River 展开；分布式/移动端部署；严格最优证明。

### 边界与假设
- 规则：HU NL，100bb，与训练一致；
- 评估：确定性评估器（固定随机种子）；
- 资源：策略表 ≤ 50MB，在线内存 ≤ 1GB；桶映射+查表 ≤ 10ms，整链路 ≤ 1000ms。

## 尺寸与封顶映射
- 尺寸标签（v0）：`0.5P → half`，`1.0P → pot`；允许等效区间（如 0.45P–0.55P 计作 half）。
- 加注封顶：训练树用 2‑cap 控制规模；若线上出现 3rd/4th‑raise 节点，先标注 `approx`（由 2‑cap 频率镜像/插值外推），后续版本用大树替换。

## 四街覆盖与派生标记
- 提供四街建议；River 节点的策略从 Turn 叶子 EV 派生，标记 `derived_from_turn_leaf=true`，UI/日志透明化，后续可替换为显式 River 解。

## 锅型覆盖的里程碑（与产品里程碑呼应）
- M1：单提标准锅（最常见线）。
- M2：limp pot（规则+小 LP 子树）。
- M3：3bet/4bet 关键节点（局部细化树）。

## 数据结构与文件约定
```
repo/
├─ configs/
│  ├─ trees/hu_discrete_2cap.yaml
│  └─ buckets/{preflop,flop,turn}.json
├─ artifacts/
│  ├─ transitions/{flop_to_turn,turn_to_river}.json
│  ├─ policies/{preflop,postflop}.jsonl|.npz
│  └─ ev_cache/turn_leaf.npz (optional)
```

### node_key（建议统一口径）
- 组成：`street/pot_type/role/{ip|oop}/texture/spr/hand_class`。
- `hand_class` 由 `bucket_id` 与离散特征派生（如 `semi_bluff`）。

### 策略表记录（JSONL 示例）
```
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

## 运行时 API 与解释字段
### 输入（精简）
- `street, hero_pos, pot, eff_stack, board, hole_cards, action_history`。

### 输出（对齐现有“建议输出”章节）
- `action: bet|raise|call|check|fold`
- `size_tag: half|pot`
- `rationale: [桶语义/封顶/价格等标签]`
- `meta: { baseline: "GTO", frequency, variant: node_key, debug: { bucket, mix[] } }`
- 稳定混合：以 hand_id 等为 seed 的确定性随机，确保“可复现但不被单局针对”。

## 离线产出流程（可直接执行）
1) 分桶与转移
```
python -m tools.build_buckets --streets preflop,flop,turn --bins 6,8,8 \
  --features strength,potential --out configs/buckets
python -m tools.estimate_transitions --from flop --to turn --samples 200000 \
  --out artifacts/transitions/flop_to_turn.json
python -m tools.estimate_transitions --from turn --to river --samples 200000 \
  --out artifacts/transitions/turn_to_river.json
```
2) 构建抽象树与叶子 EV
```
python -m tools.build_tree --config configs/trees/hu_discrete_2cap.yaml \
  --out artifacts/tree_flat.json
python -m tools.cache_turn_leaf_ev --trans artifacts/transitions/turn_to_river.json \
  --out artifacts/ev_cache/turn_leaf.npz
```
3) LP 求解并导出策略表
```
python -m tools.solve_lp --tree artifacts/tree_flat.json \
  --buckets configs/buckets --transitions artifacts/transitions \
  --leaf_ev artifacts/ev_cache/turn_leaf.npz \
  --solver highs --out artifacts/policies
```
4) 评测与回归
```
python -m tools.eval_baselines --policy artifacts/policies \
  --opponents always_call,always_raise,rule_based --hands 200000 \
  --report reports/eval_v0.md
```

## 成功标准（验收）
- 性能：本地 CPU，1000 次随机查询，P95 ≤ 1s/次；内存 ≤ 1GB。
- 对战：对 Always‑Call / Always‑Raise / Rule‑Based，平均 ≥ +30 BB/100 且置信区间显著。
- 教学：每次建议 ≥2 条解释（桶语义 + 行动/封顶原因/未来股权提示）。
- 鲁棒：异常信息集可降级（保守兜底 `CONS_FALLBACK`），并记录日志。
- 可复现：固定随机种子 + 完整命令，可从零复刻策略表。

## 风险与缓解
- LP 规模过大：从 6/8/8 桶 + 2‑cap 起步；仅对关键分支细化桶；必要时切分子树求解再拼接。
- 叶子 EV 偏差：提供采样强度开关与缓存；报告对比不同采样带来的策略稳定性。
- SLA 抖动：策略热加载 + 进程常驻内存 + LRU 最近信息集缓存；大文件用 npz/mmap。
- “保守感”：UI 提供“稳健线/进攻线”两档建议（同一 mix 中概率 Top‑2 动作），不改 baseline，教学友好。

## 里程碑（对齐版）
- M1（当前）：单提标准锅；turn 截断；2‑cap；half/pot 两档；评测达标。
- M2：补 limp pot；扩尺寸 `third/two_third`；关键 turn 节点细化桶至 12。
- M3：3bet/4bet 关键线；可选 3‑cap；显式 River 于少量高频节点；引入对手画像的提示层（仍不改 baseline）。
