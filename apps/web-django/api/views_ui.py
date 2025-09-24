from __future__ import annotations

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods, require_POST
from poker_core.domain.actions import legal_actions_struct

# 领域函数与结构化合法动作
from poker_core.state_hu import apply_action as _apply_action
from poker_core.state_hu import settle_if_needed as _settle_if_needed
from poker_core.state_hu import start_hand as _start_hand

from . import metrics
from .models import Session
from .state import HANDS, snapshot_state


def _role_name(button: int, who: int) -> str:
    """Return human-friendly role name.

    MVP: avoid SB/BB in copy; use You/Opponent to align with UI.
    """
    try:
        return "You" if int(who) == 0 else "Opponent"
    except Exception:
        return "—"


def _actions_model(gs) -> dict[str, Any]:
    """Build action set and amount model for the action bar (no client inference)."""
    struct = legal_actions_struct(gs)
    # Only display allowed actions; no client-side inference
    items: list[dict[str, Any]] = []
    to_call: int | None = None
    has_amount = False
    min_amt = None
    max_amt = None

    for it in struct:
        a = it.action
        if a in ("fold", "check", "allin"):
            items.append({"action": a, "label": a.capitalize()})
        elif a == "call":
            to_call = int(it.to_call or 0)
            items.append({"action": "call", "label": f"Call {to_call}"})
        elif a in ("bet", "raise"):
            has_amount = True
            min_amt = it.min if min_amt is None else min(min_amt, it.min or 0)
            max_amt = it.max if max_amt is None else max(max_amt, it.max or 0)
            # 展示为统一的 Bet/Raise；实际提交用 action 值
            items.append({"action": a, "label": "Bet" if a == "bet" else "Raise"})

    amount = {
        "show": bool(has_amount),
        "min": int(min_amt or 1),
        "max": int(max_amt or 0),
        "step": 1,  # MVP fixed step 1
    }
    return {"items": items, "amount": amount, "to_call": to_call}


def _hud_model(s: Session, st: dict[str, Any]) -> dict[str, Any]:
    sb = int(s.config.get("sb", 1))
    bb = int(s.config.get("bb", 2))
    to_act = st.get("to_act")
    button = st.get("button")
    next_role = _role_name(button, to_act) if to_act is not None else "—"
    return {
        "sb": sb,
        "bb": bb,
        "pot": int(st.get("pot") or 0),
        "hand_no": int(s.hand_counter or 1),
        "to_act": to_act,
        "button": button,
        "next_role": next_role,
    }


def _is_hand_over(gs) -> bool:
    street = getattr(gs, "street", None)
    return street in {"complete", "showdown_complete"} or bool(getattr(gs, "is_over", False))


def _ended_by_showdown(gs) -> bool:
    """判断本手是否以摊牌结束。

    依据领域层事件：存在 showdown 或 win_showdown 事件且 street==complete。
    若为 win_fold 结束则不算摊牌。
    """
    try:
        if getattr(gs, "street", None) != "complete":
            return False
        evs = getattr(gs, "events", None) or []
        # 优先判断 showdown / win_showdown
        for e in evs:
            t = e.get("t")
            if t in ("showdown", "win_showdown"):
                return True
        # 明确存在 win_fold 则认为非摊牌
        for e in evs:
            if e.get("t") == "win_fold":
                return False
        return False
    except Exception:
        return False


def _log_items(gs) -> list[str]:
    """Build last 5 action lines: "You/Opponent + action [+amount]" (most recent first)."""
    items: list[str] = []
    if not gs or not getattr(gs, "events", None):
        return items
    allowed = {
        "check",
        "call",
        "bet",
        "raise",
        "fold",
        "allin",
        "showdown",
        "win_fold",
        "win_showdown",
    }
    for e in reversed(gs.events):
        t = e.get("t")
        if t not in allowed:
            continue
        who = e.get("who")
        role = "You" if who == 0 else ("Opponent" if who == 1 else "—")
        if t == "check":
            items.append(f"{role} Check")
        elif t == "call":
            amt = e.get("amt")
            items.append(f"{role} Call {int(amt)}" if amt is not None else f"{role} Call")
        elif t == "bet":
            amt = e.get("amt")
            items.append(f"{role} Bet {int(amt)}" if amt is not None else f"{role} Bet")
        elif t == "raise":
            to = e.get("to")
            items.append(f"{role} Raise to {int(to)}" if to is not None else f"{role} Raise")
        elif t == "allin":
            amt = e.get("amt")
            items.append(f"{role} All-in {int(amt)}" if amt is not None else f"{role} All-in")
        elif t == "fold":
            items.append(f"{role} Fold")
        elif t == "showdown":
            items.append("Showdown")
        elif t == "win_fold":
            amt = e.get("amt")
            items.append(f"{role} Win {int(amt)}" if amt is not None else f"{role} Win")
        elif t == "win_showdown":
            amt = e.get("amt")
            items.append(f"{role} Win {int(amt)}" if amt is not None else f"{role} Win")
        if len(items) >= 5:
            break
    return items


