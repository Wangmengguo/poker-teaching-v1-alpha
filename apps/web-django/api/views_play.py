"""
API 视图：游戏流程控制
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC

from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, inline_serializer
from poker_core.analysis import annotate_player_hand
from poker_core.session_flow import next_hand
from poker_core.session_types import SessionView

# 领域函数（按你项目的实际导入路径调整）
from poker_core.state_hu import apply_action as _apply_action
from poker_core.state_hu import legal_actions as _legal_actions
from poker_core.state_hu import settle_if_needed as _settle_if_needed
from poker_core.state_hu import start_hand as _start_hand
from poker_core.state_hu import start_hand_with_carry as _start_hand_with_carry
from poker_core.suggest.service import build_suggestion
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import metrics
from .models import Replay, Session
from .state import HANDS, METRICS, snapshot_state

# --- Session end helpers (MVP) ---


def _build_session_end_summary(
    s: Session, gs, reason: str, *, last_hand_id: str | None = None
) -> dict:
    """Build minimal end summary consistent across REST/UI."""
    hands_played = int(getattr(s, "hand_counter", 0) or 0)
    try:
        stacks = [int(gs.players[0].stack), int(gs.players[1].stack)]
    except Exception:
        stacks = list(getattr(s, "stacks", []) or [0, 0])
    init_stack = int((s.config or {}).get("init_stack", 0) or 0)
    pnl = [stacks[0] - init_stack, stacks[1] - init_stack] if init_stack else [0, 0]
    pnl_fmt = [f"{pnl[0]:+d}", f"{pnl[1]:+d}"]
    return {
        "ended_reason": reason,
        "hands_played": hands_played,
        "final_stacks": stacks,
        "pnl": pnl,
        "pnl_fmt": pnl_fmt,
        "last_hand_id": last_hand_id,
    }


def finalize_session(s: Session, gs, reason: str, *, last_hand_id: str | None = None) -> dict:
    """Mark a session as ended; idempotent; return summary dict."""
    if s.status == "ended":
        stats = dict(s.stats or {})
        return {
            "ended_reason": s.ended_reason,
            "hands_played": stats.get("hands_played"),
            "final_stacks": stats.get("final_stacks"),
            "pnl": stats.get("pnl"),
            "pnl_fmt": stats.get("pnl_fmt"),
            "last_hand_id": stats.get("last_hand_id"),
        }

    from datetime import datetime

    with transaction.atomic():
        s_locked = Session.objects.select_for_update().get(pk=s.pk)
        if s_locked.status == "ended":
            stats = dict(s_locked.stats or {})
            return {
                "ended_reason": s_locked.ended_reason,
                "hands_played": stats.get("hands_played"),
                "final_stacks": stats.get("final_stacks"),
                "pnl": stats.get("pnl"),
                "pnl_fmt": stats.get("pnl_fmt"),
                "last_hand_id": stats.get("last_hand_id"),
            }
        summary = _build_session_end_summary(s_locked, gs, reason, last_hand_id=last_hand_id)
        s_locked.status = "ended"
        s_locked.ended_reason = reason
        s_locked.ended_at = datetime.now(UTC)
        s_locked.stats = summary
        s_locked.save(update_fields=["status", "ended_reason", "ended_at", "stats", "updated_at"])

    # Structured log for observability
    try:
        import logging

        logging.info(
            "session_end",
            extra={
                "event": "session_end",
                "session_id": s.session_id,
                "last_hand_id": last_hand_id,
                **summary,
            },
        )
    except Exception:
        pass

    return summary


# 从 events 中提取 outcome 信息
def _extract_outcome_from_events(gs) -> dict | None:
    # 从最后往前找 showdown 事件
    for e in reversed(getattr(gs, "events", []) or []):
        if e.get("t") == "showdown":
            return {"winner": e.get("winner"), "best5": e.get("best5")}
    # 允许弃牌结束：返回 winner、best5=None
    for e in reversed(getattr(gs, "events", []) or []):
        if e.get("t") == "win_fold":
            return {"winner": e.get("who"), "best5": None}
        if e.get("t") == "win_showdown":
            return {"winner": e.get("who"), "best5": None}
    return None


# 统一的回放持久化（手牌结束时调用）
def _persist_replay(hand_id: str, gs) -> None:
    try:
        session_id = HANDS.get(hand_id, {}).get("session_id")
        seed = HANDS.get(hand_id, {}).get("seed")
        # 统一的replay数据结构
        from datetime import datetime

        from poker_core.version import ENGINE_COMMIT, SCHEMA_VERSION

        outcome = _extract_outcome_from_events(gs)

        # 获取玩家数据和注释
        players_data = []
        annotations_data = []
        if hasattr(gs, "players"):
            for i, player in enumerate(gs.players):
                player_info = {
                    "pos": i,
                    "hole": player.hole,
                    "stack": player.stack,
                    "invested": player.invested_street,
                    "folded": player.folded,
                    "all_in": player.all_in,
                }
                players_data.append(player_info)

                # 生成教学注释
                if player.hole and len(player.hole) == 2:
                    annotation = annotate_player_hand(player.hole)
                    annotations_data.append(annotation)
                else:
                    annotations_data.append({"info": {}, "notes": []})

        # 生成基础的steps数据
        steps_data = []
        if hasattr(gs, "events") and gs.events:
            # 游戏开始步骤
            steps_data.append(
                {
                    "idx": 0,
                    "evt": "GAME_START",
                    "payload": {
                        "session_id": session_id,
                        "seed": seed,
                        "players": len(players_data),
                    },
                }
            )

            # 从events生成steps (选取关键事件)
            key_events = ["deal_hole", "showdown", "win_fold", "win_showdown"]
            for event in gs.events:
                if event.get("t") in key_events:
                    steps_data.append(
                        {
                            "idx": len(steps_data),
                            "evt": event.get("t", "").upper(),
                            "payload": {k: v for k, v in event.items() if k != "t"},
                        }
                    )

            # 游戏结束步骤
            if outcome:
                steps_data.append({"idx": len(steps_data), "evt": "GAME_END", "payload": outcome})

        replay_data = {
            # 基本信息
            "hand_id": hand_id,
            "session_id": session_id,
            "seed": seed,
            # 游戏数据
            "events": getattr(gs, "events", []),
            "board": list(getattr(gs, "board", [])),
            "button": getattr(gs, "button", 0),  # 庄位信息
            "winner": outcome.get("winner") if outcome else None,
            "best5": outcome.get("best5") if outcome else None,
            # 教学数据
            "players": players_data,
            "annotations": annotations_data,
            "steps": steps_data,
            # 元数据
            "engine_commit": ENGINE_COMMIT,
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
        }
        Replay.objects.update_or_create(hand_id=hand_id, defaults={"payload": replay_data})
    except Exception as e:
        import logging

        logging.warning(f"Failed to save replay for {hand_id}: {e}")


# ---------- 1) POST /session/start ----------
@extend_schema(
    request=inline_serializer(
        name="StartSessionReq",
        fields={
            "init_stack": serializers.IntegerField(required=False, default=200, min_value=1),
            "sb": serializers.IntegerField(required=False, default=1, min_value=1),
            "bb": serializers.IntegerField(required=False, default=2, min_value=2),
            "max_hands": serializers.IntegerField(required=False, min_value=1, allow_null=True),
        },
    ),
    responses={
        200: inline_serializer(
            name="StartSessionResp",
            fields={
                "session_id": serializers.CharField(),
                "button": serializers.IntegerField(),
                "stacks": serializers.ListField(child=serializers.IntegerField()),
                "config": serializers.JSONField(),
            },
        )
    },
)
@api_view(["POST"])
def session_start_api(request):
    import time

    start_time = time.time()
    t0 = time.perf_counter()
    route = "session/start"
    method = "POST"
    status_label = "200"

    try:
        init_stack = int(request.data.get("init_stack", 200))
        sb = int(request.data.get("sb", 1))
        bb = int(request.data.get("bb", 2))
        max_hands = request.data.get("max_hands", None)
        cfg = {"init_stack": init_stack, "sb": sb, "bb": bb}
        if max_hands is not None:
            try:
                cfg["max_hands"] = int(max_hands)
            except Exception:
                pass

        session_id = str(uuid.uuid4())
        s = Session.objects.create(
            session_id=session_id,
            config=cfg,
            stacks=[init_stack, init_stack],
            button=0,
            hand_counter=1,
            status="running",
        )

        # 记录会话创建成功
        METRICS["deals_total"] += 1  # 复用现有指标
        metrics.inc_session_start("success")  # 使用新的监控指标

        duration = time.time() - start_time
        METRICS["last_latency_ms"] = int(duration * 1000)

        return Response(
            {
                "session_id": session_id,
                "button": s.button,
                "stacks": s.stacks,
                "config": s.config,
            }
        )

    except Exception as e:
        # 记录错误
        METRICS["error_total"] += 1
        metrics.inc_session_start("failed")  # 记录失败状态
        metrics.inc_error("session_creation_failed", street="unknown")
        status_label = "500"
        try:
            metrics.inc_api_error(route, "exception")
        except Exception:
            pass

        import logging

        logging.error(f"Session creation failed: {e}")
        return Response({"detail": f"Session creation failed: {str(e)}"}, status=500)
    finally:
        try:
            metrics.observe_request(route, method, status_label, time.perf_counter() - t0)
        except Exception:
            pass


# ---------- 2) POST /hand/start ----------
@extend_schema(
    request=inline_serializer(
        name="StartHandReq",
        fields={
            "session_id": serializers.CharField(),
            "seed": serializers.IntegerField(required=False, allow_null=True),
            "button": serializers.IntegerField(required=False, allow_null=True),
        },
    ),
    responses={
        200: inline_serializer(
            name="StartHandResp",
            fields={
                "hand_id": serializers.CharField(),
                "state": serializers.JSONField(),
                "legal_actions": serializers.ListField(child=serializers.CharField()),
            },
        )
    },
)
@api_view(["POST"])
def hand_start_api(request):
    t0 = time.perf_counter()
    route = "hand/start"
    method = "POST"
    session_id = request.data.get("session_id")
    s = get_object_or_404(Session, session_id=session_id)
    if s.status != "running":
        try:
            metrics.observe_request(route, method, "409", time.perf_counter() - t0)
        except Exception:
            pass
        return Response({"detail": "session not running"}, status=409)
    cfg = s.config
    seed: int | None = request.data.get("seed")
    button = request.data.get("button", s.button)
    hand_id = str(uuid.uuid4())

    gs = _start_hand(cfg, session_id=session_id, hand_id=hand_id, button=int(button), seed=seed)

    HANDS[hand_id] = {"gs": gs, "session_id": session_id, "seed": seed, "cfg": cfg}
    # 下一手按钮建议轮转（这里不直接改，交给结算后更新；先返回当前）
    st = snapshot_state(gs)
    la = list(_legal_actions(gs))
    try:
        resp = Response({"hand_id": hand_id, "state": st, "legal_actions": la})
        return resp
    finally:
        try:
            metrics.observe_request(route, method, "200", time.perf_counter() - t0)
        except Exception:
            pass


# ---------- 3) GET /hand/{hand_id}/state ----------
@extend_schema(
    responses={
        200: inline_serializer(
            name="HandStateResp",
            fields={
                "hand_id": serializers.CharField(),
                "state": serializers.JSONField(),
                "legal_actions": serializers.ListField(child=serializers.CharField()),
            },
        )
    }
)
@api_view(["GET"])
def hand_state_api(request, hand_id: str):
    t0 = time.perf_counter()
    route = "hand/state"
    method = "GET"
    if hand_id not in HANDS:
        try:
            metrics.observe_request(route, method, "404", time.perf_counter() - t0)
        except Exception:
            pass
        return Response({"detail": "hand not found"}, status=404)
    gs = HANDS[hand_id]["gs"]
    try:
        return Response(
            {
                "hand_id": hand_id,
                "state": snapshot_state(gs),
                "legal_actions": list(_legal_actions(gs)),
            }
        )
    finally:
        try:
            metrics.observe_request(route, method, "200", time.perf_counter() - t0)
        except Exception:
            pass


# ---------- 4) POST /hand/{hand_id}/act ----------
OutcomeSchema = inline_serializer(
    name="Outcome",
    fields={
        "winner": serializers.IntegerField(allow_null=True),
        "best5": serializers.ListField(
            child=serializers.ListField(child=serializers.CharField()), allow_null=True
        ),
    },
)


@extend_schema(
    request=inline_serializer(
        name="ActReq",
        fields={
            "action": serializers.ChoiceField(
                choices=["check", "call", "bet", "raise", "fold", "allin"]
            ),
            "amount": serializers.IntegerField(required=False, allow_null=True, min_value=1),
        },
    ),
    responses={
        200: inline_serializer(
            name="ActResp",
            fields={
                "hand_id": serializers.CharField(),
                "state": serializers.JSONField(),
                "legal_actions": serializers.ListField(child=serializers.CharField()),
                "hand_over": serializers.BooleanField(),
                "outcome": OutcomeSchema,
            },
        )
    },
)
@api_view(["POST"])
def hand_act_api(request, hand_id: str):
    t0 = time.perf_counter()
    route = "hand/act"
    method = "POST"
    if hand_id not in HANDS:
        try:
            metrics.observe_request(route, method, "404", time.perf_counter() - t0)
        except Exception:
            pass
        return Response({"detail": "hand not found"}, status=404)
    gs = HANDS[hand_id]["gs"]

    action = request.data.get("action")
    amount = request.data.get("amount", None)
    try:
        gs = _apply_action(gs, action, amount)
    except ValueError as e:
        try:
            metrics.observe_request(route, method, "400", time.perf_counter() - t0)
            metrics.inc_api_error(route, "validation")
        except Exception:
            pass
        return Response({"detail": str(e)}, status=400)

    # 可能推进到下一街 / 结算
    gs = _settle_if_needed(gs)
    HANDS[hand_id]["gs"] = gs

    # 判断是否结束（按你的实现是 'complete' 或标志位）
    street = getattr(gs, "street", None) or (getattr(gs, "state", {}) or {}).get("street")
    hand_over = street in {"complete", "showdown_complete"} or getattr(gs, "is_over", False)

    payload = {
        "hand_id": hand_id,
        "state": snapshot_state(gs),
        "legal_actions": list(_legal_actions(gs)) if not hand_over else [],
        "hand_over": hand_over,
    }

    if hand_over:
        # API 直带最小结果（便于前端立即展示）
        outcome = _extract_outcome_from_events(gs)
        if outcome:
            payload["outcome"] = outcome
        # 同步持久化回放
        _persist_replay(hand_id, gs)

    try:
        return Response(payload, status=status.HTTP_200_OK)
    finally:
        try:
            metrics.observe_request(route, method, "200", time.perf_counter() - t0)
        except Exception:
            pass


# ---------- 5) GET /session/{session_id}/state ----------

SessionStateResp = inline_serializer(
    name="SessionStateResp",
    fields={
        "session_id": serializers.CharField(),
        "button": serializers.IntegerField(),
        "stacks": serializers.ListField(child=serializers.IntegerField()),
        "stacks_after_blinds": serializers.ListField(
            child=serializers.IntegerField(), allow_null=True
        ),
        "sb": serializers.IntegerField(),
        "bb": serializers.IntegerField(),
        "hand_counter": serializers.IntegerField(),
        "current_hand_id": serializers.CharField(required=False, allow_null=True),
    },
)


@extend_schema(responses={200: SessionStateResp})
@api_view(["GET"])
def session_state_api(request, session_id: str):
    t0 = time.perf_counter()
    route = "session/state"
    method = "GET"
    s = get_object_or_404(Session, session_id=session_id)
    # 尝试从内存映射取当前手（教学期：最后一次启动的 hand）
    current_hand_id, latest_gs = None, None
    for hid, item in reversed(list(HANDS.items())):
        if item.get("session_id") == session_id:
            current_hand_id = hid
            latest_gs = item.get("gs")
            break
    stacks_after_blinds = None
    if latest_gs:
        stacks_after_blinds = [latest_gs.players[0].stack, latest_gs.players[1].stack]
    sb = int((s.config or {}).get("sb", 1))
    bb = int((s.config or {}).get("bb", 2))
    try:
        return Response(
            {
                "session_id": s.session_id,
                "button": s.button,
                "stacks": s.stacks,
                "stacks_after_blinds": stacks_after_blinds,
                "sb": sb,
                "bb": bb,
                "hand_counter": s.hand_counter,
                "current_hand_id": current_hand_id,
            }
        )
    finally:
        try:
            metrics.observe_request(route, method, "200", time.perf_counter() - t0)
        except Exception:
            pass


# ---------- 6) POST /session/next ----------

NextHandResp = inline_serializer(
    name="NextHandResp",
    fields={
        "session_id": serializers.CharField(),
        "hand_id": serializers.CharField(),
        "state": serializers.JSONField(),
    },
)


@extend_schema(
    request=inline_serializer(
        name="NextHandReq",
        fields={
            "session_id": serializers.CharField(),
            "seed": serializers.IntegerField(required=False, allow_null=True),
        },
    ),
    responses={200: NextHandResp},
)
@api_view(["POST"])
def session_next_api(request):
    t0 = time.perf_counter()
    route = "session/next"
    method = "POST"
    session_id = request.data.get("session_id")
    seed = request.data.get("seed")

    # Serialize concurrent "next" with a row lock
    from django.db import transaction

    with transaction.atomic():
        try:
            s = Session.objects.select_for_update().get(session_id=session_id)
        except Session.DoesNotExist:
            return Response({"detail": "session not found"}, status=status.HTTP_404_NOT_FOUND)

        # Idempotent: already ended
        if s.status == "ended":
            try:
                metrics.observe_request(route, method, "409", time.perf_counter() - t0)
            except Exception:
                pass
            return Response(
                {"session_id": s.session_id, **(s.stats or {})},
                status=status.HTTP_409_CONFLICT,
            )

        # 1) Find latest completed hand for this session
        latest_gs, latest_cfg, latest_hid = None, None, None
        for hid, item in reversed(list(HANDS.items())):
            if item.get("session_id") == session_id:
                gs = item.get("gs")
                latest_gs = gs
                latest_cfg = item.get("cfg")
                latest_hid = hid
                if getattr(gs, "street", None) == "complete":
                    break
        if latest_gs is None or getattr(latest_gs, "street", None) != "complete":
            try:
                metrics.observe_request(route, method, "409", time.perf_counter() - t0)
            except Exception:
                pass
            return Response({"detail": "last hand not complete"}, status=status.HTTP_409_CONFLICT)

        # 1.5) Max-hands end (before planning next)
        try:
            max_hands = int((s.config or {}).get("max_hands", 0) or 0)
        except Exception:
            max_hands = 0
        if max_hands and int(s.hand_counter or 0) >= max_hands:
            summary = finalize_session(s, latest_gs, "max_hands", last_hand_id=latest_hid)
            try:
                metrics.observe_request(route, method, "409", time.perf_counter() - t0)
            except Exception:
                pass
            return Response(
                {"session_id": s.session_id, **summary}, status=status.HTTP_409_CONFLICT
            )

        # 2) Plan next hand
        cfg_for_next = latest_cfg or s.config
        sv = SessionView(
            session_id=s.session_id,
            button=int(s.button),
            stacks=tuple(s.stacks),
            hand_no=int(s.hand_counter),
            current_hand_id=None,
        )
        plan = next_hand(sv, latest_gs, seed=seed)

        # 3) Update session persistent fields
        s.button = plan.next_button
        s.stacks = list(plan.stacks)
        s.hand_counter = plan.next_hand_no
        s.save(update_fields=["button", "stacks", "hand_counter", "updated_at"])

        # 4) Start new hand (with carried stacks)
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
            summary = finalize_session(s, latest_gs, "bust", last_hand_id=latest_hid)
            try:
                metrics.observe_request(route, method, "409", time.perf_counter() - t0)
            except Exception:
                pass
            return Response({"session_id": session_id, **summary}, status=status.HTTP_409_CONFLICT)
        HANDS[new_hid] = {
            "gs": gs_new,
            "session_id": session_id,
            "seed": seed,
            "cfg": cfg_for_next,
        }

    # outside transaction: respond success
    try:
        return Response(
            {
                "session_id": session_id,
                "hand_id": new_hid,
                "state": snapshot_state(gs_new),
            }
        )
    finally:
        try:
            metrics.observe_request(route, method, "200", time.perf_counter() - t0)
        except Exception:
            pass


# ---------- 7) POST /hand/auto-step/{hand_id} ----------

AutoStepReq = inline_serializer(
    name="AutoStepReq",
    fields={
        "user_actor": serializers.IntegerField(required=False, min_value=0, max_value=1, default=0),
        "max_steps": serializers.IntegerField(
            required=False, min_value=1, max_value=50, default=10
        ),
    },
)

AutoStepResp = inline_serializer(
    name="AutoStepResp",
    fields={
        "hand_id": serializers.CharField(),
        "steps": serializers.ListField(child=serializers.JSONField()),
        "state": serializers.JSONField(),
        "hand_over": serializers.BooleanField(),
        "legal_actions": serializers.ListField(child=serializers.CharField()),
    },
)


@extend_schema(request=AutoStepReq, responses={200: AutoStepResp})
@api_view(["POST"])
def hand_auto_step_api(request, hand_id: str):
    t0 = time.perf_counter()
    route = "hand/auto-step"
    method = "POST"
    if hand_id not in HANDS:
        try:
            metrics.observe_request(route, method, "404", time.perf_counter() - t0)
        except Exception:
            pass
        return Response({"detail": "hand not found"}, status=404)

    user_actor = int(request.data.get("user_actor", 0))
    max_steps = int(request.data.get("max_steps", 10))

    entry = HANDS[hand_id]
    gs = entry["gs"]
    steps: list[dict] = []

    # 若手牌已结束，直接返回
    if getattr(gs, "street", None) == "complete":
        try:
            metrics.observe_request(route, method, "409", time.perf_counter() - t0)
        except Exception:
            pass
        return Response(
            {
                "hand_id": hand_id,
                "steps": steps,
                "state": snapshot_state(gs),
                "hand_over": True,
                "legal_actions": [],
            },
            status=409,
        )

    # 自动步进：为对手执行建议动作，直到轮到用户或结束
    while max_steps > 0:
        cur = getattr(gs, "to_act", None)
        if cur is None or cur == user_actor:
            break
        # 调用建议
        resp = build_suggestion(gs, cur)
        sug = resp.get("suggested", {})
        act_name = sug.get("action")
        amt = sug.get("amount", None)
        # 应用动作
        gs = _apply_action(gs, act_name, amt)
        gs = _settle_if_needed(gs)
        entry["gs"] = gs
        steps.append(
            {
                "actor": cur,
                "suggested": sug,
                "rationale": resp.get("rationale", []),
                "policy": resp.get("policy"),
            }
        )
        max_steps -= 1
        # 重新检查to_act，因为_apply_action和_settle_if_needed可能改变了行动者
        cur = getattr(gs, "to_act", None)
        if cur is None or cur == user_actor or getattr(gs, "street", None) == "complete":
            break

    hand_over = getattr(gs, "street", None) == "complete"
    payload = {
        "hand_id": hand_id,
        "steps": steps,
        "state": snapshot_state(gs),
        "hand_over": hand_over,
        "legal_actions": list(_legal_actions(gs)) if not hand_over else [],
    }

    if hand_over:
        outcome = _extract_outcome_from_events(gs)
        if outcome:
            payload["outcome"] = outcome
        _persist_replay(hand_id, gs)

    try:
        metrics.observe_request(route, method, "200", time.perf_counter() - t0)
    except Exception:
        pass
    return Response(payload)
