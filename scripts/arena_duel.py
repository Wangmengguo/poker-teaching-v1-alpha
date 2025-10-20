"""
Arena duel: pit two bot profiles against each other and report results.

Usage examples:

  # Baseline (v1 + mixing on) vs Exploit vs-allin (same as baseline for now)
  python scripts/arena_duel.py --sessions 50 --hands 60 --seed 123 \
    --a.policy v1 --a.mixing on --a.exploit none \
    --b.policy v1 --b.mixing on --b.exploit vs_allin

  # Both exploit profiles to sanity check draw-ish behavior
  python scripts/arena_duel.py --sessions 50 --hands 60 --seed 123 \
    --a.policy v1 --a.mixing on --a.exploit vs_allin \
    --b.policy v1 --b.mixing on --b.exploit vs_allin

Notes:
  - Per-seat env overrides are applied only for the suggestion call of that seat.
  - The game engine and randomness are otherwise shared.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import random
import time
from collections.abc import Iterator
from dataclasses import dataclass

from poker_core.session_flow import next_hand
from poker_core.session_types import SessionView
from poker_core.state_hu import apply_action
from poker_core.state_hu import settle_if_needed
from poker_core.state_hu import start_hand
from poker_core.state_hu import start_hand_with_carry
from poker_core.state_hu import start_session
from poker_core.suggest.service import build_suggestion

from tools.report_utils import SuggestCounters
from tools.report_utils import bb_per_100_from_totals
from tools.report_utils import mean_and_ci95
from tools.report_utils import timestamp_tag
from tools.report_utils import write_csv
from tools.report_utils import write_markdown_summary


@dataclass
class Profile:
    policy: str = "v1"  # v0|v1
    mixing: str = "on"  # on|off
    exploit: str = "none"  # none|vs_allin
    strategy: str = "medium"  # loose|medium|tight


@contextlib.contextmanager
def _with_env(env_overrides: dict[str, str]) -> Iterator[None]:
    backup: dict[str, str | None] = {}
    try:
        for k, v in env_overrides.items():
            backup[k] = os.environ.get(k)
            os.environ[k] = str(v)
        yield
    finally:
        for k, old in backup.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(old)


def _env_for_profile(p: Profile) -> dict[str, str]:
    env = {
        "SUGGEST_POLICY_VERSION": p.policy,
        "SUGGEST_MIXING": p.mixing,
        "SUGGEST_STRATEGY": p.strategy,
    }
    if p.exploit in {"vs_allin", "always_allin", "allin"}:
        env["SUGGEST_EXPLOIT_PROFILE"] = "vs_allin"
    else:
        env["SUGGEST_EXPLOIT_PROFILE"] = ""
    return env


@dataclass
class DuelResult:
    hands_played: int
    final_stacks: tuple[int, int]
    pnl: tuple[int, int]
    ended_reason: str


def _bot_act(gs, actor: int, profile_env: dict[str, str], counters: SuggestCounters):
    with _with_env(profile_env):
        t0 = time.perf_counter()
        resp = build_suggestion(gs, actor)
        counters.observe(resp, time.perf_counter() - t0)
    sug = resp.get("suggested") or {}
    act = str(sug.get("action"))
    amt = sug.get("amount")
    if amt is None:
        return apply_action(gs, act)
    return apply_action(gs, act, int(amt))


def _play_hand(gs, prof_a: Profile, prof_b: Profile, counters: SuggestCounters) -> object:
    env_a = _env_for_profile(prof_a)
    env_b = _env_for_profile(prof_b)
    while getattr(gs, "street", None) != "complete":
        actor = getattr(gs, "to_act", None)
        if actor is None:
            break
        if int(actor) == 0:
            gs = _bot_act(gs, 0, env_a, counters)
        else:
            gs = _bot_act(gs, 1, env_b, counters)
        gs = settle_if_needed(gs)
        if getattr(gs, "street", None) == "complete":
            break
    return gs


def simulate_session(
    *,
    seed: int,
    max_hands: int,
    init_stack: int,
    prof_a: Profile,
    prof_b: Profile,
    counters: SuggestCounters,
) -> DuelResult:
    # Baseline defaults (can be overridden per-seat at act time)
    os.environ.setdefault("SUGGEST_POLICY_VERSION", "v1")
    os.environ.setdefault("SUGGEST_MIXING", "on")

    cfg = start_session(init_stack=init_stack, sb=1, bb=2)
    button = random.Random(seed).randint(0, 1)
    session_id = f"arena_{seed}"

    hand_id = f"arena_{seed}_1"
    gs = start_hand(cfg, session_id=session_id, hand_id=hand_id, button=button, seed=seed)

    hands_played = 0
    for _ in range(max_hands):
        hands_played += 1
        gs = _play_hand(gs, prof_a, prof_b, counters)
        s0, s1 = gs.players[0].stack, gs.players[1].stack
        if s0 <= 0 or s1 <= 0:
            reason = "bust"
            break
        sv = SessionView(
            session_id=session_id, button=button, stacks=(s0, s1), hand_no=hands_played
        )
        plan = next_hand(sv, gs, seed=seed + hands_played)
        button = plan.next_button
        new_hid = f"arena_{seed}_{hands_played+1}"
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
            reason = "bust"
            break
    else:
        reason = "max_hands"

    final = (gs.players[0].stack, gs.players[1].stack)
    pnl = (final[0] - init_stack, final[1] - init_stack)
    return DuelResult(hands_played=hands_played, final_stacks=final, pnl=pnl, ended_reason=reason)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Arena duel: two bot profiles fight")
    p.add_argument("--sessions", type=int, default=50)
    p.add_argument("--hands", type=int, default=60)
    p.add_argument("--seed", type=int, default=123)
    p.add_argument("--init-stack", type=int, default=200)
    p.add_argument("--out-dir", default="reports", help="Directory to write CSV/Markdown reports")
    p.add_argument("--tag", default="", help="Optional tag for output filenames")

    # Profile A
    p.add_argument("--a.policy", dest="a_policy", default="v1")
    p.add_argument("--a.mixing", dest="a_mixing", default="on")
    p.add_argument("--a.exploit", dest="a_exploit", default="none")
    p.add_argument("--a.strategy", dest="a_strategy", default="medium")

    # Profile B
    p.add_argument("--b.policy", dest="b_policy", default="v1")
    p.add_argument("--b.mixing", dest="b_mixing", default="on")
    p.add_argument("--b.exploit", dest="b_exploit", default="none")
    p.add_argument("--b.strategy", dest="b_strategy", default="medium")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)
    seeds = [rng.randrange(1, 10_000_000) for _ in range(args.sessions)]

    prof_a = Profile(
        policy=args.a_policy, mixing=args.a_mixing, exploit=args.a_exploit, strategy=args.a_strategy
    )
    prof_b = Profile(
        policy=args.b_policy, mixing=args.b_mixing, exploit=args.b_exploit, strategy=args.b_strategy
    )

    a_w, b_w, draws = 0, 0, 0
    total_pnl_a = 0
    total_hands = 0
    samples = []
    per_session_chips: list[float] = []
    counters = SuggestCounters()
    for i, s in enumerate(seeds, 1):
        res = simulate_session(
            seed=s,
            max_hands=args.hands,
            init_stack=args.init_stack,
            prof_a=prof_a,
            prof_b=prof_b,
            counters=counters,
        )
        total_pnl_a += res.pnl[0]
        total_hands += res.hands_played
        per_session_chips.append(float(res.pnl[0]))
        if res.final_stacks[0] > res.final_stacks[1]:
            a_w += 1
        elif res.final_stacks[1] > res.final_stacks[0]:
            b_w += 1
        else:
            draws += 1
        if len(samples) < 3:
            samples.append(res)

    mean_pnl_a = total_pnl_a / float(max(1, len(seeds)))
    bb_size = 2.0  # sb=1, bb=2 in start_session
    bb100_a = bb_per_100_from_totals(total_pnl_a, total_hands, bb_size)
    chips_mean, chips_lo, chips_hi = mean_and_ci95(per_session_chips)
    print("Arena duel results")
    print(f"sessions={len(seeds)}, max_hands={args.hands}, init_stack={args.init_stack}")
    print(
        f"A={prof_a.policy}/{prof_a.mixing}/{prof_a.exploit}/{prof_a.strategy} vs B={prof_b.policy}/{prof_b.mixing}/{prof_b.exploit}/{prof_b.strategy}"
    )
    print(f"wins(A/B/draw)={a_w}/{b_w}/{draws}")
    if chips_lo is not None and chips_hi is not None:
        print(
            f"mean PnL (A): {mean_pnl_a:+.2f} chips per session (95% CI {chips_lo:+.2f}..{chips_hi:+.2f}); bb/100 (A): {bb100_a:+.2f}"
        )
    else:
        print(f"mean PnL (A): {mean_pnl_a:+.2f} chips per session; bb/100 (A): {bb100_a:+.2f}")
    for idx, r in enumerate(samples):
        print(
            f"sample[{idx}]: hands={r.hands_played}, stacks={r.final_stacks}, pnl={r.pnl}, reason={r.ended_reason}"
        )
    # Write reports
    tag = (args.tag or timestamp_tag()).replace("/", "-")
    base = os.path.join(args.out_dir, f"arena_{tag}")
    csv_path = base + ".summary.csv"
    headers = [
        "sessions",
        "hands_max",
        "init_stack",
        "A_policy",
        "A_mixing",
        "A_exploit",
        "A_strategy",
        "B_policy",
        "B_mixing",
        "B_exploit",
        "B_strategy",
        "wins_A",
        "wins_B",
        "draws",
        "mean_chips_per_session_A",
        "bb_size",
        "total_hands",
        "bb100_A",
        "chips_mean",
        "chips_ci95_lo",
        "chips_ci95_hi",
    ] + SuggestCounters.headers()
    row = [
        len(seeds),
        args.hands,
        args.init_stack,
        prof_a.policy,
        prof_a.mixing,
        prof_a.exploit,
        prof_a.strategy,
        prof_b.policy,
        prof_b.mixing,
        prof_b.exploit,
        prof_b.strategy,
        a_w,
        b_w,
        draws,
        round(mean_pnl_a, 3),
        bb_size,
        total_hands,
        round(bb100_a, 4),
        round(chips_mean, 3),
        (None if chips_lo is None else round(chips_lo, 3)),
        (None if chips_hi is None else round(chips_hi, 3)),
    ] + counters.to_row()
    write_csv(csv_path, headers, [row])
    md_path = base + ".summary.md"
    write_markdown_summary(
        md_path,
        "Arena duel summary",
        [
            ("sessions", len(seeds)),
            ("hands_max", args.hands),
            ("A", f"{prof_a.policy}/{prof_a.mixing}/{prof_a.exploit}/{prof_a.strategy}"),
            ("B", f"{prof_b.policy}/{prof_b.mixing}/{prof_b.exploit}/{prof_b.strategy}"),
            ("wins(A/B/draw)", f"{a_w}/{b_w}/{draws}"),
            ("mean chips/session (A)", f"{mean_pnl_a:+.2f}"),
            ("bb/100 (A)", f"{bb100_a:+.2f}"),
        ],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
