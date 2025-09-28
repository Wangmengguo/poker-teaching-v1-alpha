## GTO Suggest Feature Rebuild — M2 任务拆分（TDD 先行）

本章节对应 Roadmap 中的 M2（Week 3–4），主要目标：离线 LP 求解产物、策略表导出、运行时查表接入、基线评测（≥ +20~30 BB/100，95% CI>0），并补齐教学口语化频率。各任务遵循“先写测试”→“实现要点”→“交付物”→“验收标准（DoD）”的结构，便于敏捷迭代与跟踪。

---

### G. LP 求解 & 策略表产出（离线）

#### 任务 G1：LP 求解器模块化封装（HiGHS/linprog 双后端）
- 先写的测试
  - `tests/test_lp_solver_backend.py`
    - `test_highs_solver_solves_toy_tree()`：提供玩具 2 节点树与约束，断言 HiGHS 后端返回可行策略、收益与对偶价格。
    - `test_linprog_fallback_when_highs_missing()`：模拟 HiGHS ImportError，断言自动回退到 SciPy `linprog` 且结果与基准差异 ≤ 1e-6。
    - `test_invalid_inputs_raise_diagnostic_error()`：传入负概率或约束不一致时抛出自定义 `LPSolverError`，错误消息包含问题摘要。
- 实现要点
  - 新建 `tools/lp_solver.py`：封装 `solve_lp(tree, buckets, transitions, leaf_ev, backend="highs")`，内部可切换 HiGHS 或 `linprog`。
  - 错误链路记录缺依赖、矩阵奇异、约束不闭合，统一转为 `LPSolverError`。
  - 支持 `seed` 控制打乱顺序，保证重复运行稳定；允许 `--backend auto` 根据依赖可用性选择实现。
- 交付物
  - `tools/lp_solver.py` + 对应测试。
- DoD
  - 测试通过；两种后端均可运行玩具树；异常路径提供明确错误信息；CI 无 HiGHS 时自动回退。

#### 任务 G2：策略表导出工具 `tools.export_policy`
- 先写的测试
  - `tests/test_policy_export.py`
    - `test_export_policy_writes_npz_and_metadata()`：调用工具后生成 `artifacts/policies/{preflop,postflop}.npz`，文件内含 `actions, weights, meta`。
    - `test_policy_export_respects_node_key_schema()`：抽样若干节点，断言 `meta.node_key_components` 覆盖 street/pot_type/role/pos/texture/spr/bucket，与 `node_key` 一致。
    - `test_policy_export_handles_zero_weight_actions()`：包含 0 权重臂时仍保留记录并在 `meta.zero_weight_actions` 标记，确保导出稳定。
- 实现要点
  - 读取 `tools.lp_solver` 产出的策略向量，结合树结构序列化为离线查表格式。
  - 输出 NPZ 主格式 + 可选 `--debug-jsonl` 抽样文件；meta 记录源配置 hash、solver backend、生成时间、seed、版本号。
  - 支持 `--compress` 与分片参数控制单文件大小；保持 deterministic 排序便于 diff。
- 交付物
  - `tools/export_policy.py`（或模块化函数）+ 产物目录。
- DoD
  - 测试通过；NPZ 文件含所需数组；meta 字段齐备；调试 JSONL 可选输出；重复运行产出一致。

#### 任务 G3：离线流水线集成命令 `tools.m2_smoke`
- 先写的测试
  - `tests/test_tools_smoke_m2.py`
    - `test_m2_smoke_generates_all_artifacts()`：在空产物目录运行 `python -m tools.m2_smoke --quick --out reports/m2_smoke.md`，断言生成策略表、LP 日志、评测样例。
    - `test_m2_smoke_reports_pass_summary()`：报告首行包含 `PASS`，并记录策略文件大小、solver backend。
    - `test_m2_smoke_handles_partial_artifacts()`：预置部分旧产物，断言重新生成时会备份或覆盖，并在报告中注明 `reused=true|false`。
