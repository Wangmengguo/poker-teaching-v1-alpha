## GTO Suggest Feature Rebuild — M2 任务拆分（TDD 先行）

本章节对应 Roadmap 中的 M2（Week 3–4），主要目标：离线 LP 求解产物、策略表导出、运行时查表接入、基线评测（≥ +20~30 BB/100，95% CI>0），并补齐教学口语化频率。各任务遵循“先写测试”→“实现要点”→“交付物”→“验收标准（DoD）”的结构，便于敏捷迭代与跟踪。

> 注：本阶段同时承接《GTO_suggest_feature_M1_review.md》中的风险项（依赖缺失、性能基准、极端规则覆盖、查表偏差监控），并将 Compare & Tune（老师-学生对照与自动调参）整体后置至此阶段统一交付。

---

### G. LP 求解 & 策略表产出（离线）

#### ✅ 任务 G1：LP 求解器模块化封装（HiGHS/linprog 双后端）
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
- 难度评估：系数 4/5（双后端兼容 + 错误链路统一 + 随机性控制，需要较强的数值稳定性经验）。
- 易错点排雷
  - HiGHS/linprog 数值容差不同，需写入一致性断言并在测试中设置合理公差，避免 CI 偶发失败。
  - `LPSolverError` 报错上下文要保留原始异常信息，否则排查困难。
  - `seed` 控制必须贯穿求解与随机化顺序，否则复现度不达标。
- DoD
  - 测试通过；两种后端均可运行玩具树；异常路径提供明确错误信息；CI 无 HiGHS 时自动回退。

#### ✅ 任务 G2：策略表导出工具 `tools.export_policy`
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
- 难度评估：系数 3/5（序列化流程清晰，但需注意 determinism 与元数据完整性）。
- 易错点排雷
  - NPZ/JSONL 写入需确保目录存在且支持覆盖；注意 CI 无写权限路径的异常处理。
  - 0 权重动作应在导出前过滤/保留策略一致，避免后续查表缺字段。
  - `meta` 中 hash、seed、版本等字段遗漏会导致审计失败。
- DoD
  - 测试通过；NPZ 文件含所需数组；meta 字段齐备；调试 JSONL 可选输出；重复运行产出一致。

#### ✅ 任务 G3：离线流水线集成命令 `tools.m2_smoke`
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
- 难度评估：系数 4/5（串联多产物，需处理部分存在/缺失的幂等逻辑）。
- 易错点排雷
  - `--force`/`--reuse` 逻辑分支复杂，应写集成测试覆盖备份路径。
  - 报告需保证 PASS/ERROR 统一格式，否则自动化解析失败。
  - 后端回退信息要在报告中显式记录，避免调试困境。
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
- 难度评估：系数 4/5（涉及大文件懒加载、缓存一致性与线程安全）。
- 易错点排雷
  - `numpy.load` 默认 mmap=False，注意大文件内存占用；需结合 `allow_pickle=False` 安全策略。
  - 缓存刷新要避免竞态，最好使用读写锁或原子替换。
  - 日志/metrics 的性能影响要提前评估，避免查表延迟。
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
- 难度评估：系数 4/5（需要协调查表、回退、日志指标与现有代码的耦合）。
- 易错点排雷
  - `meta` 字段需保持向后兼容，避免破坏既有调用方。
  - fallback 调用必须保证幂等并避免重复执行策略查表。
  - 查表命中率统计需使用线程安全的计数器或 metrics 客户端。
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
- 难度评估：系数 3/5（业务逻辑明确，但需要良好的报告结构与 CLI 体验）。
- 易错点排雷
  - CLI 需处理策略/规则缺失的容错路径，避免异常退出。
  - 差异阈值要与监控对齐，避免数值单位不一致。
  - 报告文件注意覆盖策略与 CSV/Markdown 同步更新。
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
- 难度评估：系数 3/5（需梳理 node_key 生成链路与元信息同步）。
- 易错点排雷
  - 注意 bucket id、hand_class 的来源一致，避免线上/离线 schema 偏差。
  - 日志字段要控制大小，避免 meta 膨胀影响性能。
  - 文档与代码同步更新，保持使用方理解一致。
- DoD
  - 测试通过；策略查表键与离线桶映射对齐；缺失桶信息路径有日志与降级说明。

