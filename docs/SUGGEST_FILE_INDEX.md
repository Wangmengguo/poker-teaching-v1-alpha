# Suggest 模块 — 主要文件与入口索引（v1）

- 上下文与计算
  - packages/poker_core/suggest/context.py — SuggestContext 构建与版本/开关快照
  - packages/poker_core/suggest/calculators.py — pot_odds/mdf/size 统一计算
  - packages/poker_core/suggest/decision.py — Decision + SizeSpec（金"额"推导与最小重开）

- 观察与评估
  - packages/poker_core/suggest/observations.py — 分街构建 Observation（pot_now/last_bet 等）
  - packages/poker_core/suggest/hand_strength.py — 统一手牌强度标签（翻前/翻后）

- 策略（v1）
- packages/poker_core/suggest/policy_preflop.py — SB 首攻/BB 防守/SB vs 3bet 子策略（含 pot_odds 阈值兜底）
- packages/poker_core/suggest/policy.py — policy_preflop_v1 协调器；policy_flop_v1（MDF + 大尺吋弃牌门槛 + 半诈唬/低 SPR 价值加注）

- 规则与表
  - packages/poker_core/suggest/flop_rules.py — flop 规则加载
  - packages/poker_core/suggest/preflop_tables.py — 翻前表加载（open/vs）
  - packages/poker_core/suggest/config_loader.py — JSON 带 TTL+mtime 缓存加载
  - packages/poker_core/suggest/config/ — 策略档位与范围 JSON（含 README）

- 服务、类型、代码表
  - packages/poker_core/suggest/service.py — 建议入口，整合策略/resolve/clamp/debug/log
  - packages/poker_core/suggest/types.py — Observation/PolicyConfig/SizeTag 类型
  - packages/poker_core/suggest/codes.py — rationale code 定义与工厂

- 校验脚本
  - scripts/check_flop_rules.py — flop 规则 Gate（--all 支持三档）
  - scripts/check_preflop_ranges.js — 翻前范围 CI Gate
