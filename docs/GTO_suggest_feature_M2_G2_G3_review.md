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

## 4. H1–H3 运行时接入现状评估
- **H1（策略 NPZ 读取与缓存层）**：`PolicyLoader` 已实现文件/目录自适应加载、归一化权重、meta/table_meta 透传，以及热更新检测；单元测试覆盖权重归一化、缺失节点的 metrics&日志、mtime 变更触发刷新等 DoD 项。 【F:packages/poker_core/suggest/policy_loader.py†L45-L199】【F:tests/test_policy_loader.py†L18-L102】
- **H2（service 查表主路径）**：`build_suggestion` 会优先通过 `get_runtime_loader()` 获取策略条目，命中时将查表结果转换为主路径建议，并在 `meta/debug.meta` 中补充 `policy_source`、`policy_version` 与 `policy_fallback`；测试覆盖命中/缺失/零权重三类分支。 【F:packages/poker_core/suggest/service.py†L422-L512】【F:tests/test_service_policy_path.py†L111-L166】
- **H3（策略/规则一致性审计工具）**：`tools.audit_policy_vs_rules` 支持 CLI 形态，能够加载策略快照、对比 JSON 规则并输出 Markdown；测试验证差异报告生成、缺失节点处理与阈值超标的退出码。 【F:tools/audit_policy_vs_rules.py†L14-L196】【F:tests/test_policy_rule_audit.py†L7-L94】

### 4.1 缺少正式策略表时的未验证点
- **环境变量注入与目录多文件场景**：`get_runtime_loader()` 依赖 `SUGGEST_POLICY_DIR/SUGGEST_POLICY_PATH` 自动注入查表路径；现有测试通过 monkeypatch 返回手动构造的 `PolicyLoader`，尚未覆盖真实环境读取、多文件（如 `preflop.npz` + `postflop.npz`）组合加载、缓存命中指标等行为。 【F:packages/poker_core/suggest/policy_loader.py†L138-L247】【F:tests/test_service_policy_path.py†L111-L166】
- **实际 node_key 映射一致性**：运行时代码调用 `node_key_from_observation` 生成查表键，并依赖策略表中的 `node_key_components` 做校验；当前仅使用玩具 Observation，尚未用真实分桶/多街道数据验证键空间覆盖、`bucket`/`spr` 等字段与离线导出完全一致。 【F:packages/poker_core/suggest/service.py†L455-L508】【F:tests/test_service_policy_path.py†L65-L106】
- **查表建议与金额钳制联动**：`_build_table_policy` 仅在权重有效时返回查表建议，后续会结合 `_clamp_amount_if_needed`、`_infer_amount_from_legal_actions` 对下注金额做合法性校准；由于缺乏真实策略权重/size_tag，目前尚未在集成层验证金额钳制、频率文案与教学解释链路。 【F:packages/poker_core/suggest/service.py†L207-L320】
- **审计工具真实规模回归**：审计 CLI 目前仅对单节点样例运行；缺少真实策略表时，尚未覆盖大规模节点排序、Top-N 摘要可读性及阈值配置与运营策略的吻合度，也未验证与真实 `configs/rules` 的 schema 兼容性。 【F:tools/audit_policy_vs_rules.py†L39-L196】【F:tests/test_policy_rule_audit.py†L18-L94】

### 4.2 策略表生成步骤校验
- 文档中“离线产物准备 → LP 求解 → 策略表导出 → 烟雾测试”流程与现有 CLI 保持一致，命令行参数与脚本实现一一对应，支持 `--quick`、`--reuse` 等开关用于资源受限场景。 【F:tools/m2_smoke.py†L1-L238】【F:tools/export_policy.py†L24-L260】
- `tools.export_policy` 写出的 NPZ 中包含 `node_keys/actions/weights/meta/table_meta` 等运行时所需字段；烟雾测试会自动记录 solver backend、产物尺寸，可在正式策略产出后用于回归验证。 【F:tools/export_policy.py†L167-L260】【F:tools/m2_smoke.py†L217-L237】

## 5. LP 求解与策略表使用操作手册
### 5.1 离线产物准备
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

### 5.2 LP 求解
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

