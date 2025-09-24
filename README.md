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

# 调试
export SUGGEST_DEBUG=1                    # 返回 debug.meta（pot_odds/size_tag/rule_path 等）
export SUGGEST_CONFIG_DIR=packages/poker_core/suggest  # 可外置覆盖配置
export SUGGEST_TABLE_MODE=HU
```

— 调试脚本 —
- 单次：`python scripts/suggest_debug_tool.py single --policy auto --pct 10 --debug 1 --seed 42 --button 0`
- 灰度分布：`python scripts/suggest_debug_tool.py dist --policy auto --pct 10 --debug 1 --count 2000 --show-sample 8`

-— 策略关键口径 —
- 赔率：`pot_odds = to_call / (pot_now + to_call)`；`pot_now = pot + sum(invested_street)`（不含本次待跟注）。
- SB vs 3bet 兜底：仅当 `pot_odds <= defend_threshold_ip`（默认 0.42）或三注极小（<2.2bb）时补跟，其余 fallback 直接弃牌。
- Flop 对大尺吋防守：面对 `two_third+`、无坚果优势且手牌不在 `{HC_VALUE, HC_STRONG_DRAW, HC_OP_TPTK}` 时，`pot_odds > 0.40` 触发保守弃牌。
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

— 测试与验证（Test） —
- 单元与集成：`pytest -q` 覆盖 calculators/context/observations/策略子模块/Decision/服务整合。
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
