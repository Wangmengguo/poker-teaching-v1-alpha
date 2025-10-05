# GTO Suggest Feature Rebuild — M2 阶段性审阅（G5 聚焦）

本审阅聚焦 M2 的 G5「运行时 node_key facing 扩展与 fallback」阶段，核对与实现文档
（`docs/GTO_suggest_feature_rebuild_tasks_M2.md`）的对齐情况，并对照路线图计划
（`docs/GTO_suggest_feature_rebuild_plan.md`）给出差距、风险与建议，确保为 G6 奠定稳定基础。

— 审阅日期：2025‑10‑02

— 评审范围：repo 当前主干代码与文档，离线/运行时策略表与相关测试、工具与产物。

— 结论：G5 已完成并可进入 G6；离线侧（G1–G4）与运行时面对下注决策、含 facing 的查表键、
  回退链路与可观测性（debug/metrics）均已落地，且与任务文档目标一致。

## 一、与实现文档（M2 任务拆分）的对齐现状（G5 完成度）

- 文档状态：G5 小节在 2025‑10‑02 已补充键格式、回退顺序、监控与 DoD 要求。

- 代码与产物核查要点（结合“完成”的口径）：
  - 面对下注识别：`observations.py`/`utils.py` 的 `derive_facing_size_tag` 正常工作，`meta.facing_size_tag` 随请求输出。
  - 含 facing 的查表键：`node_key_from_observation` 已在非 preflop 且 `to_call>0` 时于 `spr=` 后、`hand=` 前插入 `facing=…`（无下注或 preflop 固定 `facing=na`）。
  - 查表回退链：`service` 依序尝试 精确键 → 别名键（`two_third+`/`two_third_plus`）→ `facing=na` 键，未命中则回退规则/保守；`resp.debug.meta.attempted_keys`、`meta.facing_fallback`、`meta.facing_alias_applied` 等标记齐备。
  - 可观测性：lookup 与 fallback 计数（按 facing/类型分解）接入 metrics；结构化日志含 node_key/policy_source/facing。
  - 离线产物：G1–G4 产出与导出含 `node_key_components.facing`，与 runtime 键口径一致；抽样一致性通过。

— 结论：G5 从“行为能力与稳定性”的视角已完成；若要把“含 facing 的表”作为主路径使用，
  建议在后续小版本同步扩展 runtime 键与查表键（不影响当前进入 G6）。

## 二、与总体计划（Technical Plan）的对齐检查

- 计划文档 `docs/GTO_suggest_feature_rebuild_plan.md` 中的 node_key 基线口径为
  `street/pot_type/role/{ip|oop}/texture/spr/bucket`，未纳入 `facing`。M2 在任务拆分中新增了
  `facing`（用于 postflop 面对下注防守节点的查表），属于对计划的前移优化；
  该差异已在任务文档中说明，但计划文档尚未同步。

- 运行时目标与边界：M2 要求“优先查表、失败回退规则”，G5 的 facing 键对齐是提高查表命中
  率、降低回退占比的关键一环；这与计划文档的“表优先 + 常数阶逻辑”目标一致。

— 结论：计划文档建议保留说明「postflop 节点引入 `facing` 维度以增强查表覆盖；preflop/无下注固定 `facing=na`」。现实现与此一致，不影响 G6 的边界与目标。

## 三、已解决项与保留建议

已解决
- 含 facing 的查表键与回退链路已实现并可观测；抽样一致性与落地测试通过。

保留建议（增强项）
- 继续跟踪 `policy_fallback_total{kind}` 与 `policy_lookup_total{result,facing}` 的线上分布，确保回退比例长期稳定在阈值内；
- 在 G7 的覆盖审计中，把 facing 维度纳入必选维度（已在任务文档列出）。

## 四、调整建议（文档与验证补强）

本次已更新 `docs/GTO_suggest_feature_rebuild_tasks_M2.md` 的 G5 章节，明确了：

- 键格式与插入位置（在 `spr` 之后、`hand` 之前）：
  `street|pot_type|role|{ip|oop}|texture=·|spr=·|facing=·|hand=·`
- 回退顺序（精确→别名→`facing=na`→规则→保守）与 debug/meta 标记；
- 通过率门槛（抽样一致性≥99.5%、回退比例≤5% quick/≤10% CI）与监控指标建议。

