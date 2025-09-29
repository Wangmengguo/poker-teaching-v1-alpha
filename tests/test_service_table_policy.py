from poker_core.domain.actions import LegalAction
from poker_core.suggest.policy_loader import PolicyEntry
from poker_core.suggest.service import _build_table_policy


def test_build_table_policy_handles_missing_size_tags() -> None:
    entry = PolicyEntry(
        node_key="node",
        actions=("bet", "check"),
        weights=(0.7, 0.3),
        size_tags=(),
        meta={"size_tag": "half"},
        table_meta={"version": "v1"},
        raw_weights=(0.7, 0.3),
    )

    acts = [
        LegalAction(action="bet"),
        LegalAction(action="check"),
    ]

    result = _build_table_policy(entry, acts)
    assert result is not None
    suggested, rationale, policy_name, meta = result

    assert suggested == {"action": "bet", "size_tag": "half"}
    assert rationale == []
    assert policy_name == "v1_table"
    assert meta["size_tag"] == "half"