def _render_oob_fragments(
    request: HttpRequest,
    *,
    session: Session,
    st: dict[str, Any],
    actions: dict[str, Any],
    coach_html: str | None = None,
    error_text: str | None = None,
    show_next_controls: bool = False,
    replay_url: str | None = None,
    hand_id_for_form: str | None = None,
    coach_hand_id: str | None = None,
    log_items: list[str] | None = None,
    reveal_opp: bool | None = None,
) -> str:
    parts: list[str] = []

    # Unified error banner
    parts.append(render_to_string("ui/_error.html", {"text": error_text or ""}, request=request))

    # HUD (aria-live for next actor)
    parts.append(
        render_to_string("ui/_hud.html", {"hud": _hud_model(session, st)}, request=request)
    )

    # Board + pot
    parts.append(render_to_string("ui/_board.html", {"st": st}, request=request))

    # Seats: stacks, per-street invested, hole cards
    teach = bool(request.session.get("teach", True))
    parts.append(
        render_to_string(
            "ui/_seats.html",
            {
                "st": st,
                "teach": teach,
                "reveal_opp": bool(reveal_opp) if reveal_opp is not None else False,
            },
            request=request,
        )
    )

    # Actions + amount
    if hand_id_for_form:
        # Replace whole form on new hand to update hx-post hand_id
        parts.append(
            render_to_string(
                "ui/_action_form.html",
                {
                    "hand_id": hand_id_for_form,
                    "actions": actions,
                    "ended": show_next_controls,
                    "session_id": session.session_id,
                    "replay_url": replay_url or "#",
                },
                request=request,
            )
        )
    else:
        # Regular: replace actions and amount separately
        parts.append(
            render_to_string(
                "ui/_actions.html",
                {
                    "actions": actions,
                    "ended": show_next_controls,
                    "session_id": session.session_id,
                    "replay_url": replay_url or "#",
                },
                request=request,
            )
        )
        parts.append(
            render_to_string(
                "ui/_amount.html",
                {"amount": actions.get("amount", {})},
                request=request,
            )
        )

    # Coach (optional OOB)
    if coach_html is not None:
        parts.append(coach_html)

    # Coach trigger (update hx-post hand_id when new hand is created)
    if coach_hand_id:
        parts.append(
            render_to_string("ui/_coach_trigger.html", {"hand_id": coach_hand_id}, request=request)
        )

    # Action log (last 5)
    if log_items is not None:
        parts.append(render_to_string("ui/_log.html", {"log": log_items}, request=request))

    return "\n".join(parts)


