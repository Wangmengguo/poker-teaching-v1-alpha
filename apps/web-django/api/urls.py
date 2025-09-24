from django.urls import path

from . import metrics
from .views_api import deal_hand_api, get_replay_api, metrics_api
from .views_play import (
    hand_act_api,
    hand_auto_step_api,
    hand_start_api,
    hand_state_api,
    session_next_api,
    session_start_api,
    session_state_api,
)
from .views_suggest import SuggestView
from .views_ui import (
    ui_coach_suggest,
    ui_game_view,
    ui_hand_act,
    ui_replay_view,
    ui_session_next,
    ui_start,
    ui_toggle_teach,
)

urlpatterns = [
    path("table/deal", deal_hand_api, name="deal"),
    # Backward-compat route (kept): /api/v1/replay/<hand_id>
    path("replay/<str:hand_id>", get_replay_api, name="replay"),
    # New route aligned with docs: /api/v1/hand/<hand_id>/replay
    path("hand/<str:hand_id>/replay", get_replay_api, name="hand_replay"),
    path("metrics", metrics_api, name="metrics"),
    path("metrics/prometheus", metrics.prometheus_view, name="metrics_prom"),
    path("session/start", session_start_api, name="session_start"),
    path("hand/start", hand_start_api, name="hand_start"),
    path("hand/state/<str:hand_id>", hand_state_api, name="hand_state"),
    path("hand/act/<str:hand_id>", hand_act_api, name="hand_act"),
    path("hand/auto-step/<str:hand_id>", hand_auto_step_api, name="hand_auto_step"),
    path("session/<str:session_id>/state", session_state_api, name="session_state"),
    path("session/next", session_next_api, name="session_next"),
    path("suggest", SuggestView.as_view(), name="suggest"),
    # UI glue (HTML, OOB fragments)
    path("ui/game/<str:session_id>/<str:hand_id>", ui_game_view, name="ui_game"),
    path("ui/replay/<str:hand_id>", ui_replay_view, name="ui_replay"),
    path("ui/start", ui_start, name="ui_start"),
    path("ui/hand/<str:hand_id>/act", ui_hand_act, name="ui_hand_act"),
    path("ui/session/<str:session_id>/next", ui_session_next, name="ui_session_next"),
    path("ui/coach/<str:hand_id>/suggest", ui_coach_suggest, name="ui_coach_suggest"),
    path("ui/prefs/teach", ui_toggle_teach, name="ui_toggle_teach"),
]
