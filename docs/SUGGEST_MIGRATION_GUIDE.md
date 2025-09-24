# Suggest v1 重构变更日志 / 迁移指南（Docs 版）

本页为项目文档导航版本，内容与代码库内的迁移指南一致：packages/poker_core/suggest/MIGRATION_GUIDE.md。

## 关键变更
- 决策契约 Decision：策略以 `Decision(action, SizeSpec)` 表达尺寸意图（翻前用 `bb`，翻后用 `size_tag`），`Decision.resolve` 统一金额换算并在需要时追加 `PL_MIN_REOPEN_LIFT`。
- 统一上下文 SuggestContext：集中加载策略档/表格/开关，并在 debug/log 输出 `config_versions/profile/strategy`。
- 观察与评估：`observations.py` 按街构建 Observation，补齐 `pot_now/first_to_act/last_to_act/facing_size_tag/last_bet/last_aggressor`；`hand_strength.py` 标准化翻前/翻后强度。
- 规则命中路径：flop 在 `meta.rule_path` 返回命中链路（例：`single_raised/role:pfr/ip/dry/le3/value_two_pair_plus/facing.half`）。

## 对外契约
- `build_suggestion` 返回结构不变：`{hand_id, actor, suggested{action,amount?}, rationale[], policy, meta?}`；仅新增 meta 字段。

## 迁移范式（面向 turn/river）
1) 策略产出 Decision：以 `Decision(action, SizeSpec.tag|bb|amount)` 表达尺寸，不做金额钳制；通过 `meta` 返回 `size_tag/rule_path/MDF 等`。
2) 统一阈值与尺寸：`calculators.pot_odds/mdf` + `obs.context.modes['HU']`；翻前 `bb`，翻后 `size_tag`。
3) 规则路径：复用 `_match_rule_with_trace` 产出 `meta.rule_path`。
4) 服务层：已支持 Decision 直通；策略可返回 `Decision` 或 `(Decision, rationale, policy_name, meta)`。
5) TDD 流：先写 contract 测试（金额/最小重开/Clamp），再写 trace 测试，最后加快照样例。

## 注意事项
- 赔率口径：`pot_odds = to_call / (pot_now + to_call)`；确保 `Observation.pot_now` 与 `last_bet` 注入。
- 最小重开：统一由 `Decision.resolve` 追加 `PL_MIN_REOPEN_LIFT`。
- Clamp：服务层仅在越界时追加一次 `WARN_CLAMPED`。
- 规则缺省：trace 出现 `defaults:*` 表示缺规则，优先补 JSON。

## 文件索引（精选）
- 上下文/计算：`suggest/context.py`、`suggest/calculators.py`、`suggest/decision.py`
- 观察/评估：`suggest/observations.py`、`suggest/hand_strength.py`
- 策略：`suggest/policy_preflop.py`、`suggest/policy.py`（flop）
- 服务：`suggest/service.py`
- 脚本：`scripts/check_flop_rules.py`

## 典型迁移片段
```python
# 原：直接返回金额 dict
return {"action": "bet", "amount": size_to_amount(...)}, rationale, "turn_v1", {"size_tag": "half"}

# 新：返回 Decision（服务层统一解析金额/最小重开）
from poker_core.suggest.decision import Decision, SizeSpec
return (
    Decision(action="bet", sizing=SizeSpec.tag("half"), meta={"size_tag": "half", "rule_path": path}),
    rationale,
    "turn_v1",
    {},
)
```