def ui_game_view(request: HttpRequest, session_id: str, hand_id: str) -> HttpResponse:
    """Game page: render skeleton + initial state (SSR)."""
    s = get_object_or_404(Session, session_id=session_id)
    entry = HANDS.get(hand_id)
    st: dict[str, Any] = {}
    actions: dict[str, Any] = {
        "items": [],
        "amount": {"show": False, "min": 1, "max": 0, "step": 1},
    }
    log = []
    if entry and entry.get("gs") is not None:
        gs = entry["gs"]
        st = snapshot_state(gs)
        log = _log_items(gs)
        if _is_hand_over(gs):
            actions = {
                "items": [],
                "amount": {"show": False, "min": 1, "max": 0, "step": 1},
            }
        else:
            actions = _actions_model(gs)
    # SSR: if session already ended, prepare session-end view data
    session_ended = s.status == "ended"
    ended_summary = dict(s.stats or {}) if session_ended else None
    ended_reason_text = None
    if session_ended:
        m = {
            "bust": "Insufficient chips to post blinds",
            "max_hands": "Maximum hands reached",
        }
        ended_reason_text = m.get(s.ended_reason or "", s.ended_reason or "Ended")
    # last hand id for replay link (best-effort)
    last_hid = None
    for hid, item in reversed(list(HANDS.items())):
        if item.get("session_id") == session_id:
            last_hid = hid
            break
    teach = bool(request.session.get("teach", True))
    # 计算 reveal_opp：Teach ON 或摊牌结束
    reveal_opp = False
    try:
        if entry and entry.get("gs") is not None:
            reveal_opp = bool(teach or _ended_by_showdown(entry["gs"]))
    except Exception:
        reveal_opp = bool(teach)
    ctx = {
        "session_id": session_id,
        "hand_id": hand_id,
        "hud": _hud_model(s, st),
        "st": st,
        "actions": actions,
        "log": log,
        "teach": teach,
        "reveal_opp": reveal_opp,
        "session_ended": session_ended,
        "ended_summary": ended_summary,
        "ended_reason_text": ended_reason_text,
        "last_hand_id": last_hid,
    }
    return render(request, "poker_teaching_game_ui_skeleton_htmx_tailwind.html", ctx)


@require_POST
def ui_hand_act(request: HttpRequest, hand_id: str) -> HttpResponse:
    t0_route = "ui/hand/act"
    method = "POST"
    status_label = "200"
    try:
        entry = HANDS.get(hand_id)
        if not entry or entry.get("gs") is None:
            status_label = "404"
            html = _render_error_only(request, "Object not found or expired")
            return _oob_response(html, route=t0_route, method=method, status_label=status_label)

        gs = entry["gs"]
        s = get_object_or_404(Session, session_id=entry.get("session_id"))

        # If hand already ended, return ended view, avoid engine calls
        if _is_hand_over(gs):
            st = snapshot_state(gs)
            html = _render_oob_fragments(
                request,
                session=s,
                st=st,
                actions={
                    "items": [],
                    "amount": {"show": False, "min": 1, "max": 0, "step": 1},
                },
                error_text="Hand already ended",
                show_next_controls=True,
                replay_url=f"/api/v1/ui/replay/{hand_id}",
                log_items=_log_items(gs),
                reveal_opp=bool(request.session.get("teach", True) or _ended_by_showdown(gs)),
            )
            status_label = "409"
            return _oob_response(html, route=t0_route, method=method, status_label=status_label)

        action = request.POST.get("action") or request.GET.get("action")
        amount_raw = request.POST.get("amount") or request.GET.get("amount")
        amount = int(amount_raw) if (amount_raw and amount_raw.isdigit()) else None

        if action is None:
            status_label = "422"
            html = _render_error_only(request, "Invalid action or amount (missing action)")
            return _oob_response(html, route=t0_route, method=method, status_label=status_label)

        try:
            gs = _apply_action(gs, action, amount)
        except ValueError:
            # Illegal action/amount → 422
            status_label = "422"
            entry["gs"] = gs
            st = snapshot_state(gs)
            actions = _actions_model(gs)
            html = _render_oob_fragments(
                request,
                session=s,
                st=st,
                actions=actions,
                error_text="Invalid action or amount (adjusted or please retry)",
                log_items=_log_items(gs),
                reveal_opp=bool(request.session.get("teach", True) or _ended_by_showdown(gs)),
            )
            return _oob_response(html, route=t0_route, method=method, status_label=status_label)

        gs = _settle_if_needed(gs)
        entry["gs"] = gs

        st = snapshot_state(gs)
        # 结束判定优先于构建 actions，避免 to_act 无效触发错误
        hand_over = _is_hand_over(gs)
        if hand_over:
            # 手牌结束时持久化回放数据
            from .views_play import _persist_replay

            _persist_replay(hand_id, gs)
            actions = {
                "items": [],
                "amount": {"show": False, "min": 1, "max": 0, "step": 1},
            }
        else:
            actions = _actions_model(gs)

        html = _render_oob_fragments(
            request,
            session=s,
            st=st,
            actions=actions,
            show_next_controls=hand_over,
            replay_url=f"/api/v1/ui/replay/{hand_id}" if hand_over else None,
            log_items=_log_items(gs),
            reveal_opp=bool(request.session.get("teach", True) or _ended_by_showdown(gs)),
        )
        return _oob_response(html, route=t0_route, method=method, status_label=status_label)
    finally:
        pass


