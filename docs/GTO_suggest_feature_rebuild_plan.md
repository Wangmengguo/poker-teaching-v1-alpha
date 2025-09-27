# GTO Suggest Feature Rebuild — Technical Plan (v0 集成版，修订版)

## 0) Roadmap & Cadence（对齐 v0 计划）
- M1（Week 1–2）：分桶与转移矩阵 + 抽象下注树（2‑cap）+ Turn 截断叶子 EV 缓存；端到端规则路径（不依赖 LP 表）与教学解释打通；混合策略基础设施（确定性掷签）就绪但默认不启用；河牌暂走规则/启发式（非 LP 表）。
- M2（Week 3–4）：LP 求解离线产物 + 策略表导出（以 NPZ 为主，JSONL 仅调试抽样）+ 基线评测（≥ +20~30 BB/100，95% CI>0）；运行时接入策略表并优先查表，失败自动回退规则；频率口语化接入。
- M3（Week 5）：关键 3bet/4bet 线覆盖（规则或小量表项）+ 少量高频 River 显式节点；运行时混合灰度（Top‑2 仅在教学/实验开关下显示，不改变 baseline 主线）；性能优化 P95 ≤ 1s。

交付节奏：每周输出可演示工件（artifacts/报告），合入仓库可复现。

## 1) Goals and Non‑Goals
- Goals
  - Deliver a GTO baseline that returns one clear, legal, executable suggestion (action + sizing) per node, with concise “why” explanations and frequency phrasing.
  - Cover all four streets with consistent teaching depth; fully cover common pot types; multi‑reraises 仅在关键线以口语化频率覆盖（M3），不承诺全面混合。
  - Keep GTO baseline pure; add exploit tips as a separate, optional layer that never alters the baseline action.
- Non‑Goals (now)
  - No online solver integration; no per‑hand real‑time equilibrium solving.
  - No automated exploitative action changes; exploit is surfaced as tips only.

## 2) Scope and Coverage
- Streets: preflop, flop, turn, river — all produce suggestions with uniform explanation depth.
- Pot types: limped, single‑raised, 3‑bet/4‑bet nodes。Multi‑reraises：关键线以口语化频率覆盖（M3），不承诺全面混合。
- Edge/unknown: fall back to a minimal, hard‑coded conservative rule set; always legal, small, explainable.
  - River（M1/M2）：默认走规则/启发式（MDF/赔率+有限价值加注），LP 表仅至 Turn；M3 评估为少量高频节点显式表项。

## 2a) Work Breakdown（WBS，对齐 v0 执行计划）
- Bucketing & Transitions（Owner: Data/Algo）
  - DoD：`configs/buckets/*.json`、`artifacts/transitions/*.json` 生成且单测通过（漂移 <1%、TV<0.05）。
- Tree & Leaf EV（Owner: Algo/Infra）
  - DoD：2‑cap 树校验通过，`ev_cache/*.npz` 命中率≥99%。
- LP Solver（Owner: Algo）
  - DoD：玩具树可复现；导出的策略表概率合法（∈[0,1] 且和=1）；评测可跑通。
- Runtime Suggest（Owner: Backend）
  - DoD：1000 随机局面 P95 ≤ 1s；每次≥2条解释；缺失节点触发保守回退并落日志；混合基础设施可控开关（默认关闭）。
- Eval & Reports（Owner: QA/Algo）
  - DoD：≥ +20~30 BB/100（固定采样方案，95% CI>0）；评测脚本入 CI，固定随机种子/对手分布；出评测报告。

## 2b) Technical Boundaries（v0）
- 规模控制：6/8/8 桶 + 每街 2‑cap；Turn 截断；River EV 可由 Turn 叶子派生并标注 `derived_from_turn_leaf`（M1/M2 的河牌建议走规则）。
- SLA：预热 200ms 内加载策略（以 NPZ+内存映射为主，JSONL 仅调试抽样）；单次查询 P95 ≤ 1s；运行时只查表 + 常数阶逻辑。
- 资源：单机 CPU，内存 ≤ 1GB；策略文件目标 ≤ 50MB（软目标，可通过分片/压缩/裁剪关键节点达成）。
- 一致性：训练与运行使用相同的树/桶/尺寸映射；固定随机种子；Exploit 只作提示不改 baseline；频率口语化描述不等价于“不可被剥削”。