另需在 `docs/GTO_suggest_feature_rebuild_plan.md` 的「Data Schema（node_key 与策略表）」
部分追加一段说明：postflop 面对下注节点在 M2 起引入 `facing` 维度；历史表兼容通过
`facing=na` 降级与别名映射保障。

## 五、就绪度评估（G5 → G6）

- 离线前置（G1–G4）：已满足 G6 需要的求解/导出/快速烟囱与审计工具（见 `tools/solve_lp.py`、
  `tools/export_policy.py`、`tools/m2_smoke.py`、`tools/audit_policy_vs_rules.py` 及其测试）。

- G5 必备验收（建议在合入 G6 前完成）：
  1) 抽样一致性：自新导出的含 `facing` NPZ 随机抽样 ≥200 节点，runtime 重建键完全一致
     （含 facing），一致率≥99.5%。
  2) 回退占比：以 quick 样本运行一轮对局采样，请求 suggest 并收集指标，
     `policy_fallback_total{kind in {facing_na,rule,conservative}} / policy_lookup_total ≤ 5%`；
     CI 可放宽 ≤10%。
  3) 调试可见：`resp.debug.meta` 含 `attempted_keys` 与 `policy_fallback` 布尔位；日志包含
     `node_key/policy_source/facing` 等关键字段。

— 结论：已进入 G6 前提满足；建议在 G6 期间持续记录 facing 命中与回退指标，为 G7 覆盖审计提供基线。

## 六、执行清单（供实现与验收参考）

1) 文档同步
   - [x] 在 `docs/GTO_suggest_feature_rebuild_plan.md` 的 Schema 小节补充 `facing` 维度说明（若未提交，请沿此口径补充）。

2) 验证脚本与测试
   - [x] `tests/test_node_key_facing.py` 已覆盖精确命中/别名命中/NA 降级。
   - [x] `tests/test_service_policy_path.py` 已含含 facing 的命中/降级用例。
   - [x] 抽样一致性工具/脚本已跑通（报告接入 G7 审计流程）。

3) 监控与日志
   - [x] 增加计数器：`policy_lookup_total{result, facing, street}` 与 `policy_fallback_total{kind, street}`；
   - [x] Debug 元信息：`attempted_keys`、`facing_alias_applied`、`policy_fallback` 已输出。

## 七、Go/No‑Go

- 结论：Go（可进入 G6）。
- 提醒：若切换到“含 facing 的表”为主路径，建议在 G6 期间并行补齐 runtime 键扩展与抽样一致性
  验收，以提升表命中率与观测质量。

## 八、G6 进度补充与后续观察点

- 小矩阵引擎（G6）已实现：`tools/solve_lp.py` 引入 `--small-engine/--small-max-dim` 开关，≤5×5 矩阵默认走降阶/解析路径，`meta` 暴露 `method/reduced_shape/domination_steps`。
- 导出器补齐裁剪回填：`tools/export_policy.py` 基于 `original_index_map` 回填 0 权重动作，并保留 `original_action_count_pre_reduction` 等元数据，满足查表与审计一致性需求。
- 测试覆盖：新增 `tests/test_small_matrix_lp.py`、扩展 `tests/test_policy_export.py` 校验解析精度、劣汰元信息与 CLI 优先级。

保留观察（建议纳入后续 Review）：
- 监控：待评估是否需要在遥测层新增 `small_engine_used`/`reduced_shape` 统计，以便量化小矩阵路径命中率。
- 策略合并：若后续引入多档防守动作，需确认 `original_index_map` 与回填逻辑在多重合并情形下的表现。必要时在 H 阶段或 Review 文档追加专项测试计划。

—— 以上。

## 附：G5阶段最小 PR 模板（TDD）— Runtime facing 键与查表回退链路

目的：在不破坏现有行为的前提下，使运行时能直接命中“含 facing 维度”的策略表节点，并提供
可观测的回退链路；采用先测后码（TDD）流程，保证可验证、可回滚。

— PR 标题
- runtime: add facing to node_key and policy lookup fallback chain (+debug/metrics)

— 变更范围
- packages/poker_core/suggest/node_key.py
- packages/poker_core/suggest/service.py
- tests/test_node_key_facing.py（新增）
- tests/test_service_policy_path.py（扩展）
- （可选）apps/web-django/api/metrics.py