#### 任务 H5：极端规则路径覆盖扩展（3-bet/4-bet、OOP Delay）
- 先写的测试
  - `tests/test_policy_extreme_nodes.py`
    - `test_three_bet_and_four_bet_paths_present()`：对 `pot_type=3bet/4bet`、`role=oop/ip` 的节点，断言策略表或规则配置存在，且缺失时落到兜底并记录 `policy_fallback=true`。
    - `test_delay_lines_rule_path_consistency()`：对 OOP delay 线路抽样，验证 `meta.rule_path` 与策略表动作一致，避免默认 fallback。
    - `test_missing_extreme_rule_triggers_todo_marker()`：当覆盖缺失时，测试捕获标记（如结构化日志 `extreme_rule_missing=true`），提示补充配置。
- 实现要点
  - 扩充 `configs/rules` 与策略导出流程，显式覆盖 3-bet/4-bet pot_type、OOP delay 线路，并在树/策略产出中固化这些节点。
  - 若暂未能提供策略表，要求规则 fallback 记录 TODO 提示并在报告中聚合（配合 `tools.audit_policy_vs_rules`）。
  - 将该测试纳入慢测标签，确保在 CI/回归中执行（可提供 quick 模式抽样 2–3 个节点）。
- 交付物
  - 新增测试与规则/策略配置补齐；审计报告更新。
- 难度评估：系数 4/5（需覆盖极端博弈分支、数据产物与规则同步）。
- 易错点排雷
  - 极端节点数据稀疏，需确保树构建与策略导出都支持；建议先补齐样例再联动规则。
  - 测试运行成本高，注意 quick 模式抽样控制时长。
  - TODO 标记要统一 key，方便在监控和审计中聚合。
- DoD
  - 测试通过；极端 pot_type/位置节点在策略或规则层面有明确覆盖，fallback 仅在标记条件下触发并可观测。

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
  - 继承 M1 Review 风险项，确保 `tests/test_performance_p95_baseline.py` 迁移/升级到策略查表路径，并在文档中记录目标/现状差距。
  - 支持可配置样本数、超时时间；默认 1k 局面，可在 CI 中降级为 200 局面。
- 交付物
  - 新增性能测试与报告模板。
- 难度评估：系数 4/5（性能测试易受环境波动影响，需要稳定的采样与统计逻辑）。
- 易错点排雷
  - CI 与本地硬件差异大，需提供 quick 模式并在测试中留容差。
  - P95 计算需排除 warmup，避免统计偏差。
  - `reports/perf_policy.json` 需包含足够字段供后续回归。
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
- 难度评估：系数 5/5（长耗时仿真 + 统计分析，对随机性与 reproducibility 要求高）。
- 易错点排雷
  - 大样本评测时间长，需设计 quick 模式并使用持久化缓存减少重复计算。
  - 置信区间计算要明确算法（如 Wilson/Bootstrap），测试需锁定随机种子。
  - 报告需同时输出 Markdown/JSON，注意字段一致性。
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
  - 与 Compare & Tune 数据联动：支持在解释测试中复用 `reports/compare_m2.md` 的差异样本，确保老师-学生对照指标与口语化频率同步演进。
- 交付物
  - 模板与服务层更新；新增测试。
- 难度评估：系数 3/5（主要是模板文案与多种数据源整合）。
- 易错点排雷
  - 频率文案需考虑多语言/字符集，测试应覆盖中文/英文。
  - Exploit 提示与频率描述组合可能重复，需设计去重逻辑。
  - 缺失频率时的回退文案需符合产品调性，避免“无数据”硬提示。
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
- 难度评估：系数 3/5（配置驱动，关注热更新与灰度策略）。
- 易错点排雷
  - Manifest 与实际文件 hash 需同步，建议在 CI 中添加校验脚本。
  - 环境变量切换需考虑服务重载/缓存刷新，避免旧策略残留。
  - 灰度日志要包含用户标识以便追踪。
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
  - 针对查表容差风险，引入 `lookup_ev_diff_pct` 等指标，基于策略表与规则/真实表对比统计偏差；超阈值时输出结构化告警并生成 `reports/audit_lookup.md`。
- 交付物
  - metrics 模块增强、测试、文档。
- 难度评估：系数 4/5（指标种类多，需兼顾性能与可观察性）。
- 易错点排雷
  - metrics 客户端需支持 mock，避免测试写入真实后端。
  - 日志字段过多会影响 I/O，需优化批量写出或采样策略。
  - 偏差监控指标要与审计脚本一致，避免单位/符号差异。
- DoD
  - 测试通过；日志/指标字段齐备；CI 可在 mock 环境验证；fallback 命中率与查表偏差监控上线且超阈值有告警。