## 2c) Offline Pipeline（Artifacts & Commands）
- 产物约定
  - Buckets：`configs/buckets/{preflop,flop,turn}.json`
  - Transitions：`artifacts/transitions/{flop_to_turn,turn_to_river}.json`
  - Tree：`configs/trees/hu_discrete_2cap.yaml` → `artifacts/tree_flat.json`
  - Leaf EV Cache：`artifacts/ev_cache/turn_leaf.npz`
  - Policies：`artifacts/policies/{preflop,postflop}.npz`（主）/ `*.jsonl`（调试抽样）
- 执行命令（可直接运行）
  - 分桶与转移
    - `python -m tools.build_buckets --streets preflop,flop,turn --bins 6,8,8 --features strength,potential --out configs/buckets`
    - `python -m tools.estimate_transitions --from flop --to turn --samples 200000 --out artifacts/transitions/flop_to_turn.json`
    - `python -m tools.estimate_transitions --from turn --to river --samples 200000 --out artifacts/transitions/turn_to_river.json`
  - 树与叶子 EV
    - `python -m tools.build_tree --config configs/trees/hu_discrete_2cap.yaml --out artifacts/tree_flat.json`
    - `python -m tools.cache_turn_leaf_ev --trans artifacts/transitions/turn_to_river.json --out artifacts/ev_cache/turn_leaf.npz`
  - LP 求解与导出策略表
    - `python -m tools.solve_lp --tree artifacts/tree_flat.json --buckets configs/buckets --transitions artifacts/transitions --leaf_ev artifacts/ev_cache/turn_leaf.npz --solver highs --out artifacts/policies`
  - 评测与回归
    - `python -m tools.eval_baselines --policy artifacts/policies --opponents always_call,always_raise,rule_based --hands 200000 --report reports/eval_v0.md`

说明：LP 优先使用 HiGHS（highspy）；若环境不可用，可用 `scipy.optimize.linprog` 作为玩具树备选以完成 M2 闭环，后续替换为 HiGHS。

## 2d) Deterministic Mixing & Node Key（新增）
- 单一主线建议与混合的口径
  - 运行时默认仅输出一条主线建议；频率仅在解释文本中口语化表述。
  - Top‑2（稳健/进攻）展示仅在教学/实验开关下启用，不改变 baseline 动作与评测口径。

- node_key 统一口径与签名（用于离线表/运行时查表）
  - 组成字段（离散化/归一化后）：
    - `street` ∈ {preflop, flop, turn, river}
    - `pot_type` ∈ {limped, single_raised, threebet}
    - `role` ∈ {pfr, caller, na}（limped 场景统一为 `na`）
    - `pos` ∈ {ip, oop}
    - `texture` ∈ {dry, semi, wet, na}
    - `spr` ∈ {low, mid, high}
    - `bucket` ∈ Z（来自桶映射的整数 id）
  - 签名（伪代码）：
```
def node_key_from_observation(obs: Observation) -> str:
    role = obs.role if obs.pot_type != "limped" else "na"
    pos = "ip" if obs.ip else "oop"
    texture = obs.board_texture or "na"
    spr = str(obs.spr_bucket or "na")  # low|mid|high
    bucket = int(getattr(obs, "bucket_id", getattr(obs, "bucket", -1)))
    return "/".join([
        obs.street,
        str(obs.pot_type or "single_raised"),
        f"role:{role}",
        pos,
        f"texture:{texture}",
        f"spr:{spr}",
        f"bucket:{bucket}",
    ])
```
  - 示例输出：`"flop/single_raised/role:pfr/ip/texture:dry/spr:low/bucket:5"`

- 确定性混合：stable_weighted_choice（实现草案）
```
import hashlib
from typing import Sequence

def stable_weighted_choice(seed: str, weights: Sequence[float]) -> int:
    """确定性按权重选择索引：
    - seed 建议由 hand_id + node_key 组成，保证“同手同节点稳定”；
    - 权重会先归一化；
    - 退化情形（全零/NaN/负值）回退到 argmax。"""
    ws = [max(0.0, float(w or 0.0)) for w in (weights or [])]
    if not ws:
        return 0
    s = sum(ws)
    if s <= 0:
        return max(range(len(ws)), key=lambda i: ws[i])
    cdf = []
    acc = 0.0
    for w in ws:
        acc += w / s
        cdf.append(acc)
    h = hashlib.sha1((seed or "").encode("utf-8")).hexdigest()
    r = (int(h[:8], 16) % 10_000_000) / 10_000_000.0
    for i, t in enumerate(cdf):
        if r < t:
            return i
    return len(ws) - 1
```

