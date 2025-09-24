# poker_core/suggest/utils.py
from __future__ import annotations

from hashlib import sha1
from math import isfinite
from typing import Any

from poker_core.cards import RANK_ORDER, parse_card
from poker_core.domain.actions import LegalAction

from .preflop_tables import get_modes


def pick_betlike_action(acts: list[LegalAction]) -> LegalAction | None:
    # 先 bet，再退而求其次 raise
    for name in ("bet", "raise"):
        a = next((x for x in acts if x.action == name), None)
        if a and a.min is not None and a.max is not None and a.min <= a.max:
            return a
    return None


def find_action(acts: list[LegalAction], name: str) -> LegalAction | None:
    return next((a for a in acts if a.action == name), None)


def to_call_from_acts(acts: list[LegalAction]) -> int:
    a = find_action(acts, "call")
    return int(a.to_call) if a and a.to_call is not None else 0


# ----- PR-0: helpers for v1 baseline (kept unused by default) -----


def calc_spr(pot_now: int, eff_stack: int) -> float:
    """SPR 定义（决策点）：
    spr = eff_stack / pot_now；当 pot_now<=0 时返回 float('inf') 并由 bucket 做 'na' 处理。

    说明：街首 SPR 可在进入新街时用 (effective_stack_at_street_start / pot_at_street_start)。
    这里提供通用决策点口径（更常用）。
    """
    try:
        pot = float(pot_now)
        if pot <= 0:
            return float("inf")
        return float(eff_stack) / pot
    except Exception:
        return float("inf")


def spr_bucket(spr: float) -> str:
    """按阈值分桶：≤3 / 3–6 / ≥6；无法计算返回 'na'。"""
    if spr is None or not isfinite(float(spr)):
        return "na"
    try:
        v = float(spr)
        if v <= 3.0:
            return "low"
        if v <= 6.0:
            return "mid"
        return "high"
    except Exception:
        return "na"


def classify_flop(board: list[str]) -> dict[str, Any]:
    """简化的翻面纹理分类。
    返回：{texture:'dry|semi|wet|na', paired:bool, fd:bool, sd:bool}
    规则（近似且稳定）：
      - <3 张公共牌 → na
      - 若有对子或三张同花或三连顺/双连顺 → wet
      - 两张同花或两张相连（含 1-gap） → semi
      - 否则 dry
    """
    if not board or len(board) < 3:
        return {"texture": "na", "paired": False, "fd": False, "sd": False}

    # ranks / suits 提取
    ranks = [c[:-1] for c in board[:3]]
    suits = [c[-1] for c in board[:3]]
    # paired
    paired = len(set(ranks)) < 3
    # 同花倾向
    s_counts: dict[str, int] = {}
    for s in suits:
        s_counts[s] = s_counts.get(s, 0) + 1
    three_suited = any(v == 3 for v in s_counts.values())
    two_suited = any(v == 2 for v in s_counts.values())
    fd = three_suited or two_suited  # 简化：两同花即认为有同花倾向

    # 顺听倾向（粗略，以排序后相邻差值衡量）
    RANK_ORDER = {
        "2": 2,
        "3": 3,
        "4": 4,
        "5": 5,
        "6": 6,
        "7": 7,
        "8": 8,
        "9": 9,
        "T": 10,
        "J": 11,
        "Q": 12,
        "K": 13,
        "A": 14,
    }
    vals = sorted(RANK_ORDER.get(r, 0) for r in ranks)
    gaps = [vals[1] - vals[0], vals[2] - vals[1]]
    connected = (gaps[0] <= 1 and gaps[1] <= 1) or (gaps[0] == 2 or gaps[1] == 2)
    sd = connected

    if paired or three_suited or (connected and two_suited):
        texture = "wet"
    elif two_suited or connected:
        texture = "semi"
    else:
        texture = "dry"

    return {"texture": texture, "paired": paired, "fd": fd, "sd": sd}


# ----- PR-2: role / facing-size helpers -----