- 实现要点
  - 串联 A1–A6 产物 + G1/G2；产物存在时提供 `--force` 与 `--reuse` 选项。
  - 报告包含产物路径、生成耗时、文件 hash、采样参数摘要；失败时落 ERROR 表格供排查。
  - 支持 `--quick` 降采样；默认使用 HiGHS，捕获失败回退 `linprog` 并在报告中注明。
- 交付物
  - `tools/m2_smoke.py`、`reports/m2_smoke.md` 模板。
- DoD
  - 测试通过；在干净目录下一键生成全部 M2 离线产物并产出报告；报告首行 `PASS`。

---

### H. 运行时策略查表接入（优先查表、失败回退）

#### 任务 H1：策略 NPZ 读取与缓存层
- 先写的测试
  - `tests/test_policy_loader.py`
    - `test_loader_reads_npz_and_normalizes_weights()`：加载策略文件后，断言每个节点权重归一化、包含动作与 `size_tag`。
    - `test_loader_handles_missing_node()`：请求不存在的 `node_key` 时返回 `None`，并触发 metrics/log。
    - `test_loader_refresh_on_file_change()`：模拟热更新（修改 mtime），断言缓存失效并重新加载。
- 实现要点
  - 新建 `packages/poker_core/suggest/policy_loader.py`：懒加载 NPZ，提供 `lookup(node_key)`；支持内存映射或分片。
  - 记录 `meta.version`、`policy_hash`；加入命中率/加载耗时/错误计数 metrics。
  - 提供 `warmup()` 钩子用于性能测试冷启动；确保线程安全。
- 交付物
  - `policy_loader.py` 与相关配置。
- DoD
  - 测试通过；缓存命中正常；热更新生效；错误日志友好。

#### 任务 H2：service 查表主路径（含回退）
- 先写的测试
  - `tests/test_service_policy_path.py`
    - `test_policy_hit_returns_table_action()`：策略表存在节点时，`service.suggest` 返回查表动作与频率。
    - `test_policy_miss_falls_back_to_rules()`：策略缺失时调用既有规则 fallback，并在 `debug.meta` 标记 `policy_fallback=true`。
    - `test_policy_weight_edge_cases()`：当策略表包含多个权重相近臂或全 0 时，确保最终动作合法且解释注明兜底策略。
- 实现要点
  - 在 `packages/poker_core/suggest/service.py` 中优先查表；缺失或异常时回退到 B 线规则。
  - `meta` 补充 `source=policy|rule`、`policy_version`、`node_key`；与混合开关兼容。
  - 结构化日志记录命中率、fallback 次数；确保错误不影响主流程。
- 交付物
  - service 主路径改造；新增测试。
- DoD
  - 测试通过；查表路径输出合法；日志含命中率统计。

#### 任务 H3：策略/规则一致性审计工具
 - 先写的测试
   - `tests/test_policy_rule_audit.py`
     - `test_policy_vs_rule_diff_report()`：对固定节点集合运行审计，生成报告列出策略与规则差异（动作、尺寸、频率），断言文件存在。
     - `test_audit_handles_missing_policy_entries()`：缺少节点时标记为 `missing` 而非异常退出。
     - `test_audit_cli_returns_nonzero_on_threshold_exceed()`：当差异超过阈值（如 30%）时命令返回码 ≠0。
 - 实现要点
   - 开发 `python -m tools.audit_policy_vs_rules --policy artifacts/policies --rules configs/rules`。
   - 报告输出 Markdown/CSV，包含总览、Top N 差异节点、建议；阈值与节点过滤可配置。
 - 交付物
   - 审计工具及报告模板。
 - DoD
   - 测试通过；报告覆盖差异；阈值可配置；CI 可运行 quick 版本。

