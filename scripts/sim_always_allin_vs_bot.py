"""
Simulate: Human always all-in vs bot (v1 suggest)

Run:
  SUGGEST_POLICY_VERSION=v1 python scripts/sim_always_allin_vs_bot.py --sessions 50 --hands 60 --seed 123

Outputs aggregate win/loss count and mean PnL for the human (seat 0).
"""

from __future__ import annotations

import argparse
import os
import random
from dataclasses import dataclass

from poker_core.session_flow import next_hand
from poker_core.session_types import SessionView
from poker_core.state_hu import apply_action
from poker_core.state_hu import legal_actions as engine_legal_actions
from poker_core.state_hu import settle_if_needed
from poker_core.state_hu import start_hand
from poker_core.state_hu import start_hand_with_carry
from poker_core.state_hu import start_session
from poker_core.suggest.service import build_suggestion


@dataclass
class Result:
    hands_played: int
    final_stacks: tuple[int, int]
    pnl: tuple[int, int]
    ended_reason: str


def _play_hand(gs, human: int) -> object:
    """Play a single hand until completion; human always all-ins on their turns."""
    while getattr(gs, "street", None) != "complete":
        actor = getattr(gs, "to_act", None)
        if actor is None:
            break
        if int(actor) == int(human):
            # Human: always jam when legal; otherwise take the most "jam-like" option
            la = set(engine_legal_actions(gs))
            if "allin" in la:
                gs = apply_action(gs, "allin")
            elif "call" in la:
                gs = apply_action(gs, "call")
            elif "check" in la:
                gs = apply_action(gs, "check")
            else:
                # Fallback to any legal (fold as last resort)
                name = next(iter(la)) if la else "check"
                gs = apply_action(gs, name)
        else:
            # Bot: use suggest service
            resp = build_suggestion(gs, actor)
            sug = resp.get("suggested") or {}
            act = str(sug.get("action"))
            amt = sug.get("amount")
            if amt is None:
                gs = apply_action(gs, act)  # check/call/fold
            else:
                gs = apply_action(gs, act, int(amt))
        gs = settle_if_needed(gs)
        if getattr(gs, "street", None) == "complete":
            break
    return gs


def simulate_session(*, seed: int, max_hands: int = 60, init_stack: int = 200) -> Result:
    # Ensure v1 policies (safer defaults)
    os.environ.setdefault("SUGGEST_POLICY_VERSION", "v1")
    # Optionally enable mixing to avoid deterministic over-exploitation
    os.environ.setdefault("SUGGEST_MIXING", "on")

    cfg = start_session(init_stack=init_stack, sb=1, bb=2)
    # Randomize initial button for variety
    button = random.Random(seed).randint(0, 1)
    session_id = f"s_{seed}"

    # First hand
    hand_id = f"h_{seed}_1"
    gs = start_hand(cfg, session_id=session_id, hand_id=hand_id, button=button, seed=seed)

    human = 0  # seat 0 as human
    hands_played = 0
    for _ in range(max_hands):
        hands_played += 1
        gs = _play_hand(gs, human=human)
        # Bust check
        s0, s1 = gs.players[0].stack, gs.players[1].stack
        if s0 <= 0 or s1 <= 0:
            reason = "bust"
            break

        # Plan next hand (button rotates, stacks carry)
        sv = SessionView(
            session_id=session_id, button=button, stacks=(s0, s1), hand_no=hands_played
        )
        plan = next_hand(sv, gs, seed=seed + hands_played)
        button = plan.next_button
        new_hid = f"h_{seed}_{hands_played+1}"
        try:
            gs = start_hand_with_carry(
                cfg,
                session_id=session_id,
                hand_id=new_hid,
                button=button,
                stacks=plan.stacks,
                seed=seed + hands_played,
            )
        except ValueError:
            # Someone cannot post blinds → treat as bust
            reason = "bust"
            break
    else:
        reason = "max_hands"

    final = (gs.players[0].stack, gs.players[1].stack)
    pnl = (final[0] - init_stack, final[1] - init_stack)
    return Result(hands_played=hands_played, final_stacks=final, pnl=pnl, ended_reason=reason)


def main() -> int:
    p = argparse.ArgumentParser(description="Simulate: human always all-in vs bot (v1)")
    p.add_argument("--sessions", type=int, default=50, help="Number of independent sessions")
    p.add_argument("--hands", type=int, default=60, help="Max hands per session")
    p.add_argument("--seed", type=int, default=123, help="Base RNG seed")
    p.add_argument("--init-stack", type=int, default=200, help="Initial stack per player")
    args = p.parse_args()

    rng = random.Random(args.seed)
    seeds = [rng.randrange(1, 10_000_000) for _ in range(args.sessions)]

    human_wins = 0
    human_losses = 0
    draws = 0
    total_pnl = 0
    sessions = []

    for i, s in enumerate(seeds, 1):
        res = simulate_session(seed=s, max_hands=args.hands, init_stack=args.init_stack)
        sessions.append(res)
        total_pnl += res.pnl[0]
        if res.final_stacks[0] > res.final_stacks[1]:
            human_wins += 1
        elif res.final_stacks[0] < res.final_stacks[1]:
            human_losses += 1
        else:
            draws += 1

    mean_pnl = total_pnl / float(max(1, len(seeds)))
    print("Human always-all-in vs bot (v1)")
    print(f"sessions={len(seeds)}, max_hands={args.hands}, init_stack={args.init_stack}")
    print(f"result: wins={human_wins}, losses={human_losses}, draws={draws}")
    print(f"mean human PnL: {mean_pnl:+.2f} chips per session")
    # Show a couple of samples
    for idx, r in enumerate(sessions[:3]):
        print(
            f"sample[{idx}]: hands={r.hands_played}, stacks={r.final_stacks}, pnl={r.pnl}, reason={r.ended_reason}"
        )

    # Return 0 always; this is an exploratory tool
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