def infer_pfr(gs) -> int | None:
    """Return seat index (0/1) of preflop aggressor (PFR) using event stream.

    Heuristic: scan events until the first board reveal (flop); track last
    'bet'/'raise'/'allin(as=raise|bet)' during preflop. Return its 'who'.
    Return None if not found (limped pot).
    """
    try:
        evts = list(getattr(gs, "events", []) or [])
    except Exception:
        return None
    pfr: int | None = None
    for e in evts:
        t = e.get("t")
        if t == "board" and e.get("street") == "flop":
            break
        if t in {"bet", "raise"}:
            if "who" in e:
                pfr = int(e["who"])
        elif t == "allin":
            as_kind = str(e.get("as") or "").lower()
            if as_kind in {"bet", "raise"} and "who" in e:
                pfr = int(e["who"])
    return pfr


def infer_pot_type(gs) -> str:
    """Classify preflop pot type by counting preflop raises in event stream.

    - 0 raises → 'limped'
    - 1 raise  → 'single_raised'
    - ≥2 raises → 'threebet' (coarse; includes 4-bet+ cases for now)
    """
    try:
        evts = list(getattr(gs, "events", []) or [])
    except Exception:
        return "single_raised"
    raises = 0
    for e in evts:
        t = e.get("t")
        if t == "board" and e.get("street") == "flop":
            break
        if t == "raise":
            raises += 1
        elif t == "allin" and str(e.get("as") or "").lower() == "raise":
            raises += 1
        elif t == "bet":
            # opening bet at preflop shouldn't happen; ignore
            pass
    if raises <= 0:
        return "limped"
    if raises == 1:
        return "single_raised"
    return "threebet"


def infer_last_aggressor_before(gs, street: str) -> int | None:
    """推断进入某街之前的“上一轮最后一次加注者”。

    规则（基于事件流 gs.events）：
    - 识别当前街边界：
      - preflop：无前一轮 → 返回 None。
      - flop：扫描到 e.t=="board" 且 e.street=="flop" 之前（即 preflop 段），返回最后一个 bet/raise/allin(as in {bet,raise}) 的 who。
      - turn：在 flop 段（board('flop') 之后、board('turn') 之前）返回最后 aggressor。
      - river：在 turn 段（board('turn') 之后、board('river') 之前）返回最后 aggressor。
    - 若没有匹配事件或结构缺失 → 返回 None。
    """
    try:
        evts = list(getattr(gs, "events", []) or [])
    except Exception:
        return None

    st = str(street or "preflop").lower()
    if st == "preflop":
        return None

    target_segment = None
    if st == "flop":
        target_segment = "preflop"
    elif st == "turn":
        target_segment = "flop"
    elif st == "river":
        target_segment = "turn"
    else:
        return None

    current = "preflop"
    last = None
    for e in evts:
        t = e.get("t")
        if t == "board":
            s = str(e.get("street") or "").lower()
            if s in {"flop", "turn", "river"}:
                current = s
            if current == st:
                break
            continue
        # 仅统计目标段（上一轮）
        if current != target_segment:
            continue
        if t in {"bet", "raise"}:
            if "who" in e:
                last = int(e["who"])
        elif t == "allin":
            as_kind = str(e.get("as") or "").lower()
            if as_kind in {"bet", "raise"} and "who" in e:
                last = int(e["who"])
    return last


def _modes_hu() -> dict[str, Any]:
    try:
        modes, _ = get_modes()
        return modes.get("HU", {}) if isinstance(modes, dict) else {}
    except Exception:
        return {}


def derive_facing_size_tag(to_call: int, pot_now: int) -> str:
    """Classify facing bet size by to_call/(pot_now) ratio.

    Thresholds loaded from table modes HU:
      - flop_facing_small_le (default 0.45) → 'third'
      - flop_facing_mid_le   (default 0.75) → 'half'
      - else → 'two_third+'
    Note: pot_now excludes hero's pending call by our service convention.
    """
    if pot_now <= 0 or to_call <= 0:
        return "na"
    r = float(to_call) / float(pot_now)
    m = _modes_hu()
    small_le = float(m.get("flop_facing_small_le", 0.45))
    mid_le = float(m.get("flop_facing_mid_le", 0.75))
    if r <= small_le:
        return "third"
    if r <= mid_le:
        return "half"
    return "two_third+"


