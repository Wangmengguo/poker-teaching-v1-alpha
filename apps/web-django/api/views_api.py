import os

# 引用领域核心
import sys
import time

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import metrics
from .models import Replay
from .state import METRICS, REPLAYS

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PKG_DIR = os.path.abspath(os.path.join(BASE_DIR, "packages"))
if PKG_DIR not in sys.path:
    sys.path.insert(0, PKG_DIR)

from datetime import UTC  # noqa: E402

from poker_core.analysis import annotate_player_hand  # noqa: E402
from poker_core.deal import deal_hand as core_deal  # noqa: E402
from poker_core.version import ENGINE_COMMIT, SCHEMA_VERSION  # noqa: E402

DealRequest = inline_serializer(
    name="DealRequest",
    fields={
        "seed": serializers.IntegerField(required=False, allow_null=True),
        "num_players": serializers.IntegerField(
            required=False, min_value=2, max_value=6, default=2
        ),
    },
)
DealResponse = inline_serializer(
    name="DealResponse",
    fields={
        "hand_id": serializers.CharField(),
        "seed": serializers.IntegerField(allow_null=True),
        "ts": serializers.CharField(),
        "engine_commit": serializers.CharField(),
        "schema_version": serializers.CharField(),
        "players": serializers.ListField(child=serializers.JSONField()),
        "annotations": serializers.ListField(child=serializers.JSONField()),
    },
)


@extend_schema(methods=["POST"], request=DealRequest, responses={200: DealResponse})
@api_view(["POST"])
def deal_hand_api(request):
    import uuid
    from datetime import datetime

    start = time.time()
    t0 = time.perf_counter()
    route = "table/deal"
    method = "POST"
    status_label = "200"
    try:
        seed = request.data.get("seed")
        num_players = int(request.data.get("num_players", 2))
        hand = core_deal(seed=seed, num_players=num_players)
        hand_id = "h_" + uuid.uuid4().hex[:8]
        ts = datetime.now(UTC).isoformat()

        annotations = [annotate_player_hand(p["hole"]) for p in hand["players"]]
        result = {
            "hand_id": hand_id,
            "seed": hand["seed"],
            "ts": ts,
            "engine_commit": ENGINE_COMMIT,
            "schema_version": SCHEMA_VERSION,
            "players": hand["players"],
            "annotations": annotations,
        }
        # 统一的replay数据结构
        from datetime import datetime

        replay = {
            # 基本信息
            "hand_id": hand_id,
            "session_id": None,  # deal_hand_api 不涉及session概念
            "seed": hand["seed"],
            # 游戏数据（从hand中提取或设为None）
            "events": hand.get("events", []),
            "board": hand.get("board", []),
            "winner": hand.get("winner"),
            "best5": hand.get("best5"),
            # 教学数据（保持兼容）
            "players": hand["players"],
            "annotations": annotations,
            "steps": hand.get("steps", []),
            # 元数据
            "engine_commit": ENGINE_COMMIT,
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
        }
        REPLAYS[hand_id] = replay
        try:
            Replay.objects.create(hand_id=hand_id, payload=replay)
        except Exception:
            pass

        resp = Response(result, status=status.HTTP_200_OK)
        return resp
    except Exception as e:
        METRICS["error_total"] += 1
        status_label = "500"
        try:
            metrics.inc_api_error(route, "exception")
        except Exception:
            pass
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        dur_ms = int((time.time() - start) * 1000)
        METRICS["deals_total"] += 1
        METRICS["last_latency_ms"] = dur_ms
        try:
            metrics.observe_request(route, method, status_label, time.perf_counter() - t0)
        except Exception:
            pass


@extend_schema(
    responses={
        200: inline_serializer(
            name="ReplayPayload",
            fields={
                # 基本信息
                "hand_id": serializers.CharField(),
                "session_id": serializers.CharField(allow_null=True),
                "seed": serializers.IntegerField(allow_null=True),
                # 游戏数据
                "events": serializers.ListField(child=serializers.JSONField(), allow_null=True),
                "board": serializers.ListField(child=serializers.CharField(), allow_null=True),
                "winner": serializers.IntegerField(allow_null=True),
                "best5": serializers.ListField(
                    child=serializers.ListField(child=serializers.CharField()),
                    allow_null=True,
                ),
                # 教学数据
                "players": serializers.ListField(child=serializers.JSONField(), allow_null=True),
                "annotations": serializers.ListField(
                    child=serializers.JSONField(), allow_null=True
                ),
                "steps": serializers.ListField(child=serializers.JSONField(), allow_null=True),
                # 元数据
                "engine_commit": serializers.CharField(),
                "schema_version": serializers.CharField(),
                "created_at": serializers.CharField(),
            },
        )
    }
)
@api_view(["GET"])
def get_replay_api(request, hand_id: str):
    t0 = time.perf_counter()
    route = "replay"
    method = "GET"
    status_label = "200"
    try:
        rep = REPLAYS.get(hand_id)
        if rep is None:
            try:
                obj = Replay.objects.get(hand_id=hand_id)
                rep = obj.payload
            except Replay.DoesNotExist:
                status_label = "404"
                return Response({"error": "not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(rep)
    finally:
        try:
            metrics.observe_request(route, method, status_label, time.perf_counter() - t0)
        except Exception:
            pass


@extend_schema(
    responses={
        200: inline_serializer(
            name="Metrics",
            fields={
                "deals_total": serializers.IntegerField(),
                "last_latency_ms": serializers.IntegerField(allow_null=True),
                "error_total": serializers.IntegerField(),
                "db_replays_total": serializers.IntegerField(allow_null=True),  # 新增
            },
        )
    }
)
@api_view(["GET"])
def metrics_api(request):
    t0 = time.perf_counter()
    route = "metrics"
    method = "GET"
    try:
        from .models import Replay

        payload = dict(METRICS)
        try:
            payload["db_replays_total"] = Replay.objects.count()
        except Exception:
            payload["db_replays_total"] = None
        return Response(payload)
    finally:
        try:
            metrics.observe_request(route, method, "200", time.perf_counter() - t0)
        except Exception:
            pass
