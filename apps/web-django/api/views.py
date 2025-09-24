import json
import os

# Import domain engine (pure Python) from packages
import sys
import time
import uuid
from datetime import UTC, datetime

from django.http import HttpResponseNotFound, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from .models import Replay
from .state import METRICS, REPLAYS

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PKG_DIR = os.path.abspath(os.path.join(BASE_DIR, "packages"))
if PKG_DIR not in sys.path:
    sys.path.insert(0, PKG_DIR)

from poker_core.analysis import annotate_player_hand  # noqa: E402
from poker_core.deal import deal_hand as core_deal  # noqa: E402
from poker_core.version import ENGINE_COMMIT, SCHEMA_VERSION  # noqa: E402


def demo_page(request):
    return render(request, "demo.html", {})


@csrf_exempt
def deal_hand(request):
    start = time.time()
    try:
        data = {}
        if request.method == "POST":
            try:
                data = json.loads(request.body.decode("utf-8") or "{}")
            except Exception:
                data = {}
        seed = data.get("seed")
        num_players = int(data.get("num_players", 2))
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

        replay = {
            # 基本信息
            "hand_id": hand_id,
            "session_id": None,  # teaching view 不涉及session概念
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

        return JsonResponse(result, status=200)
    except Exception as e:
        METRICS["error_total"] += 1
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        dur_ms = int((time.time() - start) * 1000)
        METRICS["deals_total"] += 1
        METRICS["last_latency_ms"] = dur_ms


def get_replay(request, hand_id: str):
    rep = REPLAYS.get(hand_id)
    if not rep:
        try:
            obj = Replay.objects.get(hand_id=hand_id)
            rep = obj.payload
        except Replay.DoesNotExist:
            return HttpResponseNotFound(JsonResponse({"error": "not found"}).content)
    return JsonResponse(rep)


def metrics(request):
    return JsonResponse(METRICS)