@require_POST
def ui_toggle_teach(request: HttpRequest) -> HttpResponse:
    """Toggle teaching mode preference (server-side truth).

    Stores preference in request.session['teach'] (default True), flips it,
    and returns OOB fragments to refresh seats and the toggle itself.
    Showdown reveal is handled by templates based on state (street == 'complete').
    """
    t0_route = "ui/prefs/teach"
    method = "POST"
    status_label = "200"
    try:
        teach_prev = bool(request.session.get("teach", True))
        teach = not teach_prev
        request.session["teach"] = teach

        hand_id = request.POST.get("hand_id") or request.GET.get("hand_id")
        session_id = request.POST.get("session_id") or request.GET.get("session_id") or ""
        st: dict[str, Any] = {}
        if hand_id:
            entry = HANDS.get(hand_id)
            if entry and entry.get("gs") is not None:
                st = snapshot_state(entry["gs"])

        parts: list[str] = []
        if st:
            try:
                gs = entry.get("gs") if hand_id else None
                rev = bool(teach or _ended_by_showdown(gs)) if gs is not None else bool(teach)
            except Exception:
                rev = bool(teach)
            parts.append(
                render_to_string(
                    "ui/_seats.html",
                    {"st": st, "teach": teach, "reveal_opp": rev},
                    request=request,
                )
            )
        parts.append(
            render_to_string(
                "ui/_teach_toggle.html",
                {"teach": teach, "hand_id": hand_id or "", "session_id": session_id},
                request=request,
            )
        )
        html = "\n".join(parts)
        return _oob_response(html, route=t0_route, method=method, status_label=status_label)
    finally:
        pass