#### 任务 H4：node_key 与桶映射一致性补齐
- 先写的测试
  - `tests/test_node_key_policy_bucket.py`
    - `test_node_key_uses_bucket_id_when_available()`：构造带 `bucket_id` 的 Observation，断言导出的 node_key 中 `bucket` 段为整数 id。
    - `test_node_key_meta_includes_bucket_mapping()`：策略查表命中时 `meta.node_key_components` 暴露 `bucket_id` 与 `hand_class` 的映射，便于离线/运行时审计。
    - `test_missing_bucket_logs_warning()`：当 Observation 无桶信息时记录结构化日志并标记 `meta.bucket_source=hand_class`。
- 实现要点
  - 扩展 `packages/poker_core/suggest/node_key.py` 支持优先读取 `bucket_id`（或 `bucket`）并仅在缺失时回退到 `hand_class`。
  - 在 `packages/poker_core/suggest/service.py` 与策略加载层注入 `meta.node_key_components`，记录 `bucket_id`、`hand_class`、`texture` 等字段。
  - 文档更新：在计划/README 中说明桶 id 的来源与回退策略，保证离线策略表与运行时键完全一致。
- 交付物
  - node_key 补齐实现、策略元信息扩展、对应测试。
- DoD
  - 测试通过；策略查表键与离线桶映射对齐；缺失桶信息路径有日志与降级说明。

---

### I. 评测与基线验证

#### 任务 I1：端到端性能基线测试（P95 ≤ 1s）
- 先写的测试
  - `tests/test_performance_p95_m2.py`
    - `test_build_suggestion_policy_p95()`：固定种子生成 1k 局面，端到端建议的 P95 ≤ 1s（热路径）。
    - `test_cold_start_policy_reload()`：强制重载策略文件后首次请求的 P95 统计，并在报告中输出冷/热对比。
    - `test_profiled_metrics_exported()`：运行测试后生成 `reports/perf_policy.json`，包含命中率、加载耗时、缓存情况。
- 实现要点
  - 扩展现有性能框架，记录冷启动强制重载流程；统计写入 JSON/Markdown 供持续监控。
  - 支持可配置样本数、超时时间；默认 1k 局面，可在 CI 中降级为 200 局面。
- 交付物
  - 新增性能测试与报告模板。
- DoD
  - 测试通过；P95 满足要求；报告存档于 `reports/`。

#### 任务 I2：胜率评测（≥ +20~30 BB/100，95% CI>0）
- 先写的测试
  - `tests/test_eval_baseline_policy.py`
    - `test_eval_runs_and_outputs_report()`：调用 `python -m tools.eval_baselines --policy artifacts/policies --hands 200000 --out reports/eval_m2.md`，断言报告存在且包含 `BB/100` 指标。
    - `test_eval_confidence_interval_positive()`：解析报告，断言 95% CI 下界 >0；不满足则测试失败并给出调试提示。
    - `test_eval_reproducible_with_seed()`：相同 seed 下结果一致（差异 ≤ 0.5 BB/100）。
- 实现要点
  - 扩展评测脚本：支持多对手、固定随机种子、CI 快速模式（如 50k 手）。
  - 报告结构化输出 Markdown + JSON（含原始指标），便于可视化与回归。
- 交付物
  - 评测脚本增强，报告入库。
- DoD
  - 测试通过；正式评测满足目标；quick 模式用于 CI。

#### 任务 I3：教学解释与频率口语化增强
- 先写的测试
  - `tests/test_explanations_policy_frequency.py`
    - `test_explanation_renders_policy_frequency()`：查表命中时，解释模板包含频率语句（如 “80% 下注，20% 过牌”）。
    - `test_explanation_handles_missing_frequency()`：策略缺频率数据时回退到规则口径且不报错。
    - `test_explanation_handles_exploit_tips_opt_in()`：启用 exploit 提示开关时与频率文本兼容，避免重复文案。
- 实现要点
  - 更新解释模板与渲染逻辑，从 `meta.frequency` 生成自然语言描述；单臂输出确定语句，多臂按降序描述并限制臂数（如 Top‑3）。
  - 补充测试样例覆盖 0/1/多臂、非数字频率、缺失字段、UTF‑8 字符等边界情况。
