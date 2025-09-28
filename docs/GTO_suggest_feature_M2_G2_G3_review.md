# M2 G2/G3 Review & LP Solver Runbook

## 1. Alignment With the Technical Plan
- M2 目标强调“LP 求解离线产物 + 策略表导出（NPZ 为主）+ 基线评测 + 运行时查表接入”以及持续可复现的产物。当前实现的 `tools.export_policy` 与 `tools.m2_smoke` 直接对应策略表导出与离线流水线集成命令，符合 Roadmap M2 的交付要求。 【F:docs/GTO_suggest_feature_rebuild_plan.md†L3-L63】
- 任务拆分文档中对 G2/G3 的 DoD、实现要点与测试要求已在仓库中落地，对齐“先写测试→实现→交付物”的既定节奏。 【F:docs/GTO_suggest_feature_rebuild_tasks_M2.md†L31-L69】

## 2. 任务 G2（策略表导出）现状评估
- **测试完备性**：`tests/test_policy_export.py` 覆盖 NPZ 文件生成、`node_key` 组件一致性、0 权重动作标记等关键路径，完全匹配任务书的验收项。 【F:tests/test_policy_export.py†L9-L134】【F:docs/GTO_suggest_feature_rebuild_tasks_M2.md†L31-L49】
- **核心实现**：`tools/export_policy.py` 提供参数化 CLI，读取解算产物并输出 `preflop/postflop` NPZ、可选 JSONL 抽样；对 `node_key` 组件、权重归一化、0 权重标记及表级元信息做了确定性处理，满足 deterministic + 审计需求。 【F:tools/export_policy.py†L1-L262】
- **对齐风险控制**：实现中包含复用控制（`--reuse`）、压缩选项与源解算元信息保留，可支撑后续审计、回归比较与 CI Quick 模式，符合文档对 determinism、元数据完整性的提醒。 【F:tools/export_policy.py†L24-L260】【F:docs/GTO_suggest_feature_rebuild_tasks_M2.md†L37-L47】
- **结论**：任务 G2 已达成 DoD，产物结构、元信息与测试覆盖均与计划一致。后续若需要扩展 bucket 元数据或版本号，可在 `table_meta` 与调试 JSONL 中扩展字段即可。

## 3. 任务 G3（离线流水线烟雾测试）现状评估
- **测试完备性**：`tests/test_tools_smoke_m2.py` 验证在空目录生成全量产物、报告 `PASS` 语义、以及对部分复用场景的处理，覆盖任务描述中的三项关键测试。 【F:tests/test_tools_smoke_m2.py†L15-L80】【F:docs/GTO_suggest_feature_rebuild_tasks_M2.md†L51-L69】
- **核心实现**：`tools/m2_smoke.py` 串联玩具树 LP 求解、策略导出与样例评测输出，支持 `--quick`/`--reuse`/`--force`/`--seed` 开关；报告中记录各产物尺寸与 solver backend，实现任务要求的幂等、回退与报告清晰度。 【F:tools/m2_smoke.py†L1-L238】
- **对齐风险控制**：命令内部调用 `lp_solver.solve_lp(..., backend="auto")`，在缺失 HiGHS 时可落到 linprog；产物复用逻辑与报告“reused=true|false”标记便于审计与增量刷新，符合任务对幂等性和回退信息显式化的提醒。 【F:tools/m2_smoke.py†L140-L214】【F:docs/GTO_suggest_feature_rebuild_tasks_M2.md†L57-L67】
- **结论**：任务 G3 已达到验收标准，后续若扩展到真实树/大样本，只需在玩具树生成处挂接真实产物及配置参数即可。

## 4. LP 求解与策略表使用操作手册
### 4.1 离线产物准备
1. **分桶与转移估计**（如尚未生成）：
   ```bash
   python -m tools.build_buckets --streets preflop,flop,turn --bins 6,8,8 --features strength,potential --out configs/buckets
   python -m tools.estimate_transitions --from flop --to turn --samples 200000 --out artifacts/transitions/flop_to_turn.json
   python -m tools.estimate_transitions --from turn --to river --samples 200000 --out artifacts/transitions/turn_to_river.json
   ```
2. **构建抽象树与 Turn 叶子 EV 缓存**：
   ```bash
   python -m tools.build_tree --config configs/trees/hu_discrete_2cap.yaml --out artifacts/tree_flat.json
   python -m tools.cache_turn_leaf_ev --trans artifacts/transitions/turn_to_river.json --out artifacts/ev_cache/turn_leaf.npz
   ```
   上述步骤沿用技术计划中的标准命令，确保离线产物与运行时树/桶配置一致。 【F:docs/GTO_suggest_feature_rebuild_plan.md†L43-L58】

### 4.2 LP 求解
3. **运行 LP 求解器**：
   ```bash
   python -m tools.solve_lp \
       --tree artifacts/tree_flat.json \
       --buckets configs/buckets \
       --transitions artifacts/transitions \
       --leaf_ev artifacts/ev_cache/turn_leaf.npz \
       --solver auto \
       --out artifacts/lp_solution.json
   ```
   - `--solver auto` 会优先尝试 HiGHS（高性能），缺失时自动回退到 linprog，与烟雾测试保持一致。
   - 结果 JSON 应包含 `meta`（包含 backend、seed、tree_hash 等）与 `nodes` 列表，为后续导出输入。

### 4.3 策略表导出
4. **导出 NPZ 策略表**：
   ```bash
   python -m tools.export_policy \
       --solution artifacts/lp_solution.json \
       --out artifacts/policies \
       --debug-jsonl reports/policy_sample.jsonl
   ```
   - `preflop.npz` 与 `postflop.npz` 将包含 `node_keys/actions/weights/size_tags/meta/table_meta` 数组，并保留 zero-weight 动作标签，方便运行时查表与审计。 【F:tools/export_policy.py†L167-L260】
   - 若希望避免覆盖既有产物，可追加 `--reuse`；需要压缩则加 `--compress`。

### 4.4 烟雾测试与回归
5. **一键烟雾测试（推荐）**：
   ```bash
   python -m tools.m2_smoke --out reports/m2_smoke.md --workspace . --quick
   ```
   - 命令会在 `./artifacts` 下输出解算 JSON 与策略 NPZ，并在 `reports/m2_smoke.md` 中记录状态、耗时及产物尺寸。 【F:tools/m2_smoke.py†L217-L237】
   - 若已有部分产物，可使用 `--reuse`；若需强制覆盖，使用 `--force`。

### 4.5 运行时使用要点
- 运行时加载层（H1/H2 阶段）应以 `node_key` 为索引读取 NPZ 中的动作与权重，`meta.node_key_components` 保障与离线分桶一致。 【F:tools/export_policy.py†L167-L199】
- 若策略查表缺失，可回退到 `packages/poker_core/suggest/fallback.py` 的保守规则路径；烟雾测试在报告中已记录 fallback 触发情况，便于监控。 【F:packages/poker_core/suggest/fallback.py†L1-L200】

## 5. 后续建议
- 将烟雾测试中的玩具树替换为真实树配置，并在 `table_meta` 中填充真实 hash/版本号，以简化后续审计。
- 在运行时策略加载（H1/H2）落地后，可将 `tools.m2_smoke` 集成进 CI 以验证端到端查表路径；同时时常检查 `reports/m2_smoke.md` 以追踪 solver backend 与产物大小的变动趋势。

