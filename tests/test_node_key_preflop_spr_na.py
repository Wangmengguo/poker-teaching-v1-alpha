from poker_core.state_hu import start_hand
from poker_core.state_hu import start_session
from poker_core.suggest.node_key import node_key_from_observation
from poker_core.suggest.observations import build_observation


def test_preflop_node_key_uses_spr_na():
    cfg = start_session(init_stack=200, sb=1, bb=2)
    gs = start_hand(cfg, session_id="s1", hand_id="h1", button=0, seed=123)
    # SB acts first preflop; legal_actions由obs builder内部获取
    obs, _ = build_observation(gs, actor=0, acts=[])
    key = node_key_from_observation(obs)
    assert key.startswith("preflop|"), key
    assert "spr=na" in key, key