@require_POST
def ui_session_next(request: HttpRequest, session_id: str) -> HttpResponse:
    t0_route = "ui/session/next"
    method = "POST"
    status_label = "200"
    try:
        seed_raw = request.POST.get("seed") or request.GET.get("seed")
        seed = int(seed_raw) if (seed_raw and seed_raw.isdigit()) else None
        s = get_object_or_404(Session, session_id=session_id)

        # Idempotent: already ended
        if s.status == "ended":
            # Render session end card; no Push-Url
            ended_summary = dict(s.stats or {})
            reason_map = {
                "bust": "Insufficient chips to post blinds",
                "max_hands": "Maximum hands reached",
            }
            html = render_to_string(
                "ui/_session_end.html",
                {
                    "session_id": s.session_id,
                    "summary": ended_summary,
                    "ended_reason_text": reason_map.get(
                        s.ended_reason or "", s.ended_reason or "Ended"
                    ),
                    "last_hand_id": None,
                },
                request=request,
            )
            try:
                metrics.inc_api_error("ui_next", "t409_session_ended")
            except Exception:
                pass
            return _oob_response(html, route=t0_route, method=method, status_label=status_label)

        # Find latest completed hand for this session
        latest_gs, latest_cfg = None, None
        latest_hid = None
        for hid, item in reversed(list(HANDS.items())):
            if item.get("session_id") == session_id:
                gs = item.get("gs")
                latest_gs = gs
                latest_cfg = item.get("cfg")
                latest_hid = hid
                if getattr(gs, "street", None) == "complete":
                    break
        if latest_gs is None or getattr(latest_gs, "street", None) != "complete":
            status_label = "409"
            html = _render_error_only(request, "Cannot start next hand now")
            return _oob_response(html, route=t0_route, method=method, status_label=status_label)

        # 规划下一手
        from poker_core.session_flow import next_hand
        from poker_core.session_types import SessionView
        from poker_core.state_hu import start_hand_with_carry as _start_hand_with_carry

        cfg_for_next = latest_cfg or s.config
        # Max-hands end (before planning next)
        try:
            max_hands = int((s.config or {}).get("max_hands", 0) or 0)
        except Exception:
            max_hands = 0
        if max_hands and int(s.hand_counter or 0) >= max_hands:
            from .views_play import finalize_session

            summary = finalize_session(s, latest_gs, "max_hands", last_hand_id=latest_hid)
            reason_map = {
                "bust": "Insufficient chips to post blinds",
                "max_hands": "Maximum hands reached",
            }
            html = render_to_string(
                "ui/_session_end.html",
                {
                    "session_id": s.session_id,
                    "summary": summary,
                    "ended_reason_text": reason_map.get("max_hands"),
                    "last_hand_id": None,
                },
                request=request,
            )
            try:
                metrics.inc_api_error("ui_next", "t409_session_ended")
            except Exception:
                pass
            return _oob_response(html, route=t0_route, method=method, status_label=status_label)
        sv = SessionView(
            session_id=s.session_id,
            button=int(s.button),
            stacks=tuple(s.stacks),
            hand_no=int(s.hand_counter),
            current_hand_id=None,
        )
        plan = next_hand(sv, latest_gs, seed=seed)

        # 更新 Session
        s.button = plan.next_button
        s.stacks = list(plan.stacks)
        s.hand_counter = plan.next_hand_no
        s.save(update_fields=["button", "stacks", "hand_counter", "updated_at"])

        # 启动新手并注册
        import uuid

        new_hid = str(uuid.uuid4())
        try:
            gs_new = _start_hand_with_carry(
                cfg_for_next,
                session_id=session_id,
                hand_id=new_hid,
                button=plan.next_button,
                stacks=plan.stacks,
                seed=plan.seed,
            )
        except ValueError:
            from .views_play import finalize_session

            summary = finalize_session(s, latest_gs, "bust", last_hand_id=latest_hid)
            reason_map = {
                "bust": "Insufficient chips to post blinds",
                "max_hands": "Maximum hands reached",
            }
            html = render_to_string(
                "ui/_session_end.html",
                {
                    "session_id": s.session_id,
                    "summary": summary,
                    "ended_reason_text": reason_map.get("bust"),
                    "last_hand_id": None,
                },
                request=request,
            )
            try:
                metrics.inc_api_error("ui_next", "t409_session_ended")
            except Exception:
                pass
            return _oob_response(html, route=t0_route, method=method, status_label=status_label)
        HANDS[new_hid] = {
            "gs": gs_new,
            "session_id": session_id,
            "seed": seed,
            "cfg": cfg_for_next,
        }

        # 片段渲染
        st = snapshot_state(gs_new)
        actions = _actions_model(gs_new)
        html = _render_oob_fragments(
            request,
            session=s,
            st=st,
            actions=actions,
            show_next_controls=False,
            hand_id_for_form=new_hid,
            coach_hand_id=new_hid,
            log_items=_log_items(gs_new),
        )
        # 方案A：在开始新手后，同步更新 Teach 按钮（带上新的 hand_id）
        try:
            teach = bool(request.session.get("teach", True))
            html = (
                html
                + "\n"
                + render_to_string(
                    "ui/_teach_toggle.html",
                    {"teach": teach, "hand_id": new_hid, "session_id": session_id},
                    request=request,
                )
            )
        except Exception:
            pass
        resp = _oob_response(html, route=t0_route, method=method, status_label=status_label)
        # Only push URL when a new hand is successfully started
        resp["HX-Push-Url"] = f"/api/v1/ui/game/{session_id}/{new_hid}"
        return resp
    finally:
        pass


