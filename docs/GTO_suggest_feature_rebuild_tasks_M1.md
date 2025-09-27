# GTO Suggest Feature Rebuild — M1 任务拆分（TDD 先行）

本文件依据《docs/GTO_suggest_feature_rebuild_plan.md》的 M1 目标，将工作拆解为可落地、以测试驱动开发（TDD）为先的任务包。每个任务包含：需先编写的测试、实现要点、交付物路径、验收标准（DoD）。

- 覆盖范围：四街建议（preflop/flop/turn/river），端到端教学解释与规则路径打通；不引入在线求解。
- M1 基线：仅规则/启发式；混合策略基础设施就绪但默认关闭；River 走规则/启发式；Turn 叶子 EV 做近似缓存。
- 运行时：只查表 + 常数阶逻辑；保持现有 API 契约；新增字段进入 `meta/debug.meta` 不破坏 UI。

---

## A. Bucketing & Transitions（离线产物）

### ✅ 任务 A1：分桶工具 tools.build_buckets（含 6-8-8 桶语义）
- 先写的测试
  - `tests/test_tools_buckets.py`
    - `test_build_buckets_creates_files_and_schema()`：调用构建（通过函数或 `-m`），断言生成 `configs/buckets/preflop.json, flop.json, turn.json`，并包含 `version:int, bins:int, features:list[str]`，三街 `bins=6/8/8`。
    - `test_bucket_mapping_stability_seeded()`：同一种子两次产出一致（漂移=0）。
  - `tests/test_bucket_semantics.py`
    - `test_flop_turn_8bucket_rules_examples()`：给定最小样例（若干牌面与手牌标签），映射到期望桶 id 与标签（见“规则与标签”）。
    - `test_preflop_6bucket_equiv_classes()`：预设等价类（如 premium_pair/strong_broadway/suited_ace/...）映射稳定。
- 实现要点
  - CLI：`python -m tools.build_buckets --streets preflop,flop,turn --bins 6,8,8 --features strength,potential --out configs/buckets --seed 42`
  - 输出 JSON：`{ version, bins, features, meta:{ seed, ... } }`；可后续扩展映射明细。
  - 桶语义与判定（需落在 `configs/buckets/{flop,turn}.json` 的 `labels` 与 `rules` 字段，且“写死”在配置中，避免代码隐式顺序）：
    - Preflop（6 桶，示例标签）：`premium_pair, strong_broadway, suited_ace, medium_pair, suited_connectors, junk`。
    - Flop/Turn（8 桶，示例标签）：`value_two_pair_plus, overpair_or_tptk, top_pair_weak_or_second, middle_pair_or_third_minus, strong_draw, weak_draw, overcards_no_bdfd, air`。
    - 以布尔/if-else 规则描述（是否两对+、是否 OP/TPTK、是否 FD/NFD、是否 OESD/GS、是否两高张且无 BDFD 等），并配最小样例在测试中断言。
  - 匹配优先级（冲突消解，配置写死）：在 `configs/buckets/{flop,turn}.json` 增加 `match_order`（示例）：
    `value_two_pair_plus → overpair_or_tptk → top_pair_weak_or_second → middle_pair_or_third_minus → strong_draw → weak_draw → overcards_no_bdfd → air`。
    - 在 `tests/test_bucket_semantics.py` 增加用例：当同时满足“成手”和“强听”时，优先命中成手桶（如 `overpair_or_tptk`），而非 `strong_draw`（示例：OP/TPTK + FD 命中成牌类）。
- 交付物
  - `configs/buckets/{preflop,flop,turn}.json`
- DoD
  - 单测通过；三文件存在且 schema 符合；同种子构建一致。

### ✅ 任务 A2：转移矩阵 tools.estimate_transitions（含采样语义/对手分布）
- 先写的测试
  - `tests/test_tools_transitions.py`
    - `test_transitions_row_stochastic()`：`flop→turn`、`turn→river` 行和≈1（±1e-6）。
    - `test_transitions_tv_distance_small_when_sample_increases()`：1e4 vs 2e4 样本的 TV 距离 < 0.05。
    - `test_transitions_meta_semantics_present()`：`meta` 含 `hero_range, villain_range, board_sampler, conditioners:{texture,spr_bin}`。
- 实现要点
  - CLI：`python -m tools.estimate_transitions --from flop --to turn --samples 200000 --out artifacts/transitions/flop_to_turn.json`
  - JSON 结构：`{ from_bins, to_bins, matrix: [[...]], meta:{ samples, hero_range, villain_range, board_sampler, conditioners:{texture,spr_bin} } }`
