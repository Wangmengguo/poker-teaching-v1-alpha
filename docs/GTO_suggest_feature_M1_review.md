# GTO Suggest Feature — M1 Readiness Review

## Review Scope and Method
- 对照《GTO_suggest_feature_rebuild_plan.md》的 M1 目标，检查离线产物与运行时 suggest 服务的对齐度，重点关注规则路径、混合策略、回退策略以及教学解释接口。 
- 复核 M1 任务包（A–F）中所有测试的覆盖范围，并抽查核心模块实现，确认边缘案例与默认兜底策略可落地。  
- 本次 review 以当前仓库主干为基准，未纳入 LP 表或 M2 以后的策略表目标。  

## Alignment with the Technical Plan
- M1 规划强调：完成分桶/转移矩阵、2-cap 抽象树、Turn 叶子 EV 缓存，并打通端到端规则路径、确定性混合基础设施和河牌规则启发式。【F:docs/GTO_suggest_feature_rebuild_plan.md†L3-L41】
- 运行时目标要求：1000 随机局面 P95 ≤ 1s、缺失节点触发保守回退、混合策略默认关闭且仅在解释中呈现频率。【F:docs/GTO_suggest_feature_rebuild_plan.md†L32-L41】【F:docs/GTO_suggest_feature_rebuild_plan.md†L65-L146】
- 当前实现已在 `policy.py` 中接入规则树 + 混合逻辑，默认保留单臂建议，并在 `meta` 与 `debug.meta` 中暴露频率/掷签细节，符合架构边界和展示口径要求。【F:packages/poker_core/suggest/policy.py†L478-L552】

## Offline Pipeline Readiness
- **分桶配置**：`tools.build_buckets` 的测试覆盖文件生成、schema 校验、label 匹配优先级，以及同种子一致性，满足 6/8/8 桶语义与计划要求。【F:tests/test_tools_buckets.py†L8-L87】
- **转移矩阵**：`tests/test_tools_transitions.py` 验证行随机、样本翻倍后的 TV 距离与元信息字段，确保 A2 目标中的统计稳定性；建议继续关注实际样本量对 TV 阈值的敏感度。
- **下注树与尺寸映射**：`policy.py` 运行时依赖 `_match_rule_with_trace` 返回的 `rule_path` 与 `size_tag`，配合 `Decision` 统一 sizing 解析，符合 2-cap 限制与尺寸配置约束。【F:packages/poker_core/suggest/policy.py†L439-L707】
- **Turn 叶子 EV 缓存** 与 **一键冒烟**：`tests/test_tools_ev_cache.py` 与 `tests/test_tools_smoke_m1.py` 覆盖产物形状、元信息及 quick-run 报告生成，确保全链路脚本在全新环境可复现（A1→A4→报告）。
- **Lookup 快表**：`tests/test_lookup_tables.py` 对 HS/Potential 查表产物的维度、兜底近似与公差进行断言，为后续 Turn/River 规则启发提供一致输入域。  

## Runtime Suggest Service Audit
- **节点键统一**：`node_key_from_observation` 结合 texture/SR 判定生成 `street|pot_type|role|pos|texture=·|spr=·|hand=·`，并在混合逻辑中回填 `meta.node_key`，与计划中的 node key 口径保持一致。【F:packages/poker_core/suggest/node_key.py†L20-L43】【F:packages/poker_core/suggest/policy.py†L490-L525】
- **确定性混合**：
  - `stable_weighted_choice` 采用 SHA1 前 8 字节构造 [0,1) 采样，过滤非正权重、退化情形回退 index 0，满足“同 seed 同节点稳定”的需求。【F:packages/poker_core/suggest/utils.py†L591-L630】
  - `tests/test_mixing_determinism.py` 验证确定性、分布误差界、mix 关闭时取最大权重，以及开启混合后的 `meta.frequency`、`debug.meta.mix` 填充及 size_tag 清理，覆盖主要边缘场景（含 size_tag 只在下注臂时保留）。【F:tests/test_mixing_determinism.py†L69-L170】