@require_POST
def ui_coach_suggest(request: HttpRequest, hand_id: str) -> HttpResponse:
    t0_route = "ui/coach/suggest"
    method = "POST"
    status_label = "200"
    try:
        entry = HANDS.get(hand_id)
        if not entry or entry.get("gs") is None:
            status_label = "404"
            html = _render_error_only(request, "Object not found or expired")
            return _oob_response(html, route=t0_route, method=method, status_label=status_label)

        s = get_object_or_404(Session, session_id=entry.get("session_id"))
        gs = entry.get("gs")
        st = snapshot_state(gs)
        # If ended, do not provide suggestion (avoid to_act validation)
        if _is_hand_over(gs):
            status_label = "409"
            html = _render_oob_fragments(
                request,
                session=s,
                st=st,
                actions={
                    "items": [],
                    "amount": {"show": False, "min": 1, "max": 0, "step": 1},
                },
                error_text="Hand already ended",
                show_next_controls=True,  # 添加这个参数，让UI显示next hands和replay按钮
                replay_url=f"/api/v1/ui/replay/{hand_id}",  # 添加replay URL
                log_items=_log_items(gs),
            )
            return _oob_response(html, route=t0_route, method=method, status_label=status_label)
        # 非结束态再构建 actions
        actions = _actions_model(gs)

        # 解析 actor（默认 0），要求 0/1
        actor_raw = request.POST.get("actor") or request.GET.get("actor")
        try:
            actor = int(actor_raw) if actor_raw is not None else 0
        except Exception:
            actor = 0
        if actor not in (0, 1):
            status_label = "422"
            html = _render_oob_fragments(
                request,
                session=s,
                st=st,
                actions=actions,
                error_text="Invalid suggest parameters",
            )
            return _oob_response(html, route=t0_route, method=method, status_label=status_label)

        # 构建建议
        import time

        from poker_core.suggest.service import build_suggestion

        t0 = time.perf_counter()
        try:
            resp = build_suggestion(gs, actor)
            # Metrics (align with SuggestView)
            try:
                metrics.inc_action(
                    resp.get("policy"),
                    resp.get("suggested", {}).get("action", ""),
                    street=getattr(gs, "street", None),
                )
                rationale = resp.get("rationale", []) or []
                if any((r or {}).get("code") == "W_CLAMPED" for r in rationale):
                    metrics.inc_clamped(resp.get("policy"), street=getattr(gs, "street", None))
            except Exception:
                pass
            try:
                metrics.observe_latency(
                    resp.get("policy", "unknown"),
                    getattr(gs, "street", None),
                    time.perf_counter() - t0,
                )
            except Exception:
                pass

            # Coach MVP switch (COACH_CARD_V1=on|1|true)
            import os as _os

            coach_v1 = str(_os.getenv("COACH_CARD_V1") or "off").lower() in (
                "on",
                "1",
                "true",
            )

            # Preprocess suggest data for template
            resp_processed = resp.copy()
            policy = (resp.get("policy") or "").lower()
            resp_processed["is_preflop"] = policy.startswith("preflop")

            # Debug log for meta structure
            import logging

            log = logging.getLogger(__name__)
            log.info(
                f"DEBUG: resp_processed meta keys: {list(resp_processed.get('meta', {}).keys())}"
            )
            log.info(
                f"DEBUG: resp_processed debug meta keys: {list(resp_processed.get('debug', {}).get('meta', {}).keys())}"
            )

            coach_html = render_to_string(
                "ui/_coach.html",
                {"suggest": resp_processed, "coach_v1": coach_v1},
                request=request,
            )
            # Metrics: coach card view & action aggregates
            try:
                dm = (resp.get("debug", {}) or {}).get("meta", {})
                mm = resp.get("meta", {}) or {}
                tex = dm.get("board_texture") or mm.get("texture")
                spr = dm.get("spr_bucket") or mm.get("spr_bucket")
                role = dm.get("role") or mm.get("role")
                facing = dm.get("facing_size_tag") or mm.get("facing_size_tag")
                pot_type = dm.get("pot_type") or "single_raised"
                strategy = dm.get("strategy") or "medium"
                size_tag = (resp.get("meta", {}) or {}).get("size_tag")
                action = (resp.get("suggested", {}) or {}).get("action")
                metrics.inc_coach_view(
                    getattr(gs, "street", "flop"),
                    str(tex or "na"),
                    str(spr or "na"),
                    str(role or "na"),
                )
                if action:
                    metrics.inc_coach_action(str(action), str(size_tag or ""))
                # value-raise totals（识别 rationale 中的 FL_RAISE_VALUE）
                try:
                    if any(
                        (r or {}).get("code") == "FL_RAISE_VALUE"
                        for r in (resp.get("rationale", []) or [])
                    ):
                        metrics.inc_value_raise(
                            street=getattr(gs, "street", "flop") or "flop",
                            texture=str(tex or "na"),
                            spr=str(spr or "na"),
                            role=str(role or "na"),
                            facing=str(facing or "na"),
                            pot_type=str(pot_type or "single_raised"),
                            strategy=str(strategy or "medium"),
                        )
                except Exception:
                    pass
                if coach_v1 and not ((resp.get("meta", {}) or {}).get("plan")):
                    metrics.inc_coach_plan_missing(getattr(gs, "street", "flop"))
            except Exception:
                pass
            # Prefill amount if provided
            if resp.get("suggested", {}).get("amount") is not None:
                actions["amount"]["default"] = int(resp["suggested"]["amount"])
            # Clamped hint
            rationale = resp.get("rationale", []) or []
            if any((r or {}).get("code") == "W_CLAMPED" for r in rationale):
                coach_html += "\n" + render_to_string(
                    "ui/_status_chip.html",
                    {"text": "Clamped", "extra_class": ""},
                    request=request,
                )

            html = _render_oob_fragments(
                request, session=s, st=st, actions=actions, coach_html=coach_html
            )
            return _oob_response(html, route=t0_route, method=method, status_label=status_label)
        except PermissionError:
            status_label = "409"
            html = _render_oob_fragments(
                request, session=s, st=st, actions=actions, error_text="Not your turn"
            )
            return _oob_response(html, route=t0_route, method=method, status_label=status_label)
        except ValueError:
            status_label = "422"
            html = _render_oob_fragments(
                request,
                session=s,
                st=st,
                actions=actions,
                error_text="Suggestion unavailable",
            )
            return _oob_response(html, route=t0_route, method=method, status_label=status_label)
    finally:
        pass