- 交付物
  - `artifacts/transitions/{flop_to_turn,turn_to_river}.json`
- DoD
  - 行归一化；TV 阈值通过；单测通过。

### ✅ 任务 A3：下注树生成 tools.build_tree（含最小 schema 与尺寸映射）
- 先写的测试
  - `tests/test_tools_tree_build.py`
    - `test_tree_build_generates_flat_json()`：产出 `artifacts/tree_flat.json`，包含节点数组与边引用。
    - `test_tree_is_2cap_validated()`：2‑cap 校验（每街最多 2 次再加注）。
  - `tests/test_size_map_consistency.py`
    - `test_size_tag_bounds()`：`configs/size_map.yaml` 中 `half:[0.45,0.55], pot:[0.95,1.05]` 等区间存在且有序；用于金额换算与解析回填。
- 实现要点
  - CLI：`python -m tools.build_tree --config configs/trees/hu_discrete_2cap.yaml --out artifacts/tree_flat.json`
  - 最小可运行 YAML（HU/2‑cap/尺寸标签对齐）。
  - 节点最小 schema（扁平）：`{ node_id, parent, street, role, facing, rcap, actions:[{name, size_tag}] }`。
  - 新增 `configs/size_map.yaml`：尺寸标签区间映射（例如 `half:[0.45,0.55], two_third:[0.65,0.72], pot:[0.95,1.05]`）。
  - 在 `configs/trees/hu_discrete_2cap.yaml` 顶部 `meta` 明确游戏假设：桌型 HU（SB vs BB）、前注/盲注单位、有效筹码分段（与 `spr_bins` 协调），以保证与 `rules/*`、`lookup/*`、转移矩阵键域一致。
  - 新增测试 `tests/test_tree_meta_fields.py::test_tree_meta_present_and_consistent()`：断言 `meta` 字段齐备且与 `configs/classifiers.yaml` 的 `spr_bins` 边界一致。
- 交付物
  - `configs/trees/hu_discrete_2cap.yaml`, `configs/size_map.yaml`, `artifacts/tree_flat.json`
- DoD
  - 结构/2‑cap 校验通过；单测通过。

### ✅ 任务 A4：Turn 叶子 EV 缓存 tools.cache_turn_leaf_ev
- 先写的测试
  - `tests/test_tools_ev_cache.py`
    - `test_turn_leaf_cache_npz_shapes()`：`turn_leaf.npz` 含必要数组（如 `ev`）且尺寸匹配 turn 桶；元信息包含 `derived_from_turn_leaf=true`。
    - `test_turn_leaf_cache_consistency_seeded()`：同种子两次构建一致。
- 实现要点
  - CLI：`python -m tools.cache_turn_leaf_ev --trans artifacts/transitions/turn_to_river.json --out artifacts/ev_cache/turn_leaf.npz --seed 42`
  - 采用近似河牌摊牌胜率；写入 npz；带元信息。
- 交付物
  - `artifacts/ev_cache/turn_leaf.npz`
- DoD
  - 形状/元信息正确；`meta` 至少包含：`derived_from_turn_leaf=true, board_sampler, hero_range, villain_range, conditioners:{texture,spr_bin}, samples, seed`；单测通过。
  - 新增测试 `tests/test_tools_ev_cache.py::test_turn_leaf_cache_meta_audit_fields()`：上述审计字段齐备。

---

### ✅ 任务 A5：离线流水线冒烟（A1→A4 一键校验）
- 先写的测试
  - `tests/test_tools_smoke_m1.py`
    - `test_smoke_runs_and_generates_report()`：调用 `-m tools.m1_smoke --quick --out reports/m1_smoke.md`，断言返回码为 0、报告文件存在且含“PASS”。
    - `test_smoke_validates_outputs_present()`：在空产物目录下运行，结束后断言生成以下文件存在：
      - `configs/buckets/{preflop,flop,turn}.json`
      - `artifacts/transitions/{flop_to_turn,turn_to_river}.json`
      - `configs/trees/hu_discrete_2cap.yaml`
      - `artifacts/tree_flat.json`
      - `artifacts/ev_cache/turn_leaf.npz`
