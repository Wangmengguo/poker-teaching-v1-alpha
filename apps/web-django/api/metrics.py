# apps/web_django/api/metrics.py
from __future__ import annotations

import logging

from django.http import HttpResponse

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        REGISTRY,
        Counter,
        Histogram,
        generate_latest,
    )

    log = logging.getLogger(__name__)

    # --- helpers: get_or_create，避免重复注册报错 ---
    def _get_or_create_counter(name: str, doc: str, labels: list[str]):
        try:
            return Counter(name, doc, labels)
        except ValueError:
            # 已注册，直接复用（使用 REGISTRY 的内部映射）
            return REGISTRY._names_to_collectors[name]  # type: ignore[attr-defined]

    def _get_or_create_hist(name: str, doc: str, labels: list[str]):
        try:
            return Histogram(name, doc, labels)
        except ValueError:
            return REGISTRY._names_to_collectors[name]  # type: ignore[attr-defined]

    # --- Suggest 专用指标（标签维度与视图保持一致） ---
    SUGGEST_LATENCY = _get_or_create_hist(
        "suggest_latency_seconds", "Suggest latency", ["policy", "street"]
    )
    SUGGEST_ERRORS = _get_or_create_counter(
        "suggest_errors_total", "Suggest errors", ["type", "street"]
    )
    SUGGEST_ACTION = _get_or_create_counter(
        "suggest_action_total", "Suggested actions", ["policy", "street", "action"]
    )
    SUGGEST_CLAMPED = _get_or_create_counter(
        "suggest_clamped_total", "Amount clamped", ["policy", "street"]
    )
    SUGGEST_NOLEGAL = _get_or_create_counter(
        "suggest_no_legal_actions_total", "No legal actions", ["policy", "street"]
    )

    # --- API 通用指标 ---
    API_LATENCY = _get_or_create_hist(
        "api_latency_seconds", "API latency", ["route", "method", "status"]
    )
    API_ERRORS = _get_or_create_counter(
        "api_errors_total", "API errors", ["route", "kind"]
    )

    # --- Suggest API 封装 ---
    def observe_latency(policy: str, street: str | None, seconds: float):
        SUGGEST_LATENCY.labels(policy or "unknown", street or "unknown").observe(
            seconds
        )

    def inc_error(err_type: str, street: str | None = None):
        SUGGEST_ERRORS.labels(err_type or "unknown", street or "unknown").inc()

    def inc_action(policy: str, action: str, street: str | None = None):
        SUGGEST_ACTION.labels(
            policy or "unknown", street or "unknown", action or "unknown"
        ).inc()

    def inc_clamped(policy: str, street: str | None = None):
        SUGGEST_CLAMPED.labels(policy or "unknown", street or "unknown").inc()

    def inc_no_legal_actions(policy: str, street: str | None = None):
        SUGGEST_NOLEGAL.labels(policy or "unknown", street or "unknown").inc()

    # --- API 通用封装 ---
    def observe_request(route: str, method: str, status: str, seconds: float):
        API_LATENCY.labels(
            route or "unknown", method or "GET", status or "200"
        ).observe(seconds)

    def inc_api_error(route: str, kind: str):
        API_ERRORS.labels(route or "unknown", kind or "unknown").inc()

    # --- 暴露端点 ---
    def prometheus_view(_request):
        return HttpResponse(generate_latest(), content_type=CONTENT_TYPE_LATEST)

    # --- 游戏流程扩展指标（可选） ---
    SESSION_STARTS = _get_or_create_counter(
        "session_starts_total", "Session creation count", ["status"]
    )
    HAND_STARTS = _get_or_create_counter(
        "hand_starts_total", "Hand creation count", ["status"]
    )
    HAND_ACTIONS = _get_or_create_counter(
        "hand_actions_total", "Hand actions count", ["action", "street"]
    )

    def inc_session_start(status: str = "success"):
        SESSION_STARTS.labels(status or "success").inc()

    def inc_hand_start(status: str = "success"):
        HAND_STARTS.labels(status or "success").inc()

    def inc_hand_action(action: str, street: str | None = None):
        HAND_ACTIONS.labels(action or "unknown", street or "unknown").inc()

    # --- Flop value-raise totals（JSON-driven facing path） ---
    FLOP_VALUE_RAISE = _get_or_create_counter(
        "flop_value_raise_total",
        "Flop value-raise count",
        ["street", "texture", "spr", "role", "facing", "pot_type", "strategy"],
    )

    def inc_value_raise(
        *,
        street: str = "flop",
        texture: str = "na",
        spr: str = "na",
        role: str = "na",
        facing: str = "na",
        pot_type: str = "single_raised",
        strategy: str = "medium",
    ) -> None:
        FLOP_VALUE_RAISE.labels(
            street or "flop",
            texture or "na",
            spr or "na",
            role or "na",
            facing or "na",
            pot_type or "single_raised",
            strategy or "medium",
        ).inc()

    # --- Coach 卡片埋点（MVP） ---
    COACH_CARD_VIEW = _get_or_create_counter(
        "coach_card_view_total",
        "Coach card views",
        ["street", "texture", "spr", "role"],
    )
    COACH_CARD_ACTION = _get_or_create_counter(
        "coach_card_action_total", "Coach card actions", ["action", "size_tag"]
    )
    COACH_CARD_PLAN_MISSING = _get_or_create_counter(
        "coach_card_plan_missing_total", "Coach plan missing", ["street"]
    )

    def inc_coach_view(street: str, texture: str, spr: str, role: str):
        COACH_CARD_VIEW.labels(
            street or "unknown", texture or "na", spr or "na", role or "na"
        ).inc()

    def inc_coach_action(action: str, size_tag: str | None):
        COACH_CARD_ACTION.labels(action or "unknown", size_tag or "").inc()

    def inc_coach_plan_missing(street: str = "flop"):
        COACH_CARD_PLAN_MISSING.labels(street or "unknown").inc()

except Exception as e:  # 无 Prometheus 或初始化失败时降级
    logging.getLogger(__name__).exception("Prometheus metrics init failed: %s", e)

    def observe_latency(policy: str, street: str | None, seconds: float):
        pass

    def inc_error(err_type: str, street: str | None = None):
        pass

    def inc_action(policy: str, action: str, street: str | None = None):
        pass

    def inc_clamped(policy: str, street: str | None = None):
        pass

    def inc_no_legal_actions(policy: str, street: str | None = None):
        pass

    def observe_request(route: str, method: str, status: str, seconds: float):
        pass

    def inc_api_error(route: str, kind: str):
        pass

    def inc_value_raise(
        *,
        street: str = "flop",
        texture: str = "na",
        spr: str = "na",
        role: str = "na",
        facing: str = "na",
        pot_type: str = "single_raised",
        strategy: str = "medium",
    ) -> None:
        pass

    def prometheus_view(_request):
        # 用 200 文本而不是 501，避免采集器报警刷屏；也更利于排查
        return HttpResponse(
            "prometheus metrics unavailable\n", content_type="text/plain", status=200
        )