### 5.3 策略表导出
4. **导出 NPZ 策略表**：
   ```bash
   python -m tools.export_policy \
       --solution artifacts/lp_solution.json \
       --out artifacts/policies \
       --debug-jsonl reports/policy_sample.jsonl
   ```
   - `preflop.npz` 与 `postflop.npz` 将包含 `node_keys/actions/weights/size_tags/meta/table_meta` 数组，并保留 zero-weight 动作标签，方便运行时查表与审计。 【F:tools/export_policy.py†L167-L260】
   - 若希望避免覆盖既有产物，可追加 `--reuse`；需要压缩则加 `--compress`。

### 5.4 烟雾测试与回归
5. **一键烟雾测试（推荐）**：
   ```bash
   python -m tools.m2_smoke --out reports/m2_smoke.md --workspace . --quick
   ```
   - 命令会在 `./artifacts` 下输出解算 JSON 与策略 NPZ，并在 `reports/m2_smoke.md` 中记录状态、耗时及产物尺寸。 【F:tools/m2_smoke.py†L217-L237】
   - 若已有部分产物，可使用 `--reuse`；若需强制覆盖，使用 `--force`。

### 5.5 运行时使用要点
- 运行时加载层（H1/H2 阶段）应以 `node_key` 为索引读取 NPZ 中的动作与权重，`meta.node_key_components` 保障与离线分桶一致。 【F:tools/export_policy.py†L167-L199】
- 若策略查表缺失，可回退到 `packages/poker_core/suggest/fallback.py` 的保守规则路径；烟雾测试在报告中已记录 fallback 触发情况，便于监控。 【F:packages/poker_core/suggest/fallback.py†L1-L200】

## 5. 后续建议
- 将烟雾测试中的玩具树替换为真实树配置，并在 `table_meta` 中填充真实 hash/版本号，以简化后续审计。
- 在运行时策略加载（H1/H2）落地后，可将 `tools.m2_smoke` 集成进 CI 以验证端到端查表路径；同时时常检查 `reports/m2_smoke.md` 以追踪 solver backend 与产物大小的变动趋势。

## 6. 硬件受限情况下的策略表生成方案
- **远程/云端求解**：利用带 GPU/高内存实例的云主机（如 AWS EC2、阿里云 gn5）或租赁高校/实验室服务器，通过 `tools.solve_lp` 与 `tools.export_policy` 组合命令执行完整流水线；完成后只需拉回 `artifacts/policies/*.npz` 与 `reports/m2_smoke.md` 即可复用现有加载与审计逻辑。 【F:tools/m2_smoke.py†L217-L237】【F:tools/export_policy.py†L167-L260】
- **拆分求解 + 合并导出**：若整体树超出本地内存，可按街道或子树拆分运行 `tools.solve_lp`，利用 `--reuse` 选项分批写入 `artifacts/lp_solution.json`，再一次性执行 `tools.export_policy` 合并导出，最大化本地资源利用率。 【F:tools/export_policy.py†L24-L164】
- **降采样/玩具树预热**：在本地先使用玩具树或较小分桶（`--bins` 数降低）跑通 `tools.m2_smoke --quick`，验证流程与运行时查表；待远程计算产出正式 NPZ 后仅需替换文件，无需改动代码。 【F:tools/build_buckets.py†L1-L200】【F:tools/m2_smoke.py†L1-L238】
- **结果缓存与版本管理**：在 `reports/` 目录维护策略表版本号、生成时间与来源（本地/云端），并借助 `--reuse` 避免重复求解，确保资源紧张时也能快速回滚到上一版产物。 【F:tools.export_policy.py†L24-L164】【F:tools.m2_smoke.py†L140-L214】

## 7. 在尚未有正式策略表时推进 H 阶段的方案
- **使用测试桩数据**：复用 `tests/test_policy_export.py` 中构造的策略样本或将烟雾测试生成的玩具 `npz` 作为临时依赖，实现 `packages/poker_core/suggest` 的查表接口，确保加载、索引与 fallback 逻辑可在 CI 中被验证。 【F:tests/test_policy_export.py†L9-L134】【F:packages/poker_core/suggest/fallback.py†L1-L200】
- **接口契约先行**：按照本地文档的 `node_key` 结构与 `meta.node_key_components` 约定，实现 H 阶段的读取/校验模块；即便缺少真实权重，也可以通过 mock 权重与零权动作标签测试接入逻辑。 【F:tools/export_policy.py†L167-L210】
- **模拟运行时回退链路**：优先完成 fallback 策略、熔断与日志模块，利用空策略表或缺失条目模拟异常场景，确保正式策略落地前运行时不会出现致命错误。 【F:packages/poker_core/suggest/fallback.py†L1-L200】
- **持续维护流水线脚本**：在 H 阶段迭代中保留 `tools.m2_smoke` 快速回归能力，一旦远程生成正式策略表，可立即运行烟雾测试并导入到运行时验证链路，缩短集成时间。 【F:tools.m2_smoke.py†L1-L238】