- 实现要点
  - “新人一键入口/唯一入口”：`python -m tools.m1_smoke --out reports/m1_smoke.md [--quick] [--seed 42]`。
    - 串行触发 A1→A4，对入参使用较小样本与固定种子（如 `--samples 10000`）。
    - 自动创建缺失目录（`configs/`, `artifacts/`, `reports/`）。
    - 基础校验：
      - Buckets 三文件存在，含 `version,bins,features` 且数值符合入参（6/8/8）。
      - Transitions 行随机一致化（行和≈1），给出稀松 TV 概览（非强校验）。
      - Tree 为扁平结构并通过 2‑cap 校验。
      - EV 缓存包含 `ev` 数组且形状与 turn 桶一致，`meta.derived_from_turn_leaf=true`。
    - 报告页首打印 `PASS/FAIL` 总结 + 总耗时；追加每个产物的文件大小与生成耗时摘要（便于首检与回归对比）。
- 交付物
  - `reports/m1_smoke.md`
- DoD
  - 在全新环境下仅凭本命令可产出全部 A1–A4 产物并生成报告；报告首行含“PASS”。

### ✅ 任务 A6：HS/Potential 查表产物（供运行时快速查询）
- 先写的测试
  - `tests/test_lookup_tables.py`
    - `test_lookup_files_exist_and_shapes()`：生成 `artifacts/lookup/{hs_*,pot_*}.npz`，包含 `values` 与键域元信息（`meta:{street,texture,spr_bin,bucket}`）。
    - `test_lookup_api_present_and_fallback()`：`hs_lookup.get(street, texture, spr, bucket)` 存在；当 key 缺失时触发 `outs_to_river()` 兜底且返回有限值。
- 实现要点
  - CLI：
    - `python -m tools.build_lookup --type hs --streets preflop,flop,turn --out artifacts/lookup`
    - `python -m tools.build_lookup --type pot --streets flop,turn --out artifacts/lookup`
  - 运行时 API：`packages/poker_core/suggest/lookup.py` 提供 `hs_lookup.get(...) / pot_lookup.get(...)`，读取上述 NPZ；缺失键以简化 outs/EHS 近似兜底。
  - 兜底权重与容忍度：在 `packages/poker_core/suggest/outs_weights.yaml` 固化不同 outs 的质量加权与纹理修正（如：后门听牌折扣、同花/顺子 outs 质量差异），并提供 `fallback_tolerance: 0.12` 作为默认最大偏差阈值；`lookup.py` 读取并应用；返回值范围约束在 `[0,1]`。
- 交付物
  - `artifacts/lookup/{hs_preflop,hs_flop,hs_turn}.npz`, `artifacts/lookup/{pot_flop,pot_turn}.npz`
- DoD
  - 单测通过；API 与兜底稳定；与 A2/A3 的维度（texture/spr_bin/bucket）一致；兜底返回 EHS∈[0,1]；当同时可获得查表值与兜底估计时，二者偏差 ≤ `fallback_tolerance`（默认 0.12）。

---

## B. Runtime Suggest（规则路径 + 解释 + Fallback + Mix 基建）

### 任务 B1：规则路径端到端（元信息/解释）
- 先写的测试
  - `tests/test_service_meta_contract_m1.py`
    - `test_meta_contains_rule_path_and_size_tag()`：四街命中规则时 `meta.rule_path` 与 `meta.size_tag` 存在。
    - `test_explanations_render_frequency_when_present()`：存在 `meta.frequency` 时，解释文本出现频率口语化描述。
- 实现要点
  - `packages/poker_core/suggest/policy.py`：确保 flop/turn/river v1 路径填充 `meta.rule_path/size_tag/plan`。
  - `packages/poker_core/suggest/service.py` 已调用解释渲染器，无需改 UI 契约。
- 交付物
  - 新增测试；策略元信息完善。
- DoD
  - 测试通过；解释渲染含频率文本（当提供时）。

### ✅ 任务 B2：确定性混合策略（默认关闭）
- 先写的测试
  - `tests/test_mixing_determinism.py`
    - `test_stable_weighted_choice_deterministic()`：同 `seed_key/weights` 返回同一索引。
    - `test_distribution_approx_matches_weights()`：多 `seed_key` 抽样分布近似 `weights`。
    - `test_mixing_off_chooses_max_weight()`：`SUGGEST_MIXING=off` 时选择最大权重臂。
    - `test_meta_mix_and_frequency_emitted()`：`debug.meta.mix` 与 `meta.frequency` 正确填充。