#### 任务 J3：CI 依赖守护与可选跳过（pokerkit 等第三方）
- 先写的测试
  - `tests/test_ci_dependency_guard.py`
    - `test_missing_pokerkit_marks_skip()`：模拟缺失 `pokerkit`，断言相关测试被打上 `xfail/skip` 且给出安装提示。
    - `test_dependency_manifest_lists_extras()`：校验 `configs/ci_dependencies.yaml` 中列出的可选依赖与 `pyproject`/`requirements` 保持一致。
    - `test_ci_guard_script_returns_nonzero_on_drift()`：当依赖缺失但未在守护配置中声明时，脚本返回非零并打印补救步骤。
- 实现要点
  - 新增 `tools.ci_dependency_guard`，在 CI pre-test 阶段扫描依赖并根据配置决定报错或标记跳过。
  - 在 `pyproject.toml` 或 `requirements-dev.txt` 中整理 extras，并在文档《docs/dev_setup.md》更新安装步骤。
  - 与 pytest 插件集成（例如自定义 marker），将缺失依赖的测试标记为 `skip` 而非硬失败，同时输出结构化日志。
- 交付物
  - 守护脚本、依赖配置、测试与文档更新。
- 难度评估：系数 3/5（流程脚本为主，需覆盖多种缺依赖场景）。
- 易错点排雷
  - `pyproject` 与 manifest 漏同步时需明确报错文案，避免误判。
  - pytest marker 的 skip/xfail 逻辑要与 CI pipeline 对齐。
  - 注意本地开发场景下的提示友好度，避免开发者被迫安装全部可选依赖。
- DoD
  - 测试通过；CI 在缺少 `pokerkit` 时可继续运行主流程并给出显式提示；依赖新增/删除需更新配置，否则守护脚本阻止合并。
#### 任务 J4：Fallback 行为安全网
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
- 难度评估：系数 3/5（局部算法调整，需兼顾策略一致性与安全性）。
- 易错点排雷
  - fallback 逻辑应保持纯函数特性，避免修改输入对象导致副作用。
  - 激进路径日志需与监控指标联动，便于统计。
  - 最小下注尺寸应调用规则模块常量，避免硬编码。
- DoD
  - 测试通过；默认情况下 fallback 仅返回被动动作；激进兜底路径带告警与钳制信息。
---
## K. Compare & Tune（老师-学生对照与自动调参 — 研究闭环）

> 从 M1 后置到 M2，结合策略表导出、评测与解释增强统一交付。

### 任务 K1：代表性局面集与老师打标
- 先写的测试
  - `tests/test_compare_tune_dataset.py`
    - `test_dataset_reproducible_with_seed()`：固定种子生成相同局面集。
    - `test_dataset_covers_extreme_pot_types()`：确保样本包含 3-bet/4-bet、OOP delay 等极端节点，呼应任务 H5。
- 实现要点
  - `tools.gen_cases --streets preflop,flop,turn --N 2000 --out artifacts/cases_m2.jsonl --include-extremes`。
  - 老师打标脚本 `tools.teacher_label --in artifacts/cases_m2.jsonl --out artifacts/labels_teacher.jsonl`；当 LP 策略可用时，以策略表为老师基线并记录版本。
  - 输出 `meta`，记录采样策略、策略版本、规则版本，便于回归。
- 交付物
  - 新样本与老师标签产物；测试覆盖。
- 难度评估：系数 4/5（采样策略复杂且需保障可复现）。
- 易错点排雷
  - 极端节点采样需与 H5 共享逻辑，避免覆盖不一致。
  - JSONL 体积可能较大，注意拆分或压缩策略。
  - 老师打标脚本需支持断点续跑，防止中途失败重头来过。
- DoD
  - 测试通过；产物可复现；覆盖极端节点且与策略版本绑定。

### 任务 K2：老师-学生对照评测与热力图
- 先写的测试
  - `tests/test_compare_metrics.py`
    - `test_metric_shapes_and_basic_ranges()`：Top-1 一致率、尺寸一致率、KL、ΔEV 基本范围正确。
    - `test_report_references_policy_version()`：报告包含策略/规则版本与采样 seed。
- 实现要点
  - `tools.compare --cases artifacts/cases_m2.jsonl --labels artifacts/labels_teacher.jsonl --student artifacts/policies --report reports/compare_m2.md --heatmap reports/compare_heatmap.png --thresholds configs/compare_thresholds.yaml`。
  - 验收线（可配置，默认）：Top‑1 ≥ 65%、尺寸一致率 ≥ 60%、ΔEV 中位数 ≥ 0；报告页首输出 PASS/FAIL 汇总，并与监控指标联动。
  - 新增测试 `tests/test_compare_thresholds.py`：阈值可读入、默认值正确、报告包含 PASS/FAIL。