- 交付物
  - 模板与服务层更新；新增测试。
- DoD
  - 测试通过；解释输出稳定；CI 快速校验通过。

---

### J. 运维与监控

#### 任务 J1：策略文件版本化与灰度开关
- 先写的测试
  - `tests/test_policy_versioning.py`
    - `test_policy_version_hash_exposed()`：加载策略后，在 `meta.policy_version` 暴露文件 hash 与生成时间。
    - `test_runtime_switch_between_versions()`：模拟两个策略版本，切换配置后服务返回对应版本并记录日志。
    - `test_invalid_version_falls_back_with_alert()`：请求不存在的版本时回退到默认策略并触发告警事件。
- 实现要点
  - 新增 `configs/policy_manifest.yaml` 维护版本列表、灰度比例、fallback 规则；支持 `SUGGEST_POLICY_VERSION=auto|vX`。
  - 服务层读取 manifest，按用户/手牌可选灰度策略；记录版本切换日志。
- 交付物
  - manifest 配置、服务更新、测试。
- DoD
  - 测试通过；灰度开关可控；告警路径可追踪。

#### 任务 J2：运行监控指标与日志增强
- 先写的测试
  - `tests/test_monitoring_metrics.py`
    - `test_policy_metrics_emitted()`：调用建议后，metrics 客户端记录 `policy_hit_rate`, `policy_load_time_ms`, `fallback_count`。
    - `test_error_metrics_on_exception()`：模拟加载失败，断言错误指标与结构化日志包含 `node_key`、`policy_version` 等信息。
    - `test_metrics_flush_hook_called()`：测试钩子确保请求结束时 flush 成功；若未 flush，测试失败。
- 实现要点
  - 扩展 metrics 客户端（可为 mockable 接口），默认写入日志；生产接入 Prometheus/OpenTelemetry 兼容格式。
  - 日志标准化字段：`node_key`, `policy_source`, `latency_ms`, `fallback_used`；异常路径附带堆栈摘要。
  - 追加 `fallback_hit_rate`、`lookup_fallback_rate` 与 `fallback_tolerance` 检查（超阈值时触发 WARNING），并在性能/评测报告中输出统计。
- 交付物
  - metrics 模块增强、测试、文档。
- DoD
  - 测试通过；日志/指标字段齐备；CI 可在 mock 环境验证；fallback 命中率监控上线且超阈值有告警。
#### 任务 J3：Fallback 行为安全网
- 先写的测试
  - `tests/test_fallback_safety_net.py`
    - `test_fallback_prefers_passive_actions_when_available()`：当存在 check/call/fold 时，确保不会返回 bet/raise。
    - `test_fallback_aggressive_last_resort_logs_warning()`：仅剩激进行动时返回最小尺寸并记录 `fallback_aggressive=true` 警告。
    - `test_fallback_clamps_minimum_size()`：当只剩 bet/raise，金额被钳制在合法最小值并在 `meta` 中暴露。
- 实现要点
  - 更新 `packages/poker_core/suggest/fallback.py`：在只剩激进行动时选择最小尺寸（或最小可加注），并写入告警日志/metrics。
  - 在服务层为触发 aggressive fallback 的请求打标签，方便离线审计；与性能/监控任务联动。
  - 文档记录该降级路径与预期频率，便于策略表覆盖不足时复现。
- 交付物
  - fallback 安全网实现、日志/metrics 扩展、测试。
- DoD
  - 测试通过；默认情况下 fallback 仅返回被动动作；激进兜底路径带告警与钳制信息。
---
## K. Compare & Tune（老师-学生对照与自动调参 — 研究闭环，可选）
### 任务 K1：代表性局面集与老师打标
- 先写的测试
  - `tests/test_compare_tune_dataset.py`
    - `test_dataset_reproducible_with_seed()`：固定种子生成相同局面集。
