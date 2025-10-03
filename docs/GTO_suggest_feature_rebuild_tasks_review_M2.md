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