- 实现要点
  - 在 `packages/poker_core/suggest/utils.py` 增加 `stable_weighted_choice(seed_key, weights) -> int`。
  - `policy.py` 支持规则节点 `mix: [{action,size_tag,weight}, ...]`：
    - `SUGGEST_MIXING=on` → 使用确定性掷签；`off` → 取最大权重。
    - `seed_key` 建议 `f"{obs.hand_id}:{node_key}"`；受 `SUGGEST_MIX_SEED=hand|session` 控制。
    - 输出 `debug.meta.mix` 与 `meta.frequency`。
- 交付物
  - `utils.stable_weighted_choice` 与策略接入；新增测试。
- DoD
  - 测试通过；默认关闭不影响 baseline。

### 任务 B3：保守回退（缺失节点/信息缺口）
- 先写的测试
  - `tests/test_fallback_minimal.py`
    - `test_missing_rule_triggers_fallback_and_code()`：缺规则时产出合法动作且 rationale 含 `CFG_FALLBACK_USED`。
    - `test_no_raise_in_fallback()`：回退不返回加注；面对大注偏向 `fold/check`。
    - `test_preflop_limp_threshold()`：SB 首入 `to_call ≤ 1bb` 时 `call` 且有解释码（已有路径）。
- 实现要点
  - 新增 `packages/poker_core/suggest/fallback.py`：`choose_conservative_line(obs, acts)`。
  - 策略/服务缺失节点或信息缺口时调用 fallback 并追加 `CFG_FALLBACK_USED`。
- 交付物
  - `fallback.py` 与接入；新增测试。
- DoD
  - 测试通过；无非法动作。

### 任务 B4：节点键 node_key_from_observation（统一离线/运行时）
- 先写的测试
  - `tests/test_node_key.py`
    - `test_node_key_components()`：包含 `pot_type/role/(ip|oop)/texture/spr/hand_class` 六要素。
    - `test_node_key_stable_for_same_obs()`：同 `Observation` 生成一致。
- 实现要点
  - 新增 `packages/poker_core/suggest/node_key.py`：`node_key_from_observation(obs) -> str`。
  - 策略命中时 `meta.node_key` 赋值；混合 `seed_key` 依赖该键。
  - 新增 `configs/classifiers.yaml`：明确 `texture` 判定规则与 `spr_bins` 离散边界，并写清边界语义：
    - `rounding: half_up`；`intervals: left_open_right_closed`（左开右闭）。
    - 示例：`spr_bins`: {(0,3], (3,5], (5,7], (7,9], (9, +inf)} → {2,4,6,8,10}；边界值 3/5/7/9 分别归入右侧区间。
    - `texture` 判定显式包含“相邻度/同花张数”阈值，避免实现歧义。
    在测试中断言稳定性与边界归属。
  - 新增测试 `tests/test_classifiers_stability.py`：对一组固定牌面与 SPR 输入，断言 `texture`/`spr_bin` 判定稳定且与阈值配置一致。
- 交付物
  - `node_key.py` 与接入；新增测试。
- DoD
  - 测试通过；响应包含 `meta.node_key`。

### 任务 B5：输出契约增强（不改 UI 契约）
- 先写的测试
  - `tests/test_service_meta_contract_m1.py`
    - `test_meta_fields_present()`：`meta.baseline="GTO" / meta.mode="GTO" / meta.node_key` 存在。
    - `test_debug_meta_contains_rule_path_and_mix()`：`debug.meta.rule_path` 与（mix 开启时）`debug.meta.mix` 存在。
- 实现要点
  - `packages/poker_core/suggest/service.py`：填充 `meta.baseline/mode/frequency/node_key`；保留结构化日志。
  - 预埋 M2 查表行 schema（不改现有 UI 字段）：未来策略表记录 `{node_key, mix:[{action,size_tag,weight}], meta:{...}}`，日志/调试字段口径保持不变，避免切换表驱动时漂移。
- 交付物
  - 服务层更新；新增测试。
- DoD
  - 测试通过；兼容既有测试。

### 任务 B6：River 最小规则组与解释口径（规则/启发式）
- 先写的测试
  - `tests/test_river_rules_minimal.py`
    - `test_value_threshold_and_blocker_logic()`：强成手（两对+/强顶对）在未受阻时可小注或过牌诱导；有关键阻断牌时更多过牌/跟注。
    - `test_weak_showdown_prefers_check_or_fold()`：弱摊牌优先过牌/弃牌；面对大注更趋向弃牌。
