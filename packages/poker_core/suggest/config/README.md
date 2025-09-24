This folder contains built-in configuration files for v1 policies with three strategies:
- **loose**: Aggressive strategy with wider ranges
- **medium**: Balanced strategy (default)
- **tight**: Conservative strategy with narrower ranges

Each strategy includes:
- `table_modes_{strategy}.json`: Table mode parameters
- `ranges/preflop_open_HU_{strategy}.json`: Opening ranges
- `ranges/preflop_vs_raise_HU_{strategy}.json`: Facing raise ranges

Teaching explanations (locale)
- `explanations_zh.json`: Mapping from rationale `code` to Chinese templates used to render `resp.explanations`.

At runtime:
- Use `SUGGEST_STRATEGY` environment variable to select strategy (loose/medium/tight)
- Use `SUGGEST_CONFIG_DIR` to override with external configuration directory

The medium strategy is used by default when no environment variables are set.

SB vs BB 3-bet (4-bet) support
- In `ranges/preflop_vs_raise_HU_{strategy}.json`, add an optional `SB_vs_BB_3bet` section with buckets `small|mid|large` and keys:
  - `fourbet`: list of 169-grid combos to 4-bet
  - `call`: list of combos to flat the 3-bet
- The loader is backward-compatible with a legacy `reraise` key and will treat it as `fourbet`.

Sizing parameters
- Add to `table_modes_{strategy}.json` (under `HU`):
  - `fourbet_ip_mult` (default 2.2)
  - `fourbet_oop_mult` (reserved)
  - `cap_ratio_4b` (default to `cap_ratio`)
  - `threebet_bucket_small_le` (default 9): 3-bet "to" amount (bb) threshold for small bucket
  - `threebet_bucket_mid_le` (default 11): 3-bet "to" amount (bb) threshold for mid bucket

Runtime toggle
- Set `SUGGEST_PREFLOP_ENABLE_4BET=1` to enable the SB 4-bet path in policy v1.
- Set `SUGGEST_LOCALE=zh` to select explanation language (defaults to `zh`).