def range_advantage(texture: str, role: str) -> bool:
    """Very light-weight heuristic for range advantage on flop (HU).
    - dry (A/K high, non-connected) favors PFR → True when role==pfr
    - wet favors caller range → True when role==caller
    - semi: neutral; give slight edge to PFR
    """
    t = (texture or "na").lower()
    rl = (role or "na").lower()
    if t == "dry":
        return rl == "pfr"
    if t == "wet":
        return rl == "caller"
    if t == "semi":
        return rl == "pfr"
    return False


def nut_advantage(texture: str, role: str) -> bool:
    """Heuristic nut advantage proxy.
    - wet boards (paired/three-suited/connected) → caller often has more nutted combos
    - dry/paired-high boards → PFR holds more overpairs/top range
    """
    t = (texture or "na").lower()
    rl = (role or "na").lower()
    if t == "wet":
        return rl == "caller"
    if t == "dry":
        return rl == "pfr"
    # semi: no strong nut edge assumed by default
    return False


# ---- Flop hand-class inference (6-bucket) ----

HC_VALUE = "value_two_pair_plus"
HC_OP_TPTK = "overpair_or_top_pair_strong"
HC_TOP_WEAK_OR_SECOND = "top_pair_weak_or_second_pair"
HC_MID_OR_THIRD_MINUS = "middle_pair_or_third_pair_minus"
HC_STRONG_DRAW = "strong_draw"
HC_WEAK_OR_AIR = "weak_draw_or_air"


def _rank_values(cards: list[str]) -> list[int]:
    vals: list[int] = []
    for c in cards:
        try:
            r, _ = parse_card(c)
            vals.append(RANK_ORDER.get(r, 0))
        except Exception:
            vals.append(0)
    return vals


