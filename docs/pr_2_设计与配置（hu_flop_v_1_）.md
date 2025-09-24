# PR‑2 设计与配置（HU Flop v1）

> 目标：仅修改 `packages/poker_core/suggest/*`，在 **v1 策略**下新增 **Flop v1**（Heads‑Up），**先支持单加注底池**；3bet 底池与 overbet 延后到 **v1.1**。
>
> 约束：**不改 DRF/UI 与 API 契约**；维持“可配置、可解释、可灰度、可 Gate”，尺寸采用模板 `third/half/two_third/pot`；**raise 以 to‑amount 口径**，做 **min‑reopen + 钳制**。

---

## 1. 范围与兼容

- 改动边界：仅 `poker_core/suggest/*`。
- 路由：当 `SUGGEST_POLICY_VERSION in {v1, auto(命中)}` 且 `street=='flop'` → `policy.flop_v1`；否则沿用 `postflop_v0_3`。
- 契约：
  - 顶层沿用：`confidence: float`；
  - **Flop 返回 **``（金额由 `service` 统一换算与钳制）；
  - `rationale[]` 兼容 `code/msg/data`，可附 `severity/message/meta`；
  - Preflop 的 `meta.open_bb/reraise_to_bb` 不变；**Flop 新增 **``（仅在相关时返回）。

---

## 2. 观测输入（Observation 最小集合）

- **位置/视角**：`ip: bool`（已在 PR‑0），`position` 仅用于解释。
- **底池类型**：`pot_type ∈ {single_raised, threebet}`（v1 仅 `single_raised`，v1.1 扩展）。
- **SPR**：`spr_bucket ∈ {le3, 3to6, ge6}`（已在 PR‑0）。
- **牌面纹理（极简）**：`board_texture ∈ {dry, semi, wet}`，并保留细项：`paired:bool`、`fd:bool`（两同花）、`sd:bool`（连通）。
- **手牌标签（建议来自 analysis，策略内也可兜底判定）**：
  - 牌力：`air`、`third_pair_minus`、`second_pair`、`top_pair`、`overpair`、`two_pair_plus`、`set`、`nuts`；
  - 听牌：`oesd`、`gs`（含 `bdsd` 标记）、`nfd`、`fd`、`bdfd`、`two_way_draw`（如 NFD+OESD）；
  - 阻断：`nut_blocker`（如 A♣ 持有）。
- **价格字段**：`pot_now`、`to_call`（服务层统一口径），供 pot‑odds/MDF 简化线使用。

---

## 3. 规则引擎（表驱动）

### 3.1 决策矩阵（核心维度）

- 维度：`pot_type × texture × ip/oop × hand_class × spr_bucket → {primary_action, size_tag, note?}`
- **不混频**（v1.0）：每格给出单一“首选线”（集合决策）。
- **两条主线**：
  - **无人下注线**（Hero 首说）：c‑bet / 延迟 c‑bet / 过牌；
  - **面对下注线**：`fold/call/raise`，call 先过价格线（pot‑odds / 简化 MDF），raise 只对 `value`（two pair+）与 `强听` 开启。
- **多人池收紧占位**：若 `active_player_count>2`（当前 HU 恒 2），自动附 `MWP_TIGHTEN_UP`，降一级行动（如 `bet→check` 或 `two_third→third`）。

### 3.2 首版覆盖（80/20）

- **干面（dry：K72r/A83r）**：
  - IP：`overpair/top_pair_strong` → `bet third`；`top_pair_weak/middle_pair` → `bet third` 为主；`air` 多 `check`。
  - OOP：价值可 `bet third`，多数线 `check` 或 `check/call`。
- **半湿（semi：KJ2r/QT4r/982r）**：
  - IP：价值与强听 `bet half`；边缘对降低频率或 `check`。
  - OOP：价值/强听 `bet half`；边缘 `check/call`。
- **湿面（wet：T9♠8♠/J♣T♣9♦）**：
  - IP：`monster/强听` → `bet two_third/pot`；边缘多 `check`，减少被加注。
  - OOP：多 `check`；`monster/强听` 少量 `bet two_third`；`中弱对` 倾向 `check/call`。