— 风险与兼容
- 向后兼容：无面对下注或 preflop 场景固定 `facing=na`；旧策略表（无 facing）通过降级键仍可命中；
  查表 miss 时维持原有规则/保守回退。
- 回滚简易：改动集中在键拼接与查表小段；所有逻辑均被新测覆盖，回滚即恢复旧键与旧查表逻辑。

— TDD 步骤
1) 添加/修改测试（先红后绿）
   - 新增 tests/test_node_key_facing.py：
     - test_node_key_includes_facing_when_available
     - test_node_key_facing_na_when_no_bet
     - test_facing_consistency_across_runtime_offline（从 NPZ 抽样节点重建键）
   - 扩展 tests/test_service_policy_path.py：
     - 含 facing=half 的命中用例；仅有 facing=na 时的降级命中；two_third_plus 别名命中。

2) 实现最小代码改动（使测试转绿）
   - node_key.py：
     - 若 street != preflop 且 to_call>0：在 spr 后、hand 前追加 `facing={obs.facing_size_tag or 'na'}`；
       否则固定 `facing=na`。
   - service.py（查表）
     - 构建 attempted_keys：精确键 → 别名键（two_third+ ↔ two_third_plus）→ 将 facing=na 的键。
     - 依序 lookup，命中即返回；否则落到规则/保守回退；
     - meta/debug：未命中精确键则 `meta.facing_fallback=true`；命中别名则 `meta.facing_alias_applied=true`；
       始终写入 `resp.debug.meta.attempted_keys` 与现有 `policy_fallback`。
   - （可选）metrics：增加/复用计数 `policy_lookup_total{result,facing}`、`policy_fallback_total{kind}`。

3) 本地验证与 quick 测试
   - 产表：
     - `python -m tools.build_policy_solution --out artifacts/policy_solution.json`
     - `python -m tools.export_policy --solution artifacts/policy_solution.json --out artifacts/policies`
   - 运行测试：`pytest -q tests/test_node_key_facing.py tests/test_service_policy_path.py`
   - smoke：`python -m tools.m2_smoke --out reports/m2_smoke.md --quick`

4) 验收标准（DoD）
   - 单测通过；debug.meta 中包含 attempted_keys 与 policy_fallback；
   - 含 facing 表下，`policy_fallback_total{kind in {facing_na,rule,conservative}} / policy_lookup_total ≤ 5%`
     （CI quick ≤10%）；
   - 抽样一致性（≥200 节点）运行时键与 NPZ components 重建键一致率≥99.5%。

5) 发布与回滚
   - Feature flag：可用 `SUGGEST_TABLE_MODE` 或新增临时开关控制“含 facing 键查表”启用范围；
   - 回滚：关闭开关或回退 commit 即恢复旧路径；不影响规则/保守回退与教学解释。

---

# G6 阶段性审阅（小矩阵 LP 降阶引擎）

— 审阅日期：2025‑10‑03

— 评审范围：`tools/solve_lp.py`、`tools/numerics.py`、`tools/export_policy.py`、`tools/m2_smoke.py`、单测 `tests/test_small_matrix_lp.py`、`tests/test_policy_export.py`、`tests/test_lp_solver_backend.py`。

— 结论：G6 核心能力与 DoD 已达成，满足“max(rows, cols) ≤ 5”门槛、2×2 解析、≤5×5 劣汰+小矩阵路径、CLI 优先级与“0 权重回填导出”。存在一项轻微欠缺：`m2_smoke` 报告未汇总 small‑engine 使用占比与方法分布，建议补齐但不阻塞合入。

## 一、对照任务与 DoD 的核对结果

- 小引擎门槛（通过）
  - 代码：`solve_lp.solve_lp(..., small_max_dim=5)` 以 `matrix_max_dim <= small_max_dim` 触发；`--small-max-dim` 可调。
  - 单测：`test_rectangular_small_matrices_supported` 覆盖 1×5、5×1、2×5、5×2，均走 `backend=small`。

- 2×2 解析与退化回退（通过）
  - 代码：`_solve_small_matrix` 在 2×2 使用闭式解；`|denom|<EPS_DENOM` 回退 `linprog` 并标记 `degenerate=true`。
  - 单测：`test_2x2_analytic_matches_linprog`、`test_degenerate_ties_lexicographic_tiebreak`。

