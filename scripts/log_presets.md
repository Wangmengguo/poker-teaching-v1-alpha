Log Aggregation Presets (Flop v1+)

Purpose: speed up gray rollout by pinning common group-bys and guardrail alerts. The backend can be ELK/Loki/Datadog; fields below match our structured log emitted by packages/poker_core/suggest/service.py (event name "suggest_v1").

Group-by dimensions
- street
- board_texture (aka texture)
- role (pfr|caller|na)
- spr_bucket (le3|3to6|ge6|na)
- size_tag (third|half|two_third|pot)
- hand_class6 (value_two_pair_plus|overpair_or_top_pair_strong|top_pair_weak_or_second_pair|middle_pair_or_third_pair_minus|strong_draw|weak_draw_or_air)
- plan (short text; safe to use as facet with top-N limiting)

Core counters / rates
- total_suggests: count by window
- clamped_count: count(code==W_CLAMPED) or extra.clamped==true (keep using rationale code)
- fallback_count: count(code==CFG_FALLBACK_USED)
- min_reopen_adjusted_count: count(code==FL_MIN_REOPEN_ADJUSTED)
- raise_share: share(action in {raise})
- bet_share: share(action==bet)
- check_share: share(action==check)

Guardrail thresholds (initial; tune per env)
- clamped_rate = clamped_count/total_suggests > 5% WARN, >10% ALERT
- fallback_rate = fallback_count/total_suggests > 1% WARN, >3% ALERT
- min_reopen_adjusted_rate > 5% WARN（金额口径需要复核尺寸|cap 配置）

Example pseudo-queries
- By texture+role: rate timechart
  filter service="suggest" and event="suggest_v1" and street="flop"
  group by board_texture, role | stats count(), sum(has_code_W_CLAMPED), sum(has_code_CFG_FALLBACK_USED)

Tips
- Slice by strategy (extra.strategy) and config_profile to compare builtin vs external configs.
- Use size_tag to detect unintended sizing spikes after config changes.

