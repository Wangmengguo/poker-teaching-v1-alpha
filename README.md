# Poker Teaching System — v1+

一个“教学优先”的两人德扑（HU NLHE）系统：纯函数领域引擎 + Django/DRF API + 教学视图。

**概览（Overview）**
- 领域引擎：`packages/poker_core/state_hu.py`（SB/BB 可配置；发盲→轮次→结算；筹码守恒）。
- 评牌：优先 PokerKit，不可用时回退简化评估。
- 会话流：多手对局（按钮轮转、承接筹码）；统一回放结构持久化到 DB。
- 建议（Suggest）：`POST /api/v1/suggest`（纯函数策略 → 决策解析 → 合法性统一 → 教学解释）。
- 最小 UI：HTMX + Tailwind，事件驱动 + OOB 片段，一次响应同步 HUD/牌面/行动条/金额/Coach/错误/座位与日志。
- 回放页面：`GET /api/v1/ui/replay/<hand_id>`（轻量时间轴 + 播放控制）。

**本次迭代要点（v1 教学闭环）**
- 决策契约 Decision：策略返回 `Decision(action, SizeSpec)`，服务层统一换算金额；postflop 使用“raise to‑amount”语义并自动处理最小重开（追加 `FL_MIN_REOPEN_ADJUSTED`）。
- 统一上下文 SuggestContext：集中加载策略档（loose/medium/tight）与配置（modes/open/vs）。
- 观察 Observation 扩展：`pot_now/first_to_act/last_to_act/facing_size_tag/last_bet/last_aggressor`；翻后六桶 `HandStrength`；`meta.rule_path` 追踪命中路径。
- Preflop v1：SB RFI/BB 防守，支持 3bet to‑bb（`meta.reraise_to_bb/bucket`）；SB vs 3bet 可选 4bet；所有路径补 `meta.plan`。
- Flop v1：角色 + 纹理 + SPR 对齐 MDF，支持 value‑raise 的 JSON 规则。
- Turn/River v1（极简）：沿用 flop 框架（pot_type/role/ip‑oop/texture/SPR→{action,size_tag}），返回 `size_tag/mdf/pot_odds/facing_size_tag/rule_path/plan`；修复 SPR 键映射 `low|mid|high → le3|3to6|ge6`。
- 自然语言解释 explanations：服务层注入 `resp.explanations: list[str]`（中文模板渲染 `rationale+meta`）。

— 怎么跑（Run） —

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install -e '.[dev]'
cd apps/web-django
python manage.py makemigrations api
python manage.py migrate
python manage.py runserver
```

打开：

- API Docs: http://127.0.0.1:8000/api/docs
- Metrics:   http://127.0.0.1:8000/api/v1/metrics/prometheus
- 最小 UI 入口：http://127.0.0.1:8000/api/v1/ui/start

最小 UI 对局页（事件驱动 + OOB，无轮询）
- 入口页一键开始（推荐）：浏览器打开 `/api/v1/ui/start`，点击 Start the session。
- 或用 API：`/session/start` → `/hand/start` → 打开 `/api/v1/ui/game/<session_id>/<hand_id>`。
- 交互节奏：仅在“执行动作/获取建议/开始下一手”时发起请求；其余时间零请求；每次响应用 OOB 同步多个区域。

— 怎么用（API 快查） —

- `POST /api/v1/session/start` 创建会话（可传 `sb/bb/max_hands`）
- `GET  /api/v1/session/<sid>/state` 会话视图（`stacks/stacks_after_blinds`）
- `POST /api/v1/hand/start` 开一手（可传 `seed`）
- `GET  /api/v1/hand/<hid>/state` 查询状态与 `legal_actions`
- `POST /api/v1/hand/<hid>/act` 执行动作（`check/call/bet/raise/fold/allin`）
- `GET  /api/v1/hand/<hid>/replay` / `GET  /api/v1/ui/replay/<hid>` 回放
- `POST /api/v1/suggest` 最小建议 `{hand_id, actor}`
  - `suggested`: `{action, amount?}`
  - `rationale`: `[{code,msg,data?}]`
  - `policy`: `preflop_v1|flop_v1|turn_v1|river_v1|...`
  - `meta`（按街）：
    - Preflop：`open_bb`｜`reraise_to_bb`｜`bucket`｜`pot_odds`｜`plan`
    - Flop：`size_tag`｜`mdf`｜`facing_size_tag`｜`texture`｜`pot_type`｜`rule_path`｜`plan`
    - Turn/River：`size_tag`｜`mdf`｜`facing_size_tag`｜`rule_path`｜`plan`
  - `explanations`（可选）：中文解释数组
  - 错误：`404` 不存在；`409` 非行动者/已结束；`422` 无法给出合法建议

— 配置与开关（Cheat Sheet） —

```bash
# 策略与灰度
export SUGGEST_POLICY_VERSION=v1           # v0|v1|v1_preflop|auto
export SUGGEST_STRATEGY=medium            # loose|medium|tight
export SUGGEST_V1_ROLLOUT_PCT=0           # auto 灰度