- **规则路径 & 解释**：服务层确保 `meta.rule_path/size_tag/plan` 在 flop/turn/river 规则命中时被填充，并在解释文本中口语化频率；同时 `_describe_frequency` 支持 Fraction/Decimal，增强 TTS/渲染稳定性。【F:tests/test_service_meta_contract_m1.py†L106-L202】
- **保守回退**：`choose_conservative_line` 优先返回 check/call/fold，并在面对 ≤1bb 或 pot odds ≤25% 时保持防守；缺失节点时附带 `CFG_FALLBACK_USED` rationale，确保用户可见兜底来源。【F:packages/poker_core/suggest/fallback.py†L36-L127】【F:tests/test_fallback_minimal.py†L57-L109】
- **金额钳制 & 频率解析**：`_clamp_amount_if_needed` 和 `_parse_frequency_value` 覆盖非法边界（min>max、负权重/百分比文本），降低上游异常对 UI 的影响。【F:packages/poker_core/suggest/service.py†L69-L213】

## Edge Case Coverage & Observations
- **混合节点缺失/退化**：当 `mix` 为空或全零权重时，`_select_action_from_node` 会回退到规则默认臂并仍写入 `rule_path`，避免空节点导致 crash。【F:packages/poker_core/suggest/policy.py†L495-L536】
- **河牌规则路径**：河牌策略仍依赖规则 + blocker 标签映射，`_RIVER_TIER_PLAN_DEFAULTS` 提供默认教学计划文案，符合 M1 “河牌规则/启发式” 的落地方案。【F:packages/poker_core/suggest/service.py†L223-L235】
- **SPR/纹理判定**：`node_key` 调用 `classify_spr_bin` 与 `canonical_texture_from_alias`，与 `classifiers.yaml` 配合固定边界，减少跨模块漂移风险。【F:packages/poker_core/suggest/node_key.py†L26-L33】
- **Fallback pot odds**：对极端 `to_call`/`pot_now` 情形提供 1.0 默认值，确保除零安全；建议未来将 `_pot_odds` 的 25% 阈值参数化以便策略调优。【F:packages/poker_core/suggest/fallback.py†L31-L123】

## Known Risks & Follow-up Suggestions
1. **第三方依赖缺失导致全套 `pytest` 无法完整运行**：当前环境缺少 `pokerkit`，导致 collection 阶段失败（`tests/providers/test_pokerkit_evaluator_basic.py`）。已在 M2 任务 `J3` 中规划 CI 依赖守护与跳过策略，需在合并前补齐脚本与配置。【76881d†L1-L63】【F:docs/GTO_suggest_feature_rebuild_tasks_M2.md†L205-L225】
2. **性能基准仍待实测**：计划要求端到端 P95 ≤1s，目前缺乏系统性基准测试记录；M2 任务 `I1` 要求迁移/升级 `tests/test_performance_p95_baseline.py`，在策略查表路径下输出冷/热对比及报告存档。【F:docs/GTO_suggest_feature_rebuild_tasks_M2.md†L152-L173】
3. **规则覆盖的极端 pot_type/位置**：虽有 node key 支持 `limped` 与三街角色，但仍建议补充 3-bet/4-bet（计划 M2/M3）及 OOP delay 线路的回归用例，防止规则树 defaults 过度 fallback。M2 新增任务 `H5` 专门覆盖这些节点并要求报告可观测。【F:docs/GTO_suggest_feature_rebuild_tasks_M2.md†L101-L136】
4. **Lookup 容差与实际表值偏差**：目前容差阈值 0.12 来自配置，建议在将来与真实策略表对比时加上报警/metrics，以捕捉 outs 估计漂移。M2 任务 `J2` 追加 `lookup_ev_diff_pct` 指标与告警报告，纳入运维监控。【F:docs/GTO_suggest_feature_rebuild_tasks_M2.md†L190-L207】

## Conclusion
- Offline 产物生成、规则路径、混合基础设施、保守回退和教学解释等 M1 核心能力均已落地，并与技术规划保持一致，能够支撑上线级的规则版 suggest baseline。
- 需在持续集成中补齐外部依赖与慢测脚本，确保性能与第三方模块的可复现性；同时为未来策略表接入预留监控/容差调优机制。
- Compare & Tune（老师-学生对照与自动调参）已整体挪至 M2 任务 `K1–K3`，待策略表产出与评测路径稳定后统一执行。