def _suit_counts(cards: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in cards:
        try:
            _, s = parse_card(c)
            counts[s] = counts.get(s, 0) + 1
        except Exception:
            pass
    return counts


def _has_fd(hole: list[str], board3: list[str]) -> tuple[bool, bool]:
    """Return (fd, nfd) detection on flop.
    - If board is two-suited and hero holds two cards of that suit → FD.
    - If board is three-suited and hero holds one card of that suit → FD.
    - NFD when FD and hero holds Ace of that suit.
    """
    if len(board3) < 3 or len(hole) < 2:
        return (False, False)
    bsc = _suit_counts(board3)
    if not bsc:
        return (False, False)
    # target suit: suit with max count
    suit, cnt = max(bsc.items(), key=lambda x: x[1])
    hole_s = _suit_counts(hole).get(suit, 0)
    fd = (cnt == 2 and hole_s == 2) or (cnt == 3 and hole_s >= 1)
    if not fd:
        return (False, False)
    # NFD: hero holds Ace of the suit
    try:
        ranks = [parse_card(c)[0] for c in hole if parse_card(c)[1] == suit]
        nfd = "A" in ranks
    except Exception:
        nfd = False
    return (fd, nfd)


def _has_oesd(hole: list[str], board3: list[str]) -> bool:
    # approximate: check any 4-consecutive window having 4 distinct ranks present in union(hole,board)
    vals = sorted(set(_rank_values(hole + board3)))
    if len(vals) < 4:
        return False
    for i in range(len(vals) - 3):
        if vals[i + 3] - vals[i] == 3:
            # ensure at least one hole rank participates (avoid pure-board artifact)
            hv = set(_rank_values(hole))
            window = set(range(vals[i], vals[i] + 4))
            if hv & window:
                return True
    return False


def _has_gutshot(hole: list[str], board3: list[str]) -> bool:
    vals = sorted(set(_rank_values(hole + board3)))
    if len(vals) < 4:
        return False
    # check any 5-wide window contains at least 4 ranks
    for i in range(len(vals)):
        w = [v for v in vals if vals[i] <= v <= vals[i] + 4]
        if len(w) >= 4:
            # require at least one hole rank in window
            hv = set(_rank_values(hole))
            if hv & set(w):
                return True
    return False


def infer_flop_hand_class(hole: list[str], board3: list[str]) -> str:
    """Return one of 6 buckets for flop policy.
    Precedence: two_pair+/set > overpair/TPTK(strong) > top/second > third-/under > strong_draw > weak_draw_or_air
    """
    try:
        if len(hole) != 2 or len(board3) < 3:
            return HC_WEAK_OR_AIR
        hr1, _ = parse_card(hole[0])
        hr2, _ = parse_card(hole[1])
        b_ranks = [parse_card(c)[0] for c in board3[:3]]
        # counts across 5 cards
        counts: dict[str, int] = {}
        for r in b_ranks + [hr1, hr2]:
            counts[r] = counts.get(r, 0) + 1
        pairs = [r for r, c in counts.items() if c >= 2]
        trips = [r for r, c in counts.items() if c >= 3]
        if trips or len(pairs) >= 2:
            return HC_VALUE

        # overpair check
        hole_pair = hr1 == hr2
        b_vals = sorted([RANK_ORDER[r] for r in b_ranks], reverse=True)
        topv = b_vals[0]
        if hole_pair and RANK_ORDER[hr1] > topv:
            return HC_OP_TPTK

        # top/second/third pair
        # Sort board ranks by value (highest first) for accurate comparison
        sorted_b_ranks = sorted(b_ranks, key=lambda r: RANK_ORDER[r], reverse=True)

        def _kicker_val() -> int:
            # rank value of the non-paired hole card
            if hr1 in b_ranks and hr2 not in b_ranks:
                return RANK_ORDER[hr2]
            if hr2 in b_ranks and hr1 not in b_ranks:
                return RANK_ORDER[hr1]
            return 0

        if any(r == sorted_b_ranks[0] for r in [hr1, hr2]):
            # top pair
            kv = _kicker_val()
            return HC_OP_TPTK if kv >= 12 else HC_TOP_WEAK_OR_SECOND
        if any(r == sorted_b_ranks[1] for r in [hr1, hr2]):
            return HC_TOP_WEAK_OR_SECOND
        if any(r == sorted_b_ranks[2] for r in [hr1, hr2]) or (
            hole_pair and RANK_ORDER[hr1] < b_vals[2]
        ):
            return HC_MID_OR_THIRD_MINUS

        # draws
        fd, nfd = _has_fd(hole, board3)
        oesd = _has_oesd(hole, board3)
        gs = _has_gutshot(hole, board3)
        if fd or oesd:
            return HC_STRONG_DRAW
        if gs:
            return HC_WEAK_OR_AIR
        return HC_WEAK_OR_AIR
    except Exception:
        return HC_WEAK_OR_AIR


def infer_flop_hand_class_from_gs(gs, actor: int) -> str:
    try:
        hole = list(getattr(gs.players[actor], "hole", []) or [])
        board = list(getattr(gs, "board", []) or [])[:3]
        return infer_flop_hand_class(hole, board)
    except Exception:
        return HC_WEAK_OR_AIR


def position_of(actor: int, table_mode: str, button: int, street: str) -> str:
    """最小位置映射（PR-0：HU 优先）。
    HU：button 为 SB；另一位为 BB。
    其它桌型占位实现（后续 PR 扩展）。
    """
    try:
        if (table_mode or "HU").upper() == "HU":
            return "SB" if actor == int(button) else "BB"
    except Exception:
        pass
    # 占位：未知/未实现
    return "NA"


def is_ip(actor: int, table_mode: str, button: int, street: str) -> bool:
    """仅在翻后街定义 IP（最后行动）。

    规则（HU）：
    - preflop：不使用 IP/OOP 概念，统一返回 False（避免误用）。
    - flop/turn/river：按钮位（SB）为 IP，即 actor == button。
    """
    try:
        mode = (table_mode or "HU").upper()
        st = str(street or "preflop").lower()
        if mode == "HU":
            if st in {"flop", "turn", "river"}:
                return int(actor) == int(button)
            # preflop 不用 IP 概念
            return False
    except Exception:
        return False
    return False


def is_first_to_act(actor: int, table_mode: str, button: int, street: str) -> bool:
    """判断在当前街是否首先行动（HU）。

    - preflop：SB/按钮先行动 → actor == button
    - 翻后：非按钮先行动 → actor != button
    其它桌型暂不实现，返回 False。
    """
    try:
        mode = (table_mode or "HU").upper()
        st = str(street or "preflop").lower()
        if mode == "HU":
            if st == "preflop":
                return int(actor) == int(button)
            if st in {"flop", "turn", "river"}:
                return int(actor) != int(button)
    except Exception:
        return False
    return False


def is_last_to_act(actor: int, table_mode: str, button: int, street: str) -> bool:
    """与 is_first_to_act 对偶：是否最后行动（HU）。

    - preflop：BB/非按钮最后行动 → actor != button
    - 翻后：按钮最后行动 → actor == button
    """
    try:
        mode = (table_mode or "HU").upper()
        st = str(street or "preflop").lower()
        if mode == "HU":
            if st == "preflop":
                return int(actor) != int(button)
            if st in {"flop", "turn", "river"}:
                return int(actor) == int(button)
    except Exception:
        return False
    return False


def active_player_count(gs) -> int:
    """现阶段引擎为 HU，固定返回 2。
    若传入对象含 players，则断言其长度为 2（帮助在测试/开发期尽早发现误用）。
    """
    try:
        players = getattr(gs, "players", None)
        if players is not None:
            assert len(players) == 2, "HU engine expects exactly 2 players"
    except AttributeError:
        # 忽略属性访问错误，继续返回默认值
        pass
    return 2


def size_to_amount(pot: int, last_bet: int, size_tag: str, bb: int) -> int | None:
    """根据 size_tag 计算目标下注量（bet 语义）。
    raise 语义后续可在策略中基于 min-raise 规则转换；
    这里提供统一的锅份额到金额换算。
    """
    if size_tag is None:
        return None
    sizing_map = {
        "third": 1.0 / 3.0,
        "half": 0.5,
        "two_third": 2.0 / 3.0,
        "pot": 1.0,
        "all_in": 10.0,  # 实际会被后续 min(hero_stack, max) 钳制
    }
    mult = sizing_map.get(size_tag)
    if mult is None:
        return None
    base = max(0, int(round(float(pot) * mult)))
    # 下注最小值通常 >= bb；此处先返回裸值，交由 service 钳制
    return max(base, 1)


def raise_to_amount(
    pot_now: int,
    last_bet: int,
    size_tag: str,
    bb: int,
    eff_stack: int | None = None,
    cap_ratio: float | None = None,
) -> int | None:
    """Compute postflop raise to-amount by sizing tag.

    - Use pot share to derive desired raise-to when possible.
    - Apply optional cap: min(eff_stack * cap_ratio, target_to)
    """
    sizing_map = {
        "third": 1.0 / 3.0,
        "half": 0.5,
        "two_third": 2.0 / 3.0,
        "pot": 1.0,
    }
    mult = sizing_map.get(size_tag)
    if mult is None:
        return None
    try:
        target = int(round(float(pot_now) * (1.0 + mult)))  # to-amount ≈ call + raise add
        if eff_stack is not None and cap_ratio is not None and cap_ratio > 0:
            cap_to = int(round(float(eff_stack) * float(cap_ratio)))
            target = min(target, cap_to)
        return max(target, max(bb, last_bet + bb))
    except Exception:
        return None


def stable_roll(hand_id: str, pct: int) -> bool:
    """稳定灰度：使用 sha1(hand_id) 取模决定是否命中 [0, pct)。
    pct 超界会被裁剪到 [0,100]。
    """
    q = max(0, min(int(pct or 0), 100))
    if q <= 0:
        return False
    if q >= 100:
        return True
    h = sha1((hand_id or "").encode("utf-8")).hexdigest()
    # 取前 8 字节作为无符号整数
    bucket = int(h[:8], 16) % 100
    return bucket < q


def drop_nones(d: dict[str, Any]) -> dict[str, Any]:
    """剔除值为 None 的键（浅层）。"""
    return {k: v for k, v in (d or {}).items() if v is not None}
