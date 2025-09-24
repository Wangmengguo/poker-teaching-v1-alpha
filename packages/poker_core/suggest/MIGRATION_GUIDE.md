# Suggest v1 重构变更日志 / 迁移指南（Turn/River 预备）

## 背景
- 目标：统一尺寸/阈值/上下文/元信息与日志，降低跨街策略维护成本，强化教学可解释性。
- 产出：Decision 契约、SuggestContext、Observation 拆分、rule_path 追踪、快照回归。

## 关键变更
- 决策契约（新增）：`Decision(action, SizeSpec)`，由策略表达尺寸“意图”，服务/resolve 统一换算金额；最小重开在 `Decision.resolve` 中抬高并追加 `FL_MIN_REOPEN_ADJUSTED`。
- 上下文（新增）：`SuggestContext.build()` 加载表与开关（modes/open/vs + env），策略层不再 `os.getenv`。
- 观察（升级）：`observations.py` 按街构建 Observation，新增 `pot_now/first_to_act/last_to_act/facing_size_tag/last_bet/last_aggressor`。
- 评估统一：`hand_strength.py` 将翻前标签与翻后六桶统一为 `HandStrength`。
- 规则追踪：flop 返回 `meta.rule_path`。

## 对外契约（保持不变）
- `build_suggestion` 仍返回 `{hand_id, actor, suggested{action,amount?}, rationale[], policy, meta?}`。
- 仅新增 meta 字段（例如 `rule_path/cap_bb`），不会移除历史字段。

## 迁移范式（Turn/River）
1) 策略产出 Decision
- turn/river 策略函数内部以 `Decision(action, SizeSpec.tag|bb|amount)` 表达尺寸；策略不做金额钳制。
- 元信息：继续通过 `meta` 返回 `size_tag`/`rule_path`/阈值辅助信息（如 MDF、计划文案等）。

2) 统一阈值与尺寸
- 价格/防守：统一用 `calculators.pot_odds/mdf`；表阈值从 `obs.context.modes['HU']` 读取。
- 尺寸：翻前优先 `SizeSpec.bb`，翻后优先 `SizeSpec.tag`；必要时 `SizeSpec.amount`。

3) 规则路径
- 参考 flop，补充 `_match_rule_with_trace`（或等价实现），在 `meta.rule_path` 记录命中路径。

4) 服务层集成
- 服务层已支持 `Decision` 直通：策略可返回 `Decision` 或 `(Decision, rationale, policy_name, meta)`；其它保持 tuple 兼容。

5) TDD 流程建议
- 先写 contract 测试（Decision→金额→min‑reopen→clamp），再写规则 trace 测试，最后补快照样例。
- 脚本 Gate：`scripts/check_flop_rules.py` 可作为 turn/river 的参考实现方式（建议新增 turn/river 对应 Gate）。

## 注意事项/坑位
- pot_now 口径：始终使用 `to_call/(pot_now+to_call)`；确保 `Observation.pot_now` 注入完备。
- 最小重开：避免策略内手动追加 rationale；由 Decision.resolve 统一追加 `PL_MIN_REOPEN_LIFT`。
- clamp 提示：服务层仅在金额超出合法区间时追加一次 `WARN_CLAMPED`。
- 规则 defaults：当 trace 中出现 `defaults:*`，说明当前层缺失规则；请优先补齐 JSON，而非在代码内硬编码。

## 文件索引
- 上下文/计算：packages/poker_core/suggest/context.py、packages/poker_core/suggest/calculators.py、packages/poker_core/suggest/decision.py
- 观察/评估：packages/poker_core/suggest/observations.py、packages/poker_core/suggest/hand_strength.py
- 策略：packages/poker_core/suggest/policy_preflop.py、packages/poker_core/suggest/policy.py（flop）
- 服务：packages/poker_core/suggest/service.py
- 规则/表与脚本：packages/poker_core/suggest/flop_rules.py、packages/poker_core/suggest/preflop_tables.py、scripts/check_flop_rules.py

## 里程碑与验证
- 单测：`pytest -q`；快照：`tests/test_suggest_snapshots.py`；Gate：`scripts/check_flop_rules.py --all`。
- 日志/调试：`SUGGEST_DEBUG=1` 查看 `debug.meta.rule_path/size_tag/open_bb/reraise_to_bb/cap_bb/pot_odds`。

## 附：典型迁移片段（伪代码）
```python
# 原：直接返回 dict
return {"action": "bet", "amount": size_to_amount(...)}, rationale, "turn_v1", {"size_tag": "half"}

# 新：返回 Decision
from poker_core.suggest.decision import Decision, SizeSpec

return (
    Decision(action="bet", sizing=SizeSpec.tag("half"), meta={"size_tag": "half", "rule_path": path}),
    rationale,
    "turn_v1",
    {},
)
```
