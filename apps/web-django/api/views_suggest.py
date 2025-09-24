# apps/web_django/api/views_suggest.py
from __future__ import annotations

import logging
import time

from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from poker_core.suggest.service import build_suggestion
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import metrics  # Prometheus/StatsD 封装
from .state import HANDS

logger = logging.getLogger(__name__)


class SuggestReqSerializer(serializers.Serializer):
    hand_id = serializers.CharField()
    actor = serializers.IntegerField(min_value=0, max_value=1)


class SuggestedSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["fold", "check", "call", "bet", "raise", "allin"])
    amount = serializers.IntegerField(required=False, min_value=1)


class RationaleItemSerializer(serializers.Serializer):
    code = serializers.CharField()
    msg = serializers.CharField()
    data = serializers.JSONField(required=False)


class SuggestRespSerializer(serializers.Serializer):
    hand_id = serializers.CharField()
    actor = serializers.IntegerField(min_value=0, max_value=1)
    suggested = SuggestedSerializer()
    rationale = RationaleItemSerializer(many=True)
    policy = serializers.CharField()


class SuggestView(APIView):
    @extend_schema(
        request=SuggestReqSerializer,
        responses={
            200: OpenApiResponse(response=SuggestRespSerializer, description="OK"),
            404: inline_serializer(
                name="SuggestErr404", fields={"detail": serializers.CharField()}
            ),
            409: inline_serializer(
                name="SuggestErr409", fields={"detail": serializers.CharField()}
            ),
            422: inline_serializer(
                name="SuggestErr422", fields={"detail": serializers.CharField()}
            ),
        },
        tags=["suggest"],
        summary="Return a minimal legal suggestion for the given hand/actor",
        examples=[
            OpenApiExample(
                name="Suggest Request",
                value={"hand_id": "h_1234abcd", "actor": 0},
                request_only=True,
            ),
            OpenApiExample(
                name="Suggest Response",
                value={
                    "hand_id": "h_1234abcd",
                    "actor": 0,
                    "suggested": {"action": "bet", "amount": 125},
                    "rationale": [
                        {
                            "code": "N101",
                            "msg": "未入池：2.5bb 开局（bet）。",
                            "data": {"bb": 50, "chosen": 125},
                        }
                    ],
                    "policy": "preflop_v0",
                },
                response_only=True,
            ),
        ],
    )
    def post(self, request, *args, **kwargs):
        ser = SuggestReqSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        hand_id = ser.validated_data["hand_id"]
        actor = ser.validated_data["actor"]

        entry = HANDS.get(hand_id) or {}
        gs = entry.get("gs")
        if gs is None:
            return Response({"detail": "hand not found"}, status=status.HTTP_404_NOT_FOUND)

        # 以 street==complete 判断完结
        if getattr(gs, "street", None) == "complete":
            return Response({"detail": "hand already ended"}, status=status.HTTP_409_CONFLICT)

        t0 = time.perf_counter()
        policy = "unknown"
        try:
            resp = build_suggestion(gs, actor)
            policy = resp.get("policy", "unknown")
            logger.info(
                "suggest",
                extra={
                    "hand_id": hand_id,
                    "actor": actor,
                    "street": gs.street,
                    "policy": resp.get("policy"),
                    "action": resp.get("suggested", {}).get("action"),
                    "amount": resp.get("suggested", {}).get("amount"),
                },
            )
            try:
                # 常规动作计数
                metrics.inc_action(
                    resp.get("policy"),
                    resp.get("suggested", {}).get("action"),
                    street=gs.street,
                )
                # 若发生钳制，记录细化指标（专用计数器）
                rationale = resp.get("rationale", []) or []
                if any((r or {}).get("code") == "W_CLAMPED" for r in rationale):
                    metrics.inc_clamped(
                        resp.get("policy"),
                        resp.get("suggested", {}).get("action"),
                        street=gs.street,
                    )
            except Exception:
                pass
            return Response(resp, status=status.HTTP_200_OK)
        except PermissionError:
            try:
                metrics.inc_error("not_turn", street=gs.street)
            except Exception:
                pass
            return Response({"detail": "not actor's turn"}, status=status.HTTP_409_CONFLICT)
        except ValueError as e:
            try:
                msg = str(e).lower()
                if "illegal action" in msg:
                    metrics.inc_error("illegal_action", street=gs.street)
                elif "no legal actions" in msg:
                    metrics.inc_no_legal_actions(street=gs.street)
                else:
                    metrics.inc_error("value_error", street=gs.street)
            except Exception:
                pass
            return Response(
                {"detail": f"suggest failed: {e}"},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        finally:
            try:
                metrics.observe_latency(policy, gs.street, time.perf_counter() - t0)
            except Exception:
                pass