- 实现要点
  - `tools.gen_cases --streets preflop,flop,turn --N 2000 --out artifacts/cases_m1.jsonl`。
  - 老师打标脚本 `tools.teacher_label --in artifacts/cases_m1.jsonl --out artifacts/labels_teacher.jsonl`（可用规则近似替代，后续接 LP/M2）。
### 任务 K2：对照评测与热力图
- 先写的测试
  - `tests/test_compare_metrics.py`
    - `test_metric_shapes_and_basic_ranges()`：Top-1 一致率、尺寸一致率、KL、ΔEV 基本范围正确。
- 实现要点
  - `tools.compare --cases artifacts/cases_m1.jsonl --labels artifacts/labels_teacher.jsonl --report reports/compare_m1.md --heatmap reports/compare_heatmap.png --thresholds configs/compare_thresholds.yaml`。
  - 验收线（可配置，默认）：Top‑1 ≥ 65%、尺寸一致率 ≥ 60%、ΔEV 中位数 ≥ 0；报告页首输出 PASS/FAIL 汇总。
  - 新增测试 `tests/test_compare_thresholds.py`：阈值可读入、默认值正确、报告包含 PASS/FAIL。
### 任务 K3：自动调参（可选）
- 实现要点
  - `tools.tune --space configs/tune_space.yaml --trials 100 --in rules/*.yaml --out rules.tuned.yaml`（Optuna/随机搜索任选）。
- DoD
  - 报告产出；参数回写规则文件；上述流程可全自动复跑。
---
## 产物与命令总览（M2）
- LP 求解器封装：`tools/lp_solver.py`（HiGHS/linprog 双后端）。
- 策略导出产物：`artifacts/policies/{preflop,postflop}.npz`、`reports/m2_smoke.md`。
- 运行时查表模块：`packages/poker_core/suggest/policy_loader.py`、`packages/poker_core/suggest/service.py`（查表主路径）。
- 审计/评测报告：`reports/compare_m1.md`、`reports/compare_heatmap.png`、`reports/perf_policy.json`、`reports/eval_m2.md`。
- 配置与阈值：`configs/policy_manifest.yaml`、`configs/compare_thresholds.yaml`、`configs/tune_space.yaml`、`rules.tuned.yaml`。
- 数据集与标签：`artifacts/cases_m1.jsonl`、`artifacts/labels_teacher.jsonl`。
可运行命令（实现后）：
- `python -m tools.lp_solver --tree artifacts/tree_flat.json --backend auto --out artifacts/lp_solution.npz`
- `python -m tools.export_policy --solution artifacts/lp_solution.npz --out artifacts/policies --debug-jsonl artifacts/policy_sample.jsonl`
- `python -m tools.m2_smoke --out reports/m2_smoke.md --quick`
- `python -m tools.gen_cases --streets preflop,flop,turn --N 2000 --out artifacts/cases_m1.jsonl`
- `python -m tools.teacher_label --in artifacts/cases_m1.jsonl --out artifacts/labels_teacher.jsonl`
- `python -m tools.compare --cases artifacts/cases_m1.jsonl --labels artifacts/labels_teacher.jsonl --report reports/compare_m1.md --heatmap reports/compare_heatmap.png`
- `python -m tools.tune --space configs/tune_space.yaml --trials 100 --in rules --out rules.tuned.yaml`
- `python -m tools.audit_policy_vs_rules --policy artifacts/policies --rules configs/rules --out reports/policy_rule_audit.md`
- `python -m tools.eval_baselines --policy artifacts/policies --hands 200000 --out reports/eval_m2.md`
---
## 建议执行顺序
1) G1 → G2 → G3（LP 求解与策略表产出流水线）。
2) H1 → H2 → H3（运行时查表接入与审计工具）。
3) I1 → I2 → I3（性能与胜率评测、教学解释增强）。
4) J1 → J2（策略版本化与监控运维）。
5) （可选研究）Compare & Tune：任务 K1 → K2 → K3（老师-学生对照与自动调参）。