- **SPR 导向**：
  - **低 SPR（≤3）**：价值升档 `two_third/pot`（`FL_LOW_SPR_VALUE_UP`）。
  - **高 SPR（≥6）**：边缘与弱听优先控池（`FL_HIGH_SPR_CTRL`）。

> 未命中格子 → 回退到 `texture × ip/oop` 的默认线（如 dry+IP 默认 `bet third`；wet+OOP 默认 `check`）。

---

## 4. 金额与 size\_tag

- `size_tag → amount`：`utils.size_to_amount(pot, last_bet, size_tag, bb)` 计算，再由 `service` 统一钳制。
- 建议映射：`third≈0.33P / half≈0.50P / two_third≈0.67P / pot≈1.00P`（四舍五入后进入钳制）。
- **Raise（to‑amount 口径）**：
  - 基于对手当前 **to‑amount** 与 `table_modes_{strategy}.json` 的 `reraise_ip_mult/reraise_oop_mult` 计算目标 to；
  - 执行顺序：**min‑reopen 提升 → cap（**``**）→ service 钳制**；
  - 若触发提升，附 `FL_MIN_REOPEN_ADJUSTED`；若被钳制，附 `W_CLAMPED`。

---

## 5. 解释码（codes 扩展）

- `FL_CBET_DRY_THIRD`（干面小额 c‑bet）
- `FL_CBET_WET_HALF`（湿/半湿中等 c‑bet）
- `FL_CHECK_RANGE`（区间优势不明显/纹理不利，选择过牌）
- `FL_RAISE_VALUE`（价值加注）
- `FL_RAISE_SEMI_BLUFF`（强听半诈唬加注）
- `FL_CALL_POTODDS_OK`（锅赔率允许跟注）
- `FL_FOLD_POTODDS_BAD`（价格不足弃牌）
- `FL_DRY_CBET_THIRD` / `FL_SEMI_CBET_HALF` / `FL_WET_VALUE_PROTECT` / `FL_WET_CHECK_CALL`
- `FL_LOW_SPR_VALUE_UP` / `FL_HIGH_SPR_CTRL`
- `FL_MULTIWAY_TIGHTEN` / `FL_NO_LEGAL_BET_PATH` / `FL_MIN_REOPEN_ADJUSTED` / `W_CLAMPED`

> 兼容 `code/msg/data` 键，新增 `message/severity/meta` 可选。

---

## 6. 置信度模型（简版）

- 基础：命中规则格 +0.3；命中纹理默认线 +0.2；
- SPR 调整：低 SPR 价值提升 +0.05；高 SPR 控池 +0.05；
- 边界：`amount` 被钳制 −0.1；无合法 bet 回退 −0.1；
- 剪裁到 `[0.5, 0.9]`。

---

## 7. 配置结构（可直接落库）

```
packages/poker_core/suggest/config/
  ├─ flop_medium/
  │   ├─ table_modes_medium.json
  │   ├─ rules_ip.json
  │   └─ rules_oop.json
  ├─ flop_tight/ …
  └─ flop_loose/ …
```

### 7.1 `table_modes_{strategy}.json`（示例）

```json
{
  "spr_thresholds": {"le3": 3.0, "ge6": 6.0},
  "reraise_ip_mult": 2.6,
  "reraise_oop_mult": 2.8,
  "cap_ratio_postflop": 0.9,
  "size_map": {"third": 0.33, "half": 0.5, "two_third": 0.67, "pot": 1.0}
}
```

### 7.2 `rules_ip.json / rules_oop.json`（示例片段）

```json
{
  "single_raised": {
    "dry": {
      "le3": {
        "overpair":        {"action":"bet","size_tag":"third"},
        "top_pair":        {"action":"bet","size_tag":"third"},
        "air":             {"action":"check"}
      },
      "3to6": { "top_pair": {"action":"bet","size_tag":"third"} },
      "ge6":  { "top_pair": {"action":"bet","size_tag":"third"}, "air": {"action":"check"} }
    },
    "wet": {
      "le3": {"monster": {"action":"bet","size_tag":"two_third"}, "strong_draw": {"action":"bet","size_tag":"two_third"}},
      "3to6": {"top_pair": {"action":"check"}}
    }
  }
}
```

