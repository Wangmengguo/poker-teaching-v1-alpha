from django.urls import path

from .views import demo_page
from .views_play import hand_act_api, hand_start_api, hand_state_api, session_start_api

urlpatterns = [
    path("", demo_page, name="demo"),
    path("session/start", session_start_api, name="session_start"),
    path("hand/start", hand_start_api, name="hand_start"),
    path("hand/state/<str:hand_id>", hand_state_api, name="hand_state"),
    path("hand/act/<str:hand_id>", hand_act_api, name="hand_act"),
]