- 交付物
  - 对照评测脚本、报告、热力图。
- 难度评估：系数 4/5（多指标评估 + 可视化生成，流程较长）。
- 易错点排雷
  - 阈值配置需考虑默认与自定义覆盖，防止测试耦合具体数字。
  - 热力图生成依赖 matplotlib/plotly，需在 CI 中确认依赖存在或提供 headless 方案。
  - 报告 PASS/FAIL 必须稳定，避免浮点精度导致边界抖动。
- DoD
  - 测试通过；报告与监控指标一致；支持 quick 模式。

### 任务 K3：自动调参（可选但建议）
- 实现要点
  - `tools.tune --space configs/tune_space.yaml --trials 100 --in rules/*.yaml --out rules.tuned.yaml --teacher artifacts/policies`，以策略表或老师标签为目标。
  - 记录 trial 结果并支持中断续跑；成功配置写回规则文件并生成 diff 报告。
- DoD
  - 调参脚本可运行并输出最优参数；报告列出收益/一致率提升；生成的规则文件通过现有测试。
- 难度评估：系数 5/5（可选项，但若实施涉及搜索空间、耗时与稳定性挑战）。
- 易错点排雷
  - 超参搜索需防止长时间运行阻塞 CI，可通过并行 + 提前停止机制。
  - 调参生成的规则需保证可追踪（版本、hash、diff），避免误覆盖。
  - 需考虑与老师/策略版本的匹配，防止调参目标漂移。
---
## 产物与命令总览（M2）
- LP 求解器封装：`tools/lp_solver.py`（HiGHS/linprog 双后端）。
- 策略导出产物：`artifacts/policies/{preflop,postflop}.npz`、`reports/m2_smoke.md`。
- 运行时查表模块：`packages/poker_core/suggest/policy_loader.py`、`packages/poker_core/suggest/service.py`（查表主路径）及极端规则覆盖补丁。
- 审计/评测报告：`reports/compare_m2.md`、`reports/compare_heatmap.png`、`reports/perf_policy.json`、`reports/audit_lookup.md`、`reports/eval_m2.md`。
- 配置与阈值：`configs/policy_manifest.yaml`、`configs/compare_thresholds.yaml`、`configs/tune_space.yaml`、`configs/ci_dependencies.yaml`、`rules.tuned.yaml`。
- 数据集与标签：`artifacts/cases_m2.jsonl`、`artifacts/labels_teacher.jsonl`。
可运行命令（实现后）：
- `python -m tools.lp_solver --tree artifacts/tree_flat.json --backend auto --out artifacts/lp_solution.npz`
- `python -m tools.export_policy --solution artifacts/lp_solution.npz --out artifacts/policies --debug-jsonl artifacts/policy_sample.jsonl`
- `python -m tools.m2_smoke --out reports/m2_smoke.md --quick`
- `python -m tools.gen_cases --streets preflop,flop,turn --N 2000 --out artifacts/cases_m2.jsonl --include-extremes`
- `python -m tools.teacher_label --in artifacts/cases_m2.jsonl --out artifacts/labels_teacher.jsonl`
- `python -m tools.compare --cases artifacts/cases_m2.jsonl --labels artifacts/labels_teacher.jsonl --student artifacts/policies --report reports/compare_m2.md --heatmap reports/compare_heatmap.png`
- `python -m tools.tune --space configs/tune_space.yaml --trials 100 --in rules --out rules.tuned.yaml`
- `python -m tools.audit_policy_vs_rules --policy artifacts/policies --rules configs/rules --out reports/policy_rule_audit.md`
- `python -m tools.eval_baselines --policy artifacts/policies --hands 200000 --out reports/eval_m2.md`
- `python -m tools.ci_dependency_guard --manifest configs/ci_dependencies.yaml`
---
## 建议执行顺序
1) G1 → G2 → G3（LP 求解与策略表产出流水线）。
2) H1 → H2 → H3 → H4 → H5（运行时查表接入、极端规则覆盖与审计工具）。
3) I1 → I2 → I3（性能与胜率评测、教学解释增强）。
4) J1 → J2 → J3 → J4（策略版本化、监控与依赖守护、Fallback 安全网）。
5) Compare & Tune：任务 K1 → K2 → K3（老师-学生对照与自动调参）。