- 混合注入点（运行时查表后的融合流程，伪代码）
```
node = lookup_policy_node(node_key)
if node and "mix" in node:  # mix: [{action, size_tag, weight}, ...]
    seed = f"{hand_id}:{node_key}"
    idx = stable_weighted_choice(seed, [arm["weight"] for arm in node["mix"]])
    arm = node["mix"][idx]
    suggested = {"action": arm["action"], "size_tag": arm.get("size_tag")}
    meta.update({
        "frequency": [arm["weight"] for arm in node["mix"]],
        "mix_chosen_index": idx,
        "node_key": node_key,
    })
else:
    # 单臂节点或无表 → 按规则路径或单臂表项执行
    suggested = rule_fallback_or_single_arm(node)
```
说明：混合默认关闭（通过开关控制渲染/展示），即便开启也仅影响解释中的频率描写，不改 baseline 动作选择口径（只选中一条臂执行）。

## 3) Architecture and Separation of Concerns
- Baseline Engine (GTO)
  - Inputs: Observation + SuggestContext (config tables + modes).
  - Behavior: rule/表 lookup → 若节点含 `mix` 且混合开关开启，则确定性混合选择一臂；否则按单臂 → Decision → normalized suggestion。
  - Constraints: baseline does not read rich opponent stats; only observation + config tables/modes.
- Exploit Wrapper (optional) — 弱点识别（基于GTO基准分析）
  - Inputs: bounded opponent stats (pooled/session aggregates) and current node context.
  - Behavior: emits “弱点识别提示” when safe thresholds are met; never changes `suggested`.
  - UI: rendered as an auxiliary tip (e.g., light‑bulb) under the coach card.
- Service Layer
  - Responsibilities unchanged: legality/clamps, min‑reopen lift, rationale/explanations, confidence, logging.
- UI
  - Continues to consume `suggest` payload; may render frequency text and exploit tips when present.
  - Frequency display agreement: do not add new UI fields; frequency appears only inside explanations text. `meta.frequency` is for templating/logs, not for direct UI binding.

## 3a) Data Schema（node_key 与策略表）
- node_key 统一口径：`street/pot_type/role/{ip|oop}/texture/spr/bucket`
  - `bucket` 为离线分桶的整数 id；教学用的 hand_class/标签仅作为 meta，不参与 node_key。
- 策略表记录（JSONL 示例）
```
{
  "node_key": "flop/single_raised/role:pfr/ip/texture:dry/spr:low/bucket:5",
  "mix": [
    {"action":"bet","size_tag":"half","weight":0.62},
    {"action":"check","weight":0.38}
  ],
  "meta": {"cap":2,"bucket":5,"derived_from_turn_leaf":false,
            "explain":["SEMI_BLUFF_BUCKET","PRICE_OK"]}
}
```

## 4) Deterministic Mixing (for mixed GTO nodes)
- Rationale
  - Frequencies must drive action, otherwise they confuse users and create predictable pure strategies.
- Design
  - Node schema supports `mix: [ {action, size_tag, weight}, ... ]` (single node continues to support `{ action, size_tag, freq? }`).
  - Build `node_path` from classification keys before selection:
    - `"{street}/{pot_type}/{role}/{ip|oop}/{texture}/{spr}/{hand_class}"`.
  - Stable seed key: `"{seed_basis}|{node_path}"`, where `seed_basis` is `hand_id` (default) or `session_id`.
  - Hash seed key to `u in [0,1)` and choose by cumulative (normalized) weights.
  - If `SUGGEST_MIXING=off`, pick the highest‑weight arm deterministically.
  - Hashing algorithm: use a fast, well‑distributed non‑cryptographic hash (MurmurHash3 or xxHash). If adding a dep is not feasible, reuse existing sha1 helper consistently across the codebase.
  - Confirmed defaults: use `hand_id` as the default seed basis; session‑level basis can be considered later if needed, but is not enabled by default.
- Implementation Notes
  - Helper (utils): `stable_weighted_choice(seed_key: str, weights: list[float]) -> int`.
  - Store selection in `debug.meta.mix = { seed_key, arms, chosen_index }` and `meta.frequency` as the chosen arm’s weight.
  - Worked example (K‑high dry, IP, single‑raised): rules provide `mix=[{bet,third,0.75},{check,_,0.25}]`; for a given `hand_id`, hashing selects one arm; UI explanation renders “混合策略抽样（~75%）”。