def _render_error_only(request: HttpRequest, text: str) -> str:
    return render_to_string("ui/_error.html", {"text": text}, request=request)


def _oob_response(html: str, *, route: str, method: str, status_label: str) -> HttpResponse:
    try:
        metrics.observe_request(route, method, status_label, 0.0)
    except Exception:
        pass
    return HttpResponse(html, content_type="text/html; charset=utf-8", status=200)


@require_http_methods(["GET"])
def ui_replay_view(request: HttpRequest, hand_id: str) -> HttpResponse:
    """Render replay page for a completed hand."""
    try:
        # Try to get replay data from database (primary source)
        try:
            from .models import Replay

            obj = Replay.objects.get(hand_id=hand_id)
            replay_data = obj.payload
        except Replay.DoesNotExist:
            # Fallback: try to get from memory if available
            replay_data = HANDS.get(hand_id, {}).get("replay_data")
            if replay_data is None:
                return HttpResponse("Replay not found", status=404)

        # Convert replay data to JSON string for template
        import json

        replay_json = json.dumps(replay_data)

        ctx = {
            "hand_id": hand_id,
            "replay_json": replay_json,
        }
        return render(request, "poker_teaching_replay.html", ctx)
    except Exception as e:
        return HttpResponse(f"Failed to load replay: {e}", status=500)


@require_http_methods(["GET", "POST"])
def ui_start(request: HttpRequest) -> HttpResponse:
    """Splash entry: one-click start session + first hand, then HX-Redirect.

    - GET: render splash page with a single button.
    - POST: create Session with defaults and start the first hand, then set
            HX-Redirect to /api/v1/ui/game/<sid>/<hid>.
    """
    if request.method == "GET":
        return render(request, "poker_teaching_entry_splash_start_the_session.html", {})

    import uuid

    init_stack, sb, bb = 200, 1, 2
    try:
        # Create session (defaults)
        session_id = str(uuid.uuid4())
        s = Session.objects.create(
            session_id=session_id,
            config={"init_stack": init_stack, "sb": sb, "bb": bb},
            stacks=[init_stack, init_stack],
            button=0,
            hand_counter=1,
            status="running",
        )
        # Start first hand
        hand_id = str(uuid.uuid4())
        gs = _start_hand(
            s.config,
            session_id=session_id,
            hand_id=hand_id,
            button=int(s.button),
            seed=None,
        )
        HANDS[hand_id] = {
            "gs": gs,
            "session_id": session_id,
            "seed": None,
            "cfg": s.config,
        }

        resp = HttpResponse("", status=200)
        resp["HX-Redirect"] = f"/api/v1/ui/game/{session_id}/{hand_id}"
        return resp
    except Exception as e:
        return HttpResponse(f"Failed to start session: {e}", status=500)