> v1.0 仅 `single_raised`；`threebet` 键留空占位，v1.1 再补。每格只给首选线；未命中走 `defaults`。

---

## 8. `utils` 与 `service` 需做的最小改动

- `utils`：
  - `classify_flop(board)` 已存在占位 → 输出 `{texture, paired, fd, sd}`；
  - `infer_hand_class(obs)`（极简版，可选）：若上游已有 hand\_class，可直接透传；否则用规则近似（两对+/set、NFD/OESD、顶对判定等）。
  - `size_to_amount(...)`：按 §4 实现锅份额换算。
- `service`：
  - v1 路由 `flop → flop_v1`；
  - 合并 `size_tag/confidence` 到顶层；
  - `debug.meta` 增加：`texture/paired/fd/sd/hand_class/spr_bucket/plan`；
  - 结构化日志 extra：`street=flop, size_tag, texture, spr_bucket, hand_class, policy_name`。

---

## 9. 测试（建议 20\~24 条）

**黄金用例（示例 12 条）**

1. dry+IP+`top_pair_weak` → `bet third`（`FL_DRY_CBET_THIRD`）
2. dry+OOP+`top_pair_strong` → `bet third`
3. dry+IP+`air` → `check`（`FL_CHECK_RANGE`）
4. semi+IP+`strong_draw` → `bet half`（`FL_SEMI_CBET_HALF`）
5. semi+OOP+`middle_pair` → `check`（面向 `check/call` 计划）
6. wet+IP+`monster` → `bet two_third`（`FL_WET_VALUE_PROTECT`）
7. wet+IP+`top_pair_weak` → `check`
8. wet+OOP+`strong_draw` → `check`（`FL_WET_CHECK_CALL`）
9. 低 SPR（≤3）+任意纹理+`overpair` → `two_third`（`FL_LOW_SPR_VALUE_UP`）
10. 高 SPR（≥6）+semi+`weak_draw` → `check`（`FL_HIGH_SPR_CTRL`）
11. `bet` 非法 → 自动回退 `check` + `FL_NO_LEGAL_BET_PATH`
12. **min‑reopen + 钳制并发**：raise 先被提升到 `raise.min`，再被 `cap` 或合法上限钳制（同时出现 `FL_MIN_REOPEN_ADJUSTED` 与 `W_CLAMPED`）

**边界用例（示例 10 条）**

- `size_tag→amount` 被钳制（过小/过大） → 仍返回 bet，附 `W_CLAMPED`、confidence−0.1
- `texture` 无法识别（牌面不足）→ 走 `defaults`
- `hand_class` 识别失败 → 走 `defaults`
- `spr_bucket` 为 `na` → 不触发 value\_up/control
- `paired board` 的 `air`：IP `third` 频率下降（按表）
- `fd`=true 且 `top_pair_weak`：IP `third`；OOP `check`
- `sd`=true 且 `air`：IP `check`
- `monster` 但 `bet` 不合法 → `check` 回退
- `active>2`（模拟）→ 触发 `FL_MULTIWAY_TIGHTEN`
- `pot_type=threebet`（暂未支持）→ 走 `single_raised` 默认或保守回退（并在 debug 标注占位）

---

## 10. 灰度与回退

- 与 Preflop v1 一致：
  - `SUGGEST_POLICY_VERSION=v1_preflop` → 仅 Preflop；
  - `SUGGEST_POLICY_VERSION=v1` → Preflop+Flop；
  - `SUGGEST_POLICY_VERSION=auto` + `SUGGEST_V1_ROLLOUT_PCT` → 稳定散列灰度。
- 回退：设置为 `v0` 或将 `rollout_pct=0`。

---

## 11. 校验脚本（CI Gate）