- 实现要点
  - `rules/river.yaml`：定义四档（强成手/中成手/弱摊牌/空气）的最小决策与阻断牌口径；与 `packages/poker_core/suggest/turn_river_rules.py` 读取口径一致。显式列举“关键阻断牌”集合（例如：同花坚果阻断=最高同花张；顺子坚果阻断=端张/间张关键牌；两对/三条对满堂红的阻断点等）。
  - C1 模板补河牌特定语句（见下）。
- 交付物
  - `rules/river.yaml`；新增测试。
- DoD
  - 单测通过；教学解释含河牌特定口径；在 `tests/test_river_rules_minimal.py` 中提供“有/无 blocker”对比用例，建议差异符合预期。

---

## C. Explanations & Codes（教学解释）

### 任务 C1：中文模板扩展（频率/混合/回退）
- 先写的测试
  - `tests/test_explanations_frequency_phrase.py`
    - `test_frequency_phrase_rendered()`：当 `meta.frequency=0.75` 渲染 “混合策略抽样（~75%）”。
- 实现要点
  - 更新 `packages/poker_core/suggest/config/explanations_zh.json` 增补频率/混合文案占位符（渲染器已支持）。
  - 新增河牌特定模板：强成手/阻断牌/弱摊牌的简短口径，以 `{facing_size_tag, blocker, value_tier}` 等占位符渲染。
- 交付物
  - 模板 JSON 更新；新增测试。
- DoD
  - 渲染测试通过；现有渲染测试不回归。

---

## D. Telemetry & Logging（观测）

### 任务 D1：结构化日志字段补全（与 Plan 指标清单对齐）
- 先写的测试
  - `tests/test_telemetry_logging_fields.py`
    - `test_log_contains_policy_and_rule_path()`：`caplog` 断言日志含 `policy_name, street, action, size_tag, rule_path`。
    - `test_log_mixing_and_fallback_counters()`：触发混合/回退时，记录对应字段（如 `mix.chosen_index, node_key, policy_source, mix_applied`）。
    - `test_log_price_and_units_present()`：日志含 `to_call_bb, pot_odds`（与服务层一致）。
- 实现要点
  - 复用 `packages/poker_core/suggest/service.py` 中 `log.info("suggest_v1", extra={...})`，补齐：`policy_source, mix.chosen_index, node_key`。
  - 对齐 Plan 的指标清单：确保 `to_call_bb, pot_odds`、`mix_applied(bool)` 出现在结构化日志（或 debug.meta）中。
- 交付物
  - 日志扩展；新增测试。
- DoD
  - 测试通过；字段齐备。

---

## E. Feature Flags（灰度与默认）

### 任务 E1：特性开关与默认值（统一文档口径：默认 off）
- 先写的测试
  - 复用 `tests/test_mixing_determinism.py::test_mixing_off_chooses_max_weight()` 覆盖默认关闭。
- 实现要点
  - 环境变量：`SUGGEST_MIXING=on|off`（默认 off），`SUGGEST_MIX_SEED=hand|session`（默认 hand）。
  - 仅 `SUGGEST_MIXING=on` 时注入 `meta.frequency` 与 `debug.meta.mix`。
  - 文档一致性：Plan 文档同步标注“默认 off”（在 PR 中一并修订）。
- 交付物
  - 环境变量读取与策略分支；复用上方测试。
- DoD
  - 行为满足开关；默认不改变 baseline。

---

## F. 性能基线（轻量门禁）

### 任务 F1：P95 轻量验收（慢测）
- 先写的测试
  - `tests/test_performance_p95_baseline.py`（标记 `@pytest.mark.slow`）
    - 固定种子生成 100 随机局面，端到端 `build_suggestion` 的 P95 ≤ 1s（或折算 500ms × 100 样本）。
- 实现要点
  - 生成可重放的轻量状态集；避免外部 IO；测例分层、数据量可配置。
  - 冷启动评估：首批样本前强制重新载入查表文件（NPZ/JSON），统计“冷启动 P95”与“热路径 P95”，并在报告中分别展示。
- 交付物
  - 慢测脚本。
- DoD
  - 本地通过；CI 可选择跳过或单独 job。

---

## G. Compare & Tune（老师-学生对照与自动调参 — 研究闭环，可选）