# 建议细节
export SUGGEST_FLOP_VALUE_RAISE=1         # flop 价值加注 JSON（默认 1）
export SUGGEST_PREFLOP_ENABLE_4BET=0      # SB vs 3bet 4bet（默认 0）
export SUGGEST_LOCALE=zh                  # explanations 语言（默认 zh）
export SUGGEST_MIXING=on                  # 行为混频（稳定哈希），默认 on；设为 off 关闭
export SUGGEST_FLOP_CALL_VS_LARGE_POTODDS=0.50  # 面对大尺吋/全下的“必防”价位上限
export SUGGEST_FLOP_FOLD_VS_LARGE_POTODDS=0.55  # 面对大尺吋/全下的“必弃”价位下限
export SUGGEST_PREFLOP_DEFEND_SHOVE=1     # 预留开关（当前默认启用，读取配置表）

# 调试
export SUGGEST_DEBUG=1                    # 返回 debug.meta（pot_odds/size_tag/rule_path 等）
export SUGGEST_CONFIG_DIR=packages/poker_core/suggest  # 可外置覆盖配置
export SUGGEST_TABLE_MODE=HU
```

— CI 稳定混频（Deterministic Mixing for CI） —

为避免“混频抽样导致的用例随机失败”，在 CI 环境建议开启混频但固定采样种子：

```bash
# 建议用于 CI 的环境变量（示例）
export SUGGEST_MIXING=on
export SUGGEST_MIX_SEED=fixed         # hand|session|fixed（默认 hand）
export SUGGEST_MIX_FIXED_KEY=ci       # fixed 模式下的基种子
export SUGGEST_MIX_SALT=ci            # 可选盐值；同一套 CI 保持稳定，不同流水线可更换
```

模式说明（SUGGEST_MIX_SEED）：
- `hand`（默认）：以 `hand_id` 为基种子（更贴近实战，回放一致）。
- `session`：优先使用 `session_id/config_profile/strategy_name`，同一会话内稳定。
- `fixed`：使用 `SUGGEST_MIX_FIXED_KEY` 作为固定基种子；可配合 `SUGGEST_MIX_SALT` 做隔离，适合 CI。

本仓库的 GitHub Actions 已采用上述变量，保证混频开启但运行稳定、可复现。

— 默认行为说明（v1 + mixing on） —

自 2025-10-15 起，系统默认启用建议策略 v1 且混频开启（无需设置环境变量）：
- 默认策略：`SUGGEST_POLICY_VERSION=v1`（服务层默认值）。
- 默认混频：`SUGGEST_MIXING=on`（策略层默认值）。

默认行为要点（教学/实战皆适用）：
- 预翻全下防守（HU，对全下/仅剩 call|fold 节点）：
  - `packages/poker_core/suggest/config/preflop_vs_shove_HU.json` 按 `le12/13to20/gt20` 划分强制跟注与混频跟注的组合集；
  - `JJ+/AK` 必跟；`TT/AQs/KQs` 在深筹段以给定频率混跟（可由表调整）；
  - 行为受混频控制并稳定哈希，避免被固定频率剥削。
- 翻牌与河牌的大尺吋防守（`two_third+`）：
  - 翻牌：中对/弱顶对在 `pot_odds ≤ 0.50` 时必防，灰区混跟，否则弃；
  - 河牌：按 `river_semantics` 的摊牌价值分层（强/中/弱/空气）+ 价格兜底，强价值必跟，中等价值在合理价格范围内跟或混跟，弱摊牌仅在极佳赔率下勉强跟；
  - 阈值可通过 `packages/poker_core/suggest/config/river_defense.json` 或对应环境变量覆盖。

— 一键验证脚本 —

1) 极端对手“能全下就全下”的鲁棒性检查（均值应接近 0，不能被一招剥削）：

```bash
python scripts/sim_always_allin_vs_bot.py --sessions 30 --hands 60 --seed 271828
# 观察输出：wins/losses 接近均衡、mean human PnL 接近 0（±若干筹码）
```

2) 对垒平台（Arena Duel）
   使用两个机器人，分别带不同的策略参数进行对攻，输出胜负与 A 方均值 PnL：

   ```bash
   # A: baseline（v1 + mixing on）；B: exploit（预翻全下剥削）
   python scripts/arena_duel.py --sessions 50 --hands 60 --seed 123 \
     --a.policy v1 --a.mixing on --a.exploit none \
     --b.policy v1 --b.mixing on --b.exploit vs_allin

   # 双剥削（自洽性检查，长期应接近 0）
   python scripts/arena_duel.py --sessions 50 --hands 60 --seed 123 \
     --a.policy v1 --a.mixing on --a.exploit vs_allin \
     --b.policy v1 --b.mixing on --b.exploit vs_allin
   ```

   参数说明：
   - `--*.policy`: `v0|v1`（默认 v1）
   - `--*.mixing`: `on|off`（默认 on）
   - `--*.strategy`: `loose|medium|tight`（默认 medium）
   - `--*.exploit`: `none|vs_allin`（默认 none）。当设置为 `vs_allin` 时，预翻面对“全下型”对手启用剥削表（更宽的必跟/混频跟注）。

— 剥削模式（Exploit） —
针对单一逻辑对手提供最小可用的剥削开关（先手动，再逐步接入识别）：

```bash
# 启用预翻 vs 全下剥削（手动）：
export SUGGEST_EXPLOIT_PROFILE=vs_allin