## 8. 云端 LP 求解全流程（手把手）
下述流程示例基于常见的「本地 macOS/Linux 终端 + 云端 Linux 实例」组合，目标是在云端跑完 `tools.solve_lp` → `tools.export_policy` → （可选）`tools.m2_smoke`，并把产物拉回本地。若使用其他云厂商，替换对应的实例创建命令与凭证即可。

### 8.1 本地准备
1. **同步最新代码**：在本地确认仓库为干净状态并推送到远端（例如 GitHub private repo）。
   ```bash
   git status
   git push origin <your-branch>
   ```
2. **打包上传所需文件**：为了减小体积，可只打包核心脚本与依赖；若本地已有可复用的 `artifacts/` 输入（树、转移、EV 缓存等），也一并打包。
   ```bash
   tar czf poker_gto_bundle.tgz configs tools packages scripts artifacts pyproject.toml
   ```
3. **准备云端登录信息**：记录云主机的公网 IP、SSH 用户名、密钥路径，例如：
   ```bash
   export CLOUD_HOST=ubuntu@1.2.3.4
   export CLOUD_KEY=~/.ssh/cloud_instance.pem
   ```

### 8.2 云端实例初始化
4. **上传代码包**：
   ```bash
   scp -i "$CLOUD_KEY" poker_gto_bundle.tgz "$CLOUD_HOST":~/
   ```
5. **首次登录并安装依赖**：
   ```bash
   ssh -i "$CLOUD_KEY" "$CLOUD_HOST"
   sudo apt-get update
   sudo apt-get install -y python3 python3-venv python3-pip build-essential git
   python3 -m venv ~/gto-venv
   source ~/gto-venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt  # 若项目提供 requirements；否则使用 `pip install .`
   ```
6. **解压并检查目录**：
   ```bash
   mkdir -p ~/workspace/poker
   tar xzf ~/poker_gto_bundle.tgz -C ~/workspace/poker
   cd ~/workspace/poker
   ls
   ```

### 8.3 云端一键求解脚本（推荐）
7. **创建一键脚本**：在云端当前目录编写 `run_cloud_pipeline.sh`，内容如下：
   ```bash
   cat <<'SCRIPT' > run_cloud_pipeline.sh
   #!/usr/bin/env bash
   set -euo pipefail
   WORKDIR=${1:-$(pwd)}
   OUTDIR=${WORKDIR}/artifacts
   REPORT=${WORKDIR}/reports/m2_smoke_cloud.md

   mkdir -p "$OUTDIR" "$WORKDIR/reports"

   if [ ! -f "${OUTDIR}/tree_flat.json" ]; then
       python -m tools.build_tree \
           --config configs/trees/hu_discrete_2cap.yaml \
           --out ${OUTDIR}/tree_flat.json
   fi

   if [ ! -d "${OUTDIR}/transitions" ]; then
       mkdir -p ${OUTDIR}/transitions
       python -m tools.estimate_transitions \
           --from flop --to turn --samples 200000 \
           --out ${OUTDIR}/transitions/flop_to_turn.json
       python -m tools.estimate_transitions \
           --from turn --to river --samples 200000 \
           --out ${OUTDIR}/transitions/turn_to_river.json
   fi

   if [ ! -f "${OUTDIR}/ev_cache/turn_leaf.npz" ]; then
       mkdir -p ${OUTDIR}/ev_cache
       python -m tools.cache_turn_leaf_ev \
           --trans ${OUTDIR}/transitions/turn_to_river.json \
           --out ${OUTDIR}/ev_cache/turn_leaf.npz
   fi

   python -m tools.solve_lp \
       --tree ${OUTDIR}/tree_flat.json \
       --buckets configs/buckets \
       --transitions ${OUTDIR}/transitions \
       --leaf_ev ${OUTDIR}/ev_cache/turn_leaf.npz \
       --solver auto \
       --out ${OUTDIR}/lp_solution.json

   python -m tools.export_policy \
       --solution ${OUTDIR}/lp_solution.json \
       --out ${OUTDIR}/policies \
       --compress \
       --debug-jsonl ${OUTDIR}/policy_sample.jsonl

   python -m tools.m2_smoke \
       --workspace "$WORKDIR" \
       --out "$REPORT" \
       --reuse

   SCRIPT
   chmod +x run_cloud_pipeline.sh
   ```
   - 根据需要将 `--tree`、`--transitions` 等输入替换为已同步到云端的真实文件路径。如果这些产物也需在云端生成，可在脚本前追加 `tools.build_buckets`、`tools.build_tree` 等命令。