- **目标**：校验 `flop_rules_*.json` 的 schema、键覆盖率与 `size_tag` 合法性；统计默认线命中率；（PR‑2）仅 Gate `medium`，随后全量。
- **检查项**（零依赖 Node）：
  - 结构：包含 `single_raised`；`texture ∈ {dry,semi,wet}`；每个 texture 下包含 `le3/3to6/ge6`；动作键只允许 `action/size_tag`；
  - 值域：`size_tag ∈ {third,half,two_third,pot}`；
  - 覆盖：对 `ip/oop` 至少提供默认线；
  - （可选）跨档单调：`loose ⊇ medium ⊇ tight`（动作集合层面，不强制尺寸一致）。
- **示例输出**：随机 10 牌面 × 2 手牌类别 → 建议与尺寸样例（仅打印不 Gate）。

---

## 12. 运维与本地验证

- 环境：
  - `SUGGEST_POLICY_VERSION=v1`（或 `auto + SUGGEST_V1_ROLLOUT_PCT=5`）
  - `SUGGEST_CONFIG_DIR=/path/to/config`（可选，含 `postflop/`）
  - `SUGGEST_DEBUG=1` 观察 `debug.meta`（texture/hand\_class/size\_tag/spr\_bucket/plan）
- 调试脚本（可选）：
  - `scripts/suggest_debug_tool.py single --street flop --policy v1 --debug 1` 输出一次决策；
  - `dist --street flop --pct 10 --show-sample 8` 查看分布。

---

## 13. 教学提示（落地 UI 可视化）

- 在建议卡片中展示：`size_tag`、`texture`、`hand_class`、`SPR`、`IP/OOP` 与一句话计划（rationale 拼装）。
- 典型对话：
  - “干面 IP 顶对，推荐三分之一持续下注（价值+保护）。”
  - “湿面 OOP 顶对弱踢，建议过牌跟注，控制底池，等待安全转牌。”

---

## 14. 小测（Quiz）

1. **K72r，BTN 持 KQo（IP），SPR=5**：首选线与 size\_tag 是？为什么。
2. **T9♠8♠，BB 持 A♠Q♦（OOP），SPR=8**：是下注还是过牌？
3. **A83r，CO 持 99（IP），SPR=2.5**：应如何调整 size？
4. **QJ7♣，IP 持 A♣T♣（NFD+GS），SPR=6**：为何 `half` 往往优于 `third`？
5. **J73 一同花，OOP 持 JTo，SPR=7**：为什么更多时候是 `check/call`？

> 评估口径：是否识别纹理与 SPR 档、是否能给出 size\_tag 与理由（价值/保护/控池）。

---

## 15. 实施步骤（S1→S5）

- **S1（本 PR）**：`flop_rules_medium/` 与 `table_modes_medium.json`、加载器；`policy.flop_v1` 骨架（单加注底池），bet/raise 尺寸、min‑reopen+钳制、解释/置信度与 debug.meta；黄金用例 12 条 + 边界 10 条。
- **S2（下一 PR）**：补 `flop_rules_loose/tight/`，启用“跨档单调” Gate；调参达到目标分布（可观测指标在 README）。
- **S3**：3bet 底池（v1.1）：加 `pot_type=threebet` 的规则块（更轴化与更大尺寸），开启 overbet（可选）。
- **S4**：混频占位（可选）：对少数格子允许 60/40 掷签（稳定散列），debug 展示；
- **S5**：5% 灰度（`v1`），观察 `W_CLAMPED/FL_NO_LEGAL_BET_PATH` 占比与 `confidence` 直方图，必要时热更表；随时回退。

---

### ✅ 交付后可立即操作

- 用 `SUGGEST_POLICY_VERSION=v1`（或 `auto+pct`）在测试服启用 Flop v1；
- 通过 `SUGGEST_CONFIG_DIR=.../flop_medium/` 切入 medium 档；
- 开 `SUGGEST_DEBUG=1`，核对 `postflop_size_tag/texture/hand_class/spr_bucket/plan` 与 raise to‑amount 的调试字段。