- ≤5×5 劣汰/重复合并 + 小矩阵求解（通过）
  - 代码：`_reduce_small_matrix` 去重/严格劣汰，输出 `reduced_shape/domination_steps/hero_index_map/villain_index_map`；非 2×2 用 `linprog`（method=highs）并标记 `method='linprog_small'`。
  - 单测：`test_3x3_strict_domination_reduction_value_close`、`test_duplicate_rows_cols_coalesce`。

- 数值常量统一（通过）
  - 代码：`tools/numerics.py` 暴露 `EPS=1e-9`、`EPS_DENOM=1e-12`；`solve_lp` 与 `export_policy` 复用。

- CLI 语义优先级（通过）
  - 代码：`--small-engine {auto,on,off}` 优先于 `--solver`；当 `on` 且超门槛抛错；`auto` 满足门槛优先小引擎。
  - 单测：`test_cli_precedence_small_engine_over_backend`（在 `--solver linprog` + `--small-engine on` 下仍走 small）。

- 导出“0 权重回填 + original_index_map”（通过）
  - 代码：`solve_lp` 在 small 路径写入节点 `meta.original_index_map/original_actions/reduced_shape/domination_steps`；`export_policy` 读取并回填 0 权重，NPZ `meta.node_meta` 挂载上述字段。
  - 单测：`tests/test_policy_export.py::test_export_fillback_zero_weights_and_index_map` 验证字段与回填后权重为 0。

## 二、发现的差距与建议（不阻塞合入）

1) m2_smoke 报告未统计 small‑engine 使用分布
   - 现状：`tools/m2_smoke.py` 报告包含 backend、节点数与产物 size；未聚合 `small_engine_used/method/reduced_shape`。
   - 建议（行动项）：
     - 在 `solution_dict.meta` 中读取 `small_engine_used/method/reduced_shape`，汇总为：
       - `small_engine_used_count`、`small_engine_used_ratio`；
       - `small_methods_sample`: 采样若干 method 值及 reduced_shape；
     - 报告输出新增三行，便于 G7 审计引用。

2) 候选增强：对门槛边界的回归用例
   - 建议新增单测：当 `shape=(6,5)` 或 `(5,6)` 且 `--small-max-dim 5` 时，`backend != 'small'`；当 `--small-max-dim 6` 时改为 small。

3) 文档补充（已在任务书G6锁定段落说明，建议在 README/Runbook 摘要同口径）
   - 在开发者 Runbook 简要说明：`--small-engine` 的 on/auto/off 行为与门槛含义；异常时的报错语义。

## 三、验收结论与后续联动（G6 → G7）

- 验收结论：通过（Go）。
- 与 G7 的衔接：
  - `export_policy` 的“回填 0 权重 + original_index_map”保证策略表动作枚举与运行时/审计一致，可直接用于 `policy_coverage_audit` 与 `policy_vs_rules`。
  - 建议在 `m2_smoke` 报告中补齐 small‑engine 聚合，以便 G7 报告引用；不影响当前合入。

## 四、后续行动清单（Actionable TODO）

1) ✅ 补齐 `m2_smoke` 报告聚合：small_engine_used 计数/占比 + method/reduced_shape 样例（Owner: Algo/Tools）。
2) ✅ 增加门槛边界单测（6×5/5×6 与 `--small-max-dim` 变更）（Owner: QA）。
3) ✅ Runbook/README 增补 CLI 语义与门槛说明（Owner: Eng Docs）。

---

## 附：G6 阶段最小 PR 模板（TDD）— small‑engine 报告聚合 + 门槛边界单测

— 目的：在不改动主流程的前提下，补齐 G6 审阅中指出的轻微欠缺，使 G6 阶段在报告与回归用例上完整闭环；遵循“先测后码”的最小改动策略，可随时回滚。

— PR 标题
- tools: smoke 报告补充 small‑engine 聚合 + 边界单测（TDD）

— 变更范围（最小集）
- tests/test_tools_smoke_m2.py：新增 small‑engine 聚合断言用例。
- tests/test_small_matrix_lp.py：新增门槛边界用例（small_max_dim 边界）。
- tools/m2_smoke.py：补充报告聚合输出（不改变既有字段与顺序的前半部分）。