8. **运行脚本并监控**：
   ```bash
   source ~/gto-venv/bin/activate
   cd ~/workspace/poker
   ./run_cloud_pipeline.sh
   tail -f reports/m2_smoke_cloud.md  # 观察进度，可在运行结束后退出
   ```
   - 若需要在后台运行，可参考下文“8.4 SSH 断开连接时确保脚本不中断”。

### 8.4 SSH 断开连接时确保脚本不中断
- **为何会中断？** `scripts/run_cloud_pipeline.sh` 串行执行多个 Python 模块，默认附着在当前 SSH 会话；一旦网络断开或关闭终端，系统会向前台作业发送 `SIGHUP`，脚本及其子进程会立即退出，导致长时任务中断。 【F:scripts/run_cloud_pipeline.sh†L1-L49】
- **首选方案：使用终端复用器**。
  1. 登录云主机后启动新的 `tmux` 会话：
     ```bash
     tmux new -s gto-pipeline
     ```
  2. 在会话内执行脚本：
     ```bash
     bash scripts/run_cloud_pipeline.sh
     ```
  3. 通过 `Ctrl-b` `d`（先按 `Ctrl`+`b`，再按 `d`）分离会话。即便 SSH 断连，脚本仍会在服务端继续运行；重新连上后使用：
     ```bash
     tmux attach -t gto-pipeline
     ```
- **备选方案：`nohup` + 后台运行**。若所在环境无法安装 `tmux/screen`，可以：
  ```bash
  nohup bash scripts/run_cloud_pipeline.sh > reports/cloud_pipeline.log 2>&1 &
  tail -f reports/cloud_pipeline.log
  ```
  `nohup` 会忽略 `SIGHUP`，并将输出写入日志文件；可用 `tail -f`、`less` 观察进度，或用 `ps -ef | grep run_cloud_pipeline` 检查进程。
- **更进一步：systemd-run/atd**。在具有 `systemd` 权限的机器上，可用 `systemd-run --unit=gto-pipeline --scope bash scripts/run_cloud_pipeline.sh`，或提前用 `at` 调度执行，以完全脱离交互式会话。
- **收尾检查**：无论采用哪种方式，任务完成后都应查看 `reports/m2_smoke_cloud.md` 与 `artifacts/` 目录，确认 `lp_solution.json`、`policies/`、`policy_sample.jsonl` 等产物是否生成完整，再将日志与结果拉回本地归档。

### 8.5 拉取产物回本地
9. **压缩产物以便下载**：
   ```bash
   cd ~/workspace/poker
   tar czf cloud_results.tgz artifacts/policies artifacts/lp_solution.json reports/m2_smoke_cloud.md
   ```
10. **下载回本地**：
    ```bash
    scp -i "$CLOUD_KEY" "$CLOUD_HOST":~/workspace/poker/cloud_results.tgz ./
    tar xzf cloud_results.tgz -C ./
    ```
11. **合并到本地仓库**：
    ```bash
    cp -r artifacts/policies local_artifacts/
    cp reports/m2_smoke_cloud.md reports/
    git add local_artifacts/policies reports/m2_smoke_cloud.md
    ```

### 8.6 日常复用 & 自动化
- **增量更新**：后续只需同步改动的配置或脚本（可使用 `rsync -az`），云端脚本可复用。
- **自动触发**：可在 CI/CD 中创建 job，通过云厂商的 API 启动实例、执行 `run_cloud_pipeline.sh` 并把 `cloud_results.tgz` 上传至对象存储，再由本地/其他流水线下载。
- **版本记录**：在 `reports/` 中维护 `m2_smoke_cloud.md` 与当前策略表哈希、生成时间，用于审计与回滚。