## 5) Conservative Fallback (minimal, hard‑coded)
- When rule node missing or information gap:
  - No bet yet: prefer `check` if legal; else smallest legal `bet`.
  - Facing bet: if facing ∈ {third, half} and `call` legal → `call`; if `two_third+` and `fold` legal → `fold`; else prefer `check` then `fold`.
  - Preflop: SB first‑in `check` (or limp completion when `to_call ≤ 1bb`); facing raise: `call` if `to_call ≤ 1bb` else `fold`.
- Emit single rationale code `CFG_FALLBACK_USED` with `{ reason: "missing_rule|info_gap" }`。
- Do not attempt “smart block‑bet” in fallback; keep minimal and predictable.
 - Clarification (preflop limp threshold): SB first‑in limp completion uses a fixed price threshold `to_call ≤ 1bb`.

## 6) Rules and Config Schema
- Preflop tables (extend)
  - Existing: `open_table`, `vs_table`.
  - Add optional `freq_hint` per node, e.g. `{ "reraise": 0.25, "call": 0.5 }`.
- Postflop rule nodes (extend)
  - Single: `{ action, size_tag, freq?, plan? }`.
  - Mixed: `{ mix: [ { action, size_tag, weight }, ... ], plan?, rule_notes? }`.
 - Keep `defaults` fallback and existing keying: `pot_type/role/(ip|oop)/texture/spr/hand_class`.
 - Exploit thresholds (new)
   - Config file: `config/exploit_thresholds.json` with adjustable thresholds and sample‑size floors, e.g.:
     - `{ "flop_fold_to_cbet": {"thr": 0.75, "min_n": 30 }, "turn_fold_to_barrel": {"thr": 0.70, "min_n": 20 }, ... }`.

### Sizing & Cap（v0 规则）
- 尺寸标签：`0.5P → half`，`1.0P → pot`；允许等效区间（如 0.45P–0.55P 计作 half）。
- 加注封顶：训练树为 2‑cap；线上若出现 3rd/4th‑raise 节点，先标注 `approx`（以 2‑cap 频率镜像/插值外推），后续用更大树替换。

## 7) Opponent Data — Baseline vs Exploit（弱点识别）
- Baseline (GTO): does not branch on opponent stats; only observation + config tables/modes.
- 弱点识别（Exploit Wrapper）
  - M1 minimal set (confirmed): implement a minimal threshold set first, then iterate. Initially ship only
    - `flop_fold_to_cbet` and
    - `turn_fold_to_barrel`
    with copy/templates aligned to these; other examples remain backlog for later expansion.
  - Features & defaults (with sample‑size floors):
    - Flop fold to c‑bet ≥ 75% with N≥30 → 高频 1/3 cbet（强度：高）
    - Turn fold to 2nd barrel ≥ 70% with N≥20 → 增加二次下注频率/尺寸（强度：中）
    - BB fold to steal ≥ 70% with N≥40 → SB/RFI 更高频小尺寸开局（强度：中）
    - Fold to 3bet/4bet ≥ 65% with N≥25 → 相应节点扩大诈唬频率（强度：中）
    - River overfold to bet ≥ 65% with N≥15 → 偏向薄价值下注（强度：中）
    - Check‑raise rate ≤ 5% with N≥25 → 小面 cbet 更放心（强度：低‑中）
  - Output structure for UI/UX:
    - Prefer template-based payload to decouple copy/i18n from backend:
      - `tips: [ { code, strength: high|mid|low, align: aligns|diverges, metrics: { name, value, N, window }, tip_template_code, tip_template_data, text? } ]`
      - `tip_template_code` examples: `EXP_FLOP_OVERFOLD_CBET_TEXT`, `EXP_TURN_OVERFOLD_BARREL_TEXT`, `EXP_BB_OVERFOLD_STEAL_TEXT`, `EXP_PREFLOP_OVERFOLD_3BET_TEXT`, `EXP_RIVER_OVERFOLD_TEXT`, `EXP_LOW_CXRATE_TEXT`。
      - `tip_template_data` example (flop overfold to c‑bet): `{ "value": 0.85, "value_pct": "85%", "N": 30, "window": "last_3_sessions", "size_tag": "third", "bet_size": "1/3" }`
      - Backend may optionally include a fallback `text` for debugging; clients should prefer template rendering.
  - Templating/i18n notes:
    - Tips follow rationale’s template philosophy: backend provides `tip_template_code` + data; the client (or a shared i18n module) renders localized strings.
    - Keep variable names stable and documented per code; avoid UI-breaking renames.
  - Align判定（伪代码）：
    - `if gto.action in {bet,raise} and tip.suggests_betting: align = 'aligns'`
    - `elif gto.action == 'check' and tip.suggests_betting: align = 'diverges'`
    - `elif gto.action in {bet,raise} and tip.suggests_different_sizing: align = 'aligns' // 核心动作一致`
    - `elif gto.action == 'fold' and tip.suggests_call: align = 'diverges'`
    - `else: align = 'diverges'`（按需扩展）
  - Data source assumption: a near‑real‑time (minutes‑level) aggregation service provides opponent frequencies with sample sizes. Tip quality depends on accuracy and coverage.
  - No pool‑mean fallback for tips: if no opponent‑specific data meeting `min_n`, do not show tips（避免误导）。
  - Gating: `SUGGEST_EXPLOIT_TIPS=on|off` (default on); tips reside in `debug.meta.exploit.tips` and optional rendered list.