### 任务 G1：代表性局面集与老师打标
- 先写的测试
  - `tests/test_compare_tune_dataset.py`
    - `test_dataset_reproducible_with_seed()`：固定种子生成相同局面集。
- 实现要点
  - `tools.gen_cases --streets preflop,flop,turn --N 2000 --out artifacts/cases_m1.jsonl`。
  - 老师打标脚本 `tools.teacher_label --in artifacts/cases_m1.jsonl --out artifacts/labels_teacher.jsonl`（可用规则近似替代，后续接 LP/M2）。

### 任务 G2：对照评测与热力图
- 先写的测试
  - `tests/test_compare_metrics.py`
    - `test_metric_shapes_and_basic_ranges()`：Top-1 一致率、尺寸一致率、KL、ΔEV 基本范围正确。
- 实现要点
  - `tools.compare --cases artifacts/cases_m1.jsonl --labels artifacts/labels_teacher.jsonl --report reports/compare_m1.md --heatmap reports/compare_heatmap.png --thresholds configs/compare_thresholds.yaml`。
  - 验收线（可配置，默认）：Top‑1 ≥ 65%、尺寸一致率 ≥ 60%、ΔEV 中位数 ≥ 0；报告页首输出 PASS/FAIL 汇总。
  - 新增测试 `tests/test_compare_thresholds.py`：阈值可读入、默认值正确、报告包含 PASS/FAIL。

### 任务 G3：自动调参（可选）
- 实现要点
  - `tools.tune --space configs/tune_space.yaml --trials 100 --in rules/*.yaml --out rules.tuned.yaml`（Optuna/随机搜索任选）。
- DoD
  - 报告产出；参数回写规则文件；上述流程可全自动复跑。

---

## 产物与命令总览（M1）
- Buckets：`configs/buckets/{preflop,flop,turn}.json`
- Transitions：`artifacts/transitions/{flop_to_turn,turn_to_river}.json`
- Tree：`configs/trees/hu_discrete_2cap.yaml`、`configs/size_map.yaml` → `artifacts/tree_flat.json`
- Leaf EV Cache：`artifacts/ev_cache/turn_leaf.npz`
- Classifiers：`configs/classifiers.yaml`
- Lookup：`artifacts/lookup/{hs_*,pot_*}.npz`
- River Rules：`rules/river.yaml`
- Outs Weights：`packages/poker_core/suggest/outs_weights.yaml`
 - Compare Thresholds：`configs/compare_thresholds.yaml`

可运行命令（实现后）：
- `python -m tools.build_buckets --streets preflop,flop,turn --bins 6,8,8 --features strength,potential --out configs/buckets`
- `python -m tools.estimate_transitions --from flop --to turn --samples 200000 --out artifacts/transitions/flop_to_turn.json`
- `python -m tools.estimate_transitions --from turn --to river --samples 200000 --out artifacts/transitions/turn_to_river.json`
- `python -m tools.build_tree --config configs/trees/hu_discrete_2cap.yaml --out artifacts/tree_flat.json`
- `python -m tools.cache_turn_leaf_ev --trans artifacts/transitions/turn_to_river.json --out artifacts/ev_cache/turn_leaf.npz`
- `python -m tools.m1_smoke --out reports/m1_smoke.md --quick`
- `python -m tools.build_lookup --type hs --streets preflop,flop,turn --out artifacts/lookup`
- `python -m tools.build_lookup --type pot --streets flop,turn --out artifacts/lookup`

---

## 建议执行顺序
1) A1 → A2 → A3 → A4 → A5 → A6（离线产物 + 冒烟 + 查表）
2) B1 → B3 → B2 → B4 → B5（运行时策略/回退/混合/节点键/契约）
3) B6 → C1 → D1 → E1 → F1（河牌规则/解释/日志/开关/性能）
4) （可选）G1 → G2 → G3（研究闭环）

> 注：`policy_table.jsonl` 与 `policy_index.sqlite`（查表策略与混合）在 M2 实现；本文件在 M1 明确其行 schema（`{node_key, mix:[{action,size_tag,weight}], meta:{...}}`）与索引方案（SQLite offset 索引），以减少后续歧义。B5 的契约测试仅在“mix 存在时”断言 `meta.node_key / debug.meta.mix` 字段，不要求 M1 产出策略表文件。

> 备注：现有测试需保持通过；新增测试避免脆弱非确定性。产物文件与运行时口径在 docs 计划文档（`docs/GTO_suggest_feature_rebuild_plan.md`）中约定。