# 调整“把它视为全下”的识别阈值（默认 8bb）：
export SUGGEST_SHOVE_DETECT_TO_CALL_BB=8.0
```

实现要点：
- 预翻全下识别更健壮：除纯 `call/fold` 节点外，当 `to_call_bb ≥ 阈值` 时也视为“面对全下”（即使引擎仍列出 `raise`）。
- 剥削表：`packages/poker_core/suggest/config/preflop_vs_shove_HU_exploit.json`（`le12/13to20/gt20`）在短码显著放宽 `call/mix` 组合，深筹谨慎放宽。
- 运行时通过 `SUGGEST_EXPLOIT_PROFILE=vs_allin` 自动切换到该表；未开启时沿用默认防守表 `preflop_vs_shove_HU.json`。
 - 先手 Exploit Jam：当我们“先手行动 + vs_allin”时，以“高权益牌（近似≥50% vs random）”直接全下（SB 场景）。
   - 规则近似：任意对子、任意 Ax、以及 KQ/KJ/KT、QJ/QT、JT(s)、T9s 等；
   - 原理：对手会“能全下就全下”，面对我们的全下只能跟注；在深筹下先手全下的盈亏平衡权益约为 `to_call / (2*to_call + pot)`≈0.5，因此上述组合具有正期望；
   - 仅在 `SUGGEST_EXPLOIT_PROFILE=vs_allin` 打开时启用，不影响常规（非剥削）模式。

提示：以上脚本均无需显式设置策略变量；服务层与策略层已默认 v1 + 混频 on。

— 后续优化路线（策略表与阈值的系统化收敛） —

- 预翻 vs shove（对栈深敏感）：
  - 以“有效筹码（bb）× 位置（SB/BB）”为键扩展防守表；现有 `le12/13to20/gt20` 作为起点，细化至 `≤8/9–12/13–20/21–40/41–100/101–200`；
  - 为 `mix_map` 提供每组合独立频率，并允许按位置与盲注比例（SB/BB 比）微调；
  - 通过对垒平台批量试验不同频率（网格/贝叶斯优化），以“均值 PnL≈0”为收敛准则并生成快照。

- 翻牌/河牌大尺吋兜底（对 SPR/纹理敏感）：
  - 将现有阈值细分到 SPR 段（`low/mid/high`），不同纹理（dry/semi/wet）加载不同 `call_le/mix_to`；
  - 在河牌 `medium_value` 的灰区，频率由对垒结果反推（保证总体不低于 MDF 的同时避免过度跟注）。

- 统一“短码/长码”认知：
  - 建议在 `SuggestContext.modes` 中引入 `eff_bb_bands`，策略在构造 Observation 后根据 `to_call/pot_now/eff_stack` 映射到 band，从而加载对应的表或阈值；
  - 预翻与翻后公用该 band，确保短码（≤20bb）与深筹（≥100bb）行为有本质差异。

- 校准与回归：
  - 对垒回归：固定种子集（如 200 个），每次策略/表变更后跑 `arena_duel.py` 并产出 `mean PnL` 区间；
  - 线上观测：追加 Prometheus 指标（`defend_shove_total`、`river_defend_large_total`）与价位分箱，持续监控防守频率与胜率。

— 调试脚本 —
- 单次：`python scripts/suggest_debug_tool.py single --policy auto --pct 10 --debug 1 --seed 42 --button 0`
- 灰度分布：`python scripts/suggest_debug_tool.py dist --policy auto --pct 10 --debug 1 --count 2000 --show-sample 8`

— 小矩阵 LP CLI（G6） —
- `python -m tools.solve_lp --tree tree.json --buckets buckets.json --transitions transitions.json --leaf_ev leaf.json --out solution.json`
- `--small-engine {auto,on,off}`：`auto`（默认）在 `max(rows, cols) ≤ --small-max-dim` 时优先走小矩阵路径；`on` 强制使用（若超门槛将抛出 `small engine forced on but matrix dimension ... exceeds limit ...`）；`off` 完全禁用。
- `--small-max-dim <int>`：小引擎门槛（默认 5）。当矩阵最大维度超过该值时会退回 HiGHS/linprog；提高门槛（例如 6）可在 6×5/5×6 等边界矩阵上启用小引擎。
- 小引擎元信息：`meta.small_engine_used/method/reduced_shape/domination_steps` 记录是否降阶、具体方法（analytic/linprog_small 等）与裁剪形状；烟囱报告 `tools.m2_smoke` 会聚合这些字段。

— 导出与烟囱 CLI 快查（M2/G6） —

- 导出策略表（export_policy）
  - 基本用法：
    ```bash
    python -m tools.export_policy \
      --solution artifacts/lp_solution.json \
      --out artifacts/policies \
      --debug-jsonl reports/policy_sample.jsonl  # 可选，仅导出少量样本
    ```
  - 行为摘要：
    - 读取解算产物中的 `nodes` 并输出 `preflop.npz/postflop.npz`；
    - 当解算阶段做过降阶，导出层按照 `meta.original_actions + original_index_map` 对“被劣汰动作”进行 0 权重回填，保证运行时/审计动作枚举一致；
    - NPZ `meta.node_meta` 含：`original_index_map`、`original_action_count_pre_reduction`、`reduced_shape`、`domination_steps`、`zero_weight_actions`。

- 烟囱验证（m2_smoke）
  - 基本用法：
    ```bash
    python -m tools.m2_smoke --out reports/m2_smoke.md --workspace . --quick --seed 123
    ```
  - 报告新增（G6）：
    - `small_engine_used_count=<int>`
    - `small_engine_used_ratio=<0..1>`
    - `small_methods_sample={"method": "analytic|linprog_small|na", "reduced_shape": [r,c]|null}`
  - 其他：报告仍包含 artifact 列表与 `solver_backend=value` 概要；新增行位于报告末尾，对现有解析脚本无影响。

-— 策略关键口径 —
- 赔率：`pot_odds = to_call / (pot_now + to_call)`；`pot_now = pot + sum(invested_street)`（不含本次待跟注）。
- SB vs 3bet 兜底：仅当 `pot_odds <= defend_threshold_ip`（默认 0.42）或三注极小（<2.2bb）时补跟，其余 fallback 直接弃牌。
- Flop 对大尺吋防守（改良）：面对 `two_third+`（含过池/全下），若无坚果优势且手牌不在 `{HC_VALUE, HC_STRONG_DRAW, HC_OP_TPTK}`：
  - `pot_odds ≤ 0.50` 且为中对/弱顶（`HC_TOP_WEAK_OR_SECOND|HC_MID_OR_THIRD_MINUS`）→ 直接跟注；
  - `0.50 < pot_odds ≤ 0.55` → 可选混频跟注（`SUGGEST_MIXING=on` 时启用，稳定哈希决定频率，受 MDF 轻微影响）；
  - `pot_odds > 0.55` → 弃牌；
  - 阈值可通过 `SUGGEST_FLOP_CALL_VS_LARGE_POTODDS`（默认 0.50）与 `SUGGEST_FLOP_FOLD_VS_LARGE_POTODDS`（默认 0.55）配置。

- Preflop 全下防守（新）：
  - 识别“纯 call/fold”节点（对手已全下）。
  - 组合表驱动（HU）：`packages/poker_core/suggest/config/preflop_vs_shove_HU.json` 按 `le12/13to20/gt20`（以 `to_call_bb` 为准）定义 `call/mix` 组合。
  - 决策：`call` → 必跟；`mix` → 开启混频（`SUGGEST_MIXING=on`）按固定频率跟注；否则回退到价格兜底（通常 fold）。
  - 元信息：`meta.vs_shove_band`、`meta.to_call_bb`；解释码复用 `PF_DEFEND_PRICE_OK`（带 `src=vs_shove`）。

- River 大尺吋防守（新，fallback）：
  - 使用 `river_semantics` 计算摊牌价值分层（`strong_value|medium_value|weak_showdown|air`）。
  - 面对 `two_third+`：
    - `strong_value` → 必跟；
    - `medium_value` → `pot_odds ≤ 0.50` 必跟；`0.50–0.52` 混频跟注（`SUGGEST_MIXING=on`）；否则弃牌；
    - `weak_showdown/air` → `pot_odds ≤ 0.30` 勉强跟注，否则弃牌；
  - 可调：`SUGGEST_RIVER_MEDIUM_CALL_POTODDS`（默认 0.50）、`SUGGEST_RIVER_MEDIUM_MIX_POTODDS`（默认 0.52）、`SUGGEST_RIVER_WEAK_CALL_POTODDS`（默认 0.30）。
- Flop 半诈唬/价值加注：`HC_STRONG_DRAW` 现可对 `third|half` 下注选择 `SizeSpec.tag("half")` 半诈唬加注；低 SPR (`le3`) 的 `HC_OP_TPTK` 面对 `third|half` 自动升级到 `two_third` 价值加注。
- 最小重开（postflop raise to‑amount）：若目标金额 < `raise.min`，提升至 `raise.min` → 再参与合法区间钳制（越界触发 `W_CLAMPED`）。
- 对抗三桶阈值：来自 `table_modes_{strategy}.json` 的 `threebet_bucket_small_le/mid_le`。
- SB 4‑bet：开关 `SUGGEST_PREFLOP_ENABLE_4BET=1` 才启用，读取 `SB_vs_BB_3bet` 的 `fourbet/call` 集合与 `fourbet_ip_mult/cap_ratio_4b`。

— 目录速览（Where to Change） —
- 引擎：`packages/poker_core/state_hu.py`
- 建议：`packages/poker_core/suggest/`
  - 服务：`service.py`（策略选择、Decision 解析/最小重开、clamp/告警、explanations 注入、debug.meta）
  - 策略：`policy_preflop.py`（RFI/防守/4bet）｜`policy.py`（flop/turn/river v1 与 v0.3）
  - 上下文/观测：`context.py`｜`observations.py`
  - 决策与工具：`decision.py`｜`calculators.py`｜`utils.py`
  - 教学解释：`explanations.py`
- 规则与表：`config/`（preflop ranges、flop/turn/river 规则 JSON）
- REST：`apps/web-django/api/`（`views_suggest.py`、`views_play.py`、`views_ui.py`）
- UI：`apps/web-django/templates/ui/`（错误/HUD/牌面/座位/日志/动作/金额/Coach）

— 最小升级（Minimal Upgrade） —
- 启用 preflop facing 键：运行时 node_key 现在会在翻前也携带 `facing=third|half|two_third+|na`（原逻辑强制 `na`）。旧表仍可命中（服务层会回退到 `facing=na`）。
- 翻前最小表（可选，一次性生成/更新）：
  ```bash
  python tools/build_preflop_min_table.py --out artifacts/policies/preflop.npz
  ```
  该最小表覆盖 `pot_type=limped/single_raised/threebet` × `role=na|caller|pfr` × `pos=ip|oop` × `facing=na|third|half|two_third+` × `hand=pair|Ax_suited|suited_broadway|broadway_offsuit|weak`。
- 三注池覆盖：新增工具 `tools/augment_policy_tables.py`，把 `postflop.npz` 中所有 `single_raised` 节点镜像为 `threebet` 节点并回写文件。
  - 用法：
    ```bash
    python tools/augment_policy_tables.py --in artifacts/policies/postflop.npz --out artifacts/policies/postflop.npz
    ```
  - 生效方式：
    ```bash
    export SUGGEST_POLICY_DIR=artifacts/policies
    # 正常启动/调用 suggest 即可；threebet 池在 flop/turn/river 将直接命中表。
    ```
  - 可选剥削开关（默认 none）：
    ```bash
    export SUGGEST_EXPLOIT_PROFILE=none   # 或 vs_allin
    ```
  - 验证：`pytest -q tests/test_policy_loader_threebet_nodes.py` 应通过，并在日志中看到 `policy_lookup_hit`。

— 测试与验证（Test） —
- 单元与集成：`python -m pytest -q` 覆盖 calculators/context/observations/策略子模块/Decision/服务整合。
- 快照回归：`tests/test_suggest_snapshots.py`（含 preflop/flop/turn/river 典型场景）。
- Turn/River 规则命中：`tests/test_turn_river_rulepath.py` 断言 `rule_path` 使用 `le3|3to6|ge6`。
- 规则检查（可选）：`python scripts/check_flop_rules.py --all`、`node scripts/check_preflop_ranges.js --dir packages/poker_core/suggest/config`。

— Tips —
- 自定义盲注：在 `POST /api/v1/session/start` 传 `{sb, bb}`。
- 常见 409：非当前行动者或手牌已结束；先 `GET /hand/state` 查看 `to_act/street`。
- 教学/实战切换：对局页头部 Teach 开关（默认 ON），后端持久化偏好并用 OOB 刷新视图。

— 变更记录（本 PR） —
- 新增 explanations 渲染（中文），服务层注入 `resp.explanations`。
- Preflop v1 路径统一 `meta.plan`；SB vs 3bet 支持 4bet。
- Flop v1：value‑raise JSON 化与 `rule_path` 追踪。
- Turn/River v1：规则加载与策略接入，统一 `size_tag/mdf/pot_odds/facing_size_tag/plan`；修复 SPR 键映射命中 JSON。
- 统一“最小重开”码名为 `FL_MIN_REOPEN_ADJUSTED`（详见 `packages/poker_core/suggest/MIGRATION_GUIDE.md`）。