## 8) Output Contract (Service)
- Keep keys: `hand_id, actor, suggested, rationale, policy, confidence`.
- `meta` additions
  - `baseline: "GTO"`, `mode: "GTO"`, `frequency: number|string`, `node_key: string`, `variant: string` (compact/legacy key if需要), existing `size_tag/plan`。
- `debug.meta` additions
  - `mix: { seed_key, arms, chosen_index }`, `rule_path`, and optional `exploit: { tips: [ { text, strength, align, metrics:{name,value,N,window}, code } ] }`。
- Explanations
  - Localized templates accept `{frequency:.0%}` and `{size_tag}`; mixed selection phrased as “该节点为混合策略，本手抽样为此分支（~{frequency:.0%}）”。

## 9) Feature Flags and Rollout
- `SUGGEST_POLICY_VERSION=v1` (existing).
- `SUGGEST_MIXING=on|off` (default off)。
- `SUGGEST_MIX_SEED=hand|session` (default hand).
- `SUGGEST_EXPLOIT_TIPS=on|off` (default on).
- Existing: `SUGGEST_STRATEGY`, `SUGGEST_DEBUG`, `SUGGEST_TABLE_MODE`。
- 新增：`SUGGEST_POLICY_SOURCE=rules|lp_table`（默认 `rules`）与已存在的 `SUGGEST_POLICY_VERSION` 正交：
  - 当 `lp_table` 不存在或加载失败 → 自动回退 `rules` 并落结构化日志；
  - 当 `lp_table` 存在 → 运行时优先查表（与 `rules` 保持同一 node_key 与尺寸口径）。

## 10) Telemetry and Logging
- Metrics
  - `mix_applied(street,pot_type,rule_path)`, `fallback_used(street)`（任何一次出现都为高优先级待办，目标趋近为0）、`exploit_tips_shown(kind)`。
- Logs (structured)
  - `policy_name`, `street`, `action`, `amount`, `size_tag`, `frequency`, `rule_path`, `pot_type`, `bucket`, `node_key`, `policy_source`, `to_call_bb`, `pot_odds`, `mix.chosen_index`。

## 11) Testing Strategy
- Offline artifacts
  - Bucketing：同一牌面/手牌映射稳定性（漂移 < 1%）。
  - Transitions：行归一化、样本量变化下 TV 距离 < 0.05。
  - Tree：2‑cap 约束与终局节点计数一致；结构校验。
  - LP Solver：玩具树可解，混合概率合法（∈[0,1] 且和=1）。
- Mixing determinism
  - Same `hand_id` + node_key → same arm; distribution approximates weights over many hands; mixing off → highest weight.
- Baseline vs wrapper separation
  - Assert `suggested` unaffected when exploit tips are enabled; tips appear only in debug/meta/UI tip list.
- Fallback
  - Missing rule nodes trigger minimal fallback; ensure no raises are proposed; rationale `CFG_FALLBACK_USED` present。
- Service
  - Clamp normalization occurs once; min‑reopen rationale not duplicated; explanations render frequency text when available.
- Preflop/Flop/Turn/River cases
  - RFI with freq hint, BB defend buckets with reraise/call, dry K‑high small cbet, MDF rationale when facing bets, limped defaults.