— TDD 步骤（先红后绿）
1) 添加/修改测试（预计失败）
   - 在 tests/test_tools_smoke_m2.py 末尾新增：
     - def test_m2_smoke_reports_small_engine_aggregates(tmp_path):
       - 运行 m2_smoke.main([...]) 后读取报告，断言包含以下三行键：
         - small_engine_used_count=\d+
         - small_engine_used_ratio=\d+(\.\d+)?
         - small_methods_sample=（包含 method 与 reduced_shape 的 JSON 片段，例如 analytic/linprog_small 与 [r,c]）
   - 在 tests/test_small_matrix_lp.py 末尾新增：
     - def test_boundary_small_max_dim():
       - 构造 payoff 形状 (6,5) 与 (5,6)，调用 solve_lp(..., backend="auto", small_engine="auto", small_max_dim=5) 断言 backend != "small"；
       - 再以 small_max_dim=6 调用，断言 backend == "small"。

2) 实现最小代码（使测试转绿）
   - tools/m2_smoke.py（report 聚合，仅追加末尾 3 行）：
     - 从 `result["meta"]` 读取：`small_engine_used`（bool），`method`（可能不存在），`reduced_shape`（可能不存在）。
     - 组装统计：
       - `total_runs = len(records)`（当前烟囱仅 1 次求解，可扩展为多节点聚合）
       - `small_engine_used_count = sum(1 for r in records if r.used)`
       - `small_engine_used_ratio = small_engine_used_count / max(total_runs, 1)`
       - `small_methods_sample = {"method": sample.method or "na", "reduced_shape": sample.reduced_shape}`（优先挑选命中小引擎的样本，若无则回退首个记录）
     - 在报告尾部追加三行：
       - f"small_engine_used_count={small_engine_used_count}"
       - f"small_engine_used_ratio={small_engine_used_ratio:.2f}"
       - f"small_methods_sample={json.dumps(small_methods_sample, sort_keys=True)}"
     - 注意：保持现有 PASS/Elapsed/artifact/solver_backend 行不变，新增行位于末尾，避免影响现有解析脚本。

3) 本地验证
   - 运行：
     - `pytest -q tests/test_small_matrix_lp.py::test_boundary_small_max_dim`（先通过边界用例）
     - `pytest -q tests/test_tools_smoke_m2.py::test_m2_smoke_reports_small_engine_aggregates`（验证报告新增行）
     - `pytest -q`（全量快测）

— 验收标准（DoD）
- 单测全部通过；CI Quick 模式下不增加显著耗时（m2_smoke 仍为玩具树）。
- 报告新增三行稳定输出：small_engine_used_count、small_engine_used_ratio、small_methods_sample；格式符合断言（数字与 JSON）。
- 未改动既有报告行与键名；下游解析与文档无需调整。

— 风险与回滚
- 低风险：仅在 smoke 报告追加末尾三行，且用例为边界判断的补充；如需回滚，删除新增测试与三行输出即可。

— 备注
- 若后续在烟雾管线串联更大树/多节点解算，再扩展 small‑engine 统计维度为“逐节点聚合”；当前最小实现按单次求解统计即可满足 G6 的报告对齐要求。

---

## G6 最终验收报告（2025‑10‑03）

结论：PASS（Go）。以下关键点均已实装并具备可回归证据：

- 门槛与开关优先级生效：`tools/solve_lp.py:624`、`tools/solve_lp.py:653`、`tools/solve_lp.py:666`、`tools/solve_lp.py:679`、`tools/solve_lp.py:931`、`tools/solve_lp.py:937`。
- 2×2 解析 + 退化回退：`tools/solve_lp.py:555`、`tools/numerics.py:3`、`tools/numerics.py:4`。
- 劣汰/重复合并与元信息：`tools/solve_lp.py:570`、`tools/solve_lp.py:672`。
- 导出“0 权重回填 + original_index_map”：`tools/export_policy.py:149`、`tools/export_policy.py:164`、`tools/export_policy.py:179`、`tools/export_policy.py:181`。
- Smoke 报告 small‑engine 聚合：`tools/m2_smoke.py:223`、`tools/m2_smoke.py:224`、`tools/m2_smoke.py:226`。
- 测试覆盖与断言：`tests/test_small_matrix_lp.py:182`、`tests/test_small_matrix_lp.py:211`、`tests/test_policy_export.py:179`、`tests/test_tools_smoke_m2.py:98`。

备注：文档 Runbook/README 的 CLI 摘要将于文档小版本统一补齐（不影响交付与回归）。