## 12) Milestones（对齐 v0 执行计划）
- M1（W1–W2）：分桶/转移、2‑cap 下注树、Turn 截断叶子 EV 缓存；落仓 `configs/buckets`、`artifacts/transitions`、`artifacts/tree_flat.json`、`artifacts/ev_cache/*.npz`；规则路径端到端+教学解释；确定性混合与保守回退基础设施（默认关闭混合）。
- M2（W3–W4）：LP 求解离线产物与策略表导出（NPZ 主、JSONL 调试）；完成基线评测（≥ +20~30 BB/100，95% CI>0）与报告；策略热加载与一致性校验；频率口语化解释接入；`SUGGEST_POLICY_SOURCE=lp_table` 可灰度。
- M3（W5）：关键 3bet/4bet 线与少量高频 River 显式节点；运行时混合灰度与Top‑2教学展示（不改baseline）；端到端 P95 ≤ 1s；Exploit 提示模板化与阈值配置接入。

## 13) Implementation Tasks (Backlog)
- Tools & Artifacts
  - `tools.build_buckets`：实现强度/潜力特征与分箱；产出 `configs/buckets/*.json`。
  - `tools.estimate_transitions`：Monte Carlo 桶转移估计；产出 `artifacts/transitions/*.json`。
  - `tools.build_tree`：从 `configs/trees/*.yaml` 生成扁平树；2‑cap 校验；产出 `artifacts/tree_flat.json`。
  - `tools.cache_turn_leaf_ev`：基于 `turn→river` 转移与 river 摊牌胜率近似缓存叶子 EV；产出 `artifacts/ev_cache/*.npz`。
  - `tools.solve_lp`：LP 求解（可先 v0 简化版，后续升级 sequence‑form）；导出 `artifacts/policies/*.jsonl|.npz`。
  - `tools.eval_baselines`：对战评测脚本与报告输出。
- Helpers
  - Add `stable_weighted_choice` in `packages/poker_core/suggest/utils.py`（按本文档草案实现）。
  - Add conservative fallback helper `choose_conservative_line(obs, acts)` in policies。
  - Add `node_key_from_observation(obs)`（统一口径函数，供离线/运行时共用）。
- Policy integration
  - Runtime：在 `_match_rule_with_trace/_lookup_node` 之后，如有 `mix` 则按 `stable_weighted_choice` 选择一臂，填充 `meta.frequency/mix_chosen_index/node_key`；否则单臂。
  - Policy source：支持 `SUGGEST_POLICY_SOURCE=rules|lp_table`，在 `lp_table` 可用时优先查表，否则自动回退到 `rules` 并落结构化日志。
- Exploit wrapper
  - 新模块 `packages/poker_core/suggest/exploit.py`（受 gate 控制）生成 `tips`；在 service 渲染前注入，不改变 baseline 动作。
- Codes & explanations
  - 扩展 `packages/poker_core/suggest/codes.py`：`GTO_CBET_FREQ`, `GTO_PREFLINE_MIX`, `CFG_FALLBACK_USED` 等；
  - 更新 `config/explanations_zh.json`：频率/混合/回退文案模板。
- Service/meta
  - 填充 `meta.baseline/mode/frequency/node_key/mix_chosen_index`；附带 `debug.meta.mix`、`exploit.tips`（若有）。
- Tests
  - 单测：桶映射/转移矩阵/树 2‑cap 校验/LP 解合法性。
  - 集成：1000 随机局面 P95 ≤ 1s；缺失节点/越界尺寸触发回退并落日志；混合确定性（同手同节点稳定）。

## 14) Real‑World Constraints Coverage
- No solver at runtime: curated JSON rules + deterministic mixing approximate GTO; conservative fallback guarantees legality and safety.
- Opponent data sparsity: baseline independent of opponent; tips rely on pooled thresholds; gated and optional.
- UI continuity: coach card already consumes `size_tag/plan/explanations`; frequency appears in explanations to avoid UI churn; tips are additive.
- Legality and amounts: policy + service enforce legal ranges; min reopen lift is already covered; clamp warning emitted once.
  
注：频率的口语化描写用于教学呈现与长期频率趋近，非“不可剥削”承诺；严格不可剥削仅在全局均衡解与在线混合执行可控时成立，超出 v0 范畴。

---
Document owner: Engineering (Suggest)
Version: v1.1（对齐 docs/GTO‑suggest‑feature‑specify‑rebuild.md 与 docs/suggest_v_0_execution_plan_with_technical_boundaries_how_to.md）
