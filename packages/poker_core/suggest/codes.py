from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CodeDef:
    code: str
    severity: str  # info/warn/error（rationale 默认不输出 severity，仅供 note 使用）
    default_msg: str = ""
    legacy: list[str] = field(default_factory=list)


def mk_rationale(
    c: CodeDef, msg: str | None = None, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """构造策略 rationale item（兼容 + 扩展）。

    - 保留旧键：code/msg/data
    - 新增同义键：message(=msg)/meta(=data)/severity(=CodeDef.severity)
    """
    payload: dict[str, Any] = {
        "code": c.code,
        "msg": (msg or c.default_msg),
        "message": (msg or c.default_msg),
        "severity": c.severity,
    }
    if data is not None:
        payload["data"] = data
        payload["meta"] = data
    return payload


def mk_note(
    c: CodeDef, msg: str | None = None, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """构造教学 note（含 severity）。供 analysis 使用。

    同步返回 message/meta 键，便于前端/日志统一。
    """
    item = {
        "code": c.code,
        "severity": c.severity,
        "msg": (msg or c.default_msg),
        "message": (msg or c.default_msg),
    }
    if data is not None:
        item["data"] = data
        item["meta"] = data
    return item


class SCodes:
    # --- Analysis（保持现有对外 code 以兼容测试/UI） ---
    AN_WEAK = CodeDef(
        "E001", "warn", "Weak hand: consider folding in many preflop spots."
    )
    AN_VERY_WEAK = CodeDef(
        "E002", "warn", "Very weak offsuit/unconnected. Often a fold preflop."
    )
    AN_SUITED_BROADWAY = CodeDef(
        "N101", "info", "Suited broadway: good equity/realization potential."
    )
    AN_SUITED_CONNECTED = CodeDef(
        "N101", "info", "Suited & relatively connected. Potential for draws."
    )
    AN_PREMIUM_PAIR = CodeDef(
        "N102", "info", "Premium pair: raise or 3-bet in many spots."
    )

    # --- Preflop 策略 ---
    PF_OPEN_BET = CodeDef("PF_OPEN_BET", "info", "未入池：{bb_mult}bb 开局（bet）。")
    PF_OPEN_RAISE = CodeDef(
        "PF_OPEN_RAISE", "info", "未入池：{bb_mult}bb 开局（raise）。"
    )
    PF_CHECK_NOT_IN_RANGE = CodeDef("PF_CHECK", "info", "不在开局白名单，选择过牌。")
    PF_FOLD_NO_BET = CodeDef("PF_FOLD", "info", "无更优可行动作，保底弃牌。")
    PF_CALL_THRESHOLD = CodeDef(
        "PF_CALL", "info", "面对下注：范围内且代价不高（<=阈值），选择跟注。"
    )
    PF_FOLD_EXPENSIVE = CodeDef(
        "PF_FOLD_EXPENSIVE", "info", "面对下注：范围外或代价过高，弃牌。"
    )

    # --- Postflop 策略 ---
    PL_HEADER = CodeDef(
        "PL_HEADER", "info", "Postflop v0.3：hand tags + 赔率阈值 + 最小下注。"
    )
    PL_PROBE_BET = CodeDef(
        "PL_PROBE_BET", "info", "{street} 无人下注线：以最小尺寸试探性下注。"
    )
    PL_CHECK = CodeDef("PL_CHECK", "info", "无法或不宜下注，选择过牌。")
    PL_CALL_POTODDS = CodeDef("PL_CALL", "info", "赔率可接受，选择跟注。")
    PL_FOLD_POTODDS = CodeDef("PL_FOLD", "info", "赔率不利，弃牌。")
    PL_ALLIN_ONLY = CodeDef("PL_ALLIN_ONLY", "info", "仅剩全下可选。")

    # --- 安全/告警 ---
    SAFE_CHECK = CodeDef("SAFE_CHECK", "info", "异常局面：回退为过牌。")
    WARN_CLAMPED = CodeDef("W_CLAMPED", "warn", "策略金额越界，已钳制至合法区间。")
    WARN_ANALYSIS_MISSING = CodeDef(
        "W_ANALYSIS", "warn", "无法分析手牌，使用保守策略。"
    )

    # --- 新增（v1 基座：占位码，PR-0 不在策略路径触发） ---
    PF_OPEN_RANGE_HIT = CodeDef("PF_OPEN_RANGE_HIT", "info", "RFI 范围命中：建议开局。")
    PF_DEFEND_PRICE_OK = CodeDef(
        "PF_DEFEND_PRICE_OK", "info", "价格可接受，建议防守（跟注/3bet）。"
    )
    PF_DEFEND_PRICE_BAD = CodeDef("PF_DEFEND_PRICE_BAD", "info", "价格不利，收紧防守。")
    FL_DRY_CBET_THIRD = CodeDef(
        "FL_DRY_CBET_THIRD", "info", "干面/IP：以 1/3 彩池持续下注。"
    )
    FL_WET_CHECK_CALL = CodeDef(
        "FL_WET_CHECK_CALL", "info", "湿面/OOP：以过牌为主，谨慎防守。"
    )
    FL_LOW_SPR_VALUE_UP = CodeDef(
        "FL_LOW_SPR_VALUE_UP", "info", "低 SPR：强牌倾向提额。"
    )
    FL_HIGH_SPR_CTRL = CodeDef("FL_HIGH_SPR_CTRL", "info", "高 SPR：控池优先。")
    MWP_TIGHTEN_UP = CodeDef("MWP_TIGHTEN_UP", "info", "多人底池：整体收紧范围与频率。")
    CFG_FALLBACK_USED = CodeDef(
        "CFG_FALLBACK_USED", "warn", "配置不可用，已使用内置回退。"
    )

    # --- Preflop v1 细化 ---
    PF_DEFEND_3BET = CodeDef("PF_DEFEND_3BET", "info", "面对加注：范围内，选择 3bet。")
    PF_NO_LEGAL_RAISE = CodeDef(
        "PF_NO_LEGAL_RAISE", "info", "无合法再加注，回退到次优动作。"
    )
    PF_DEFEND_3BET_MIN_RAISE_ADJUSTED = CodeDef(
        "PF_DEFEND_3BET_MIN_RAISE_ADJUSTED", "info", "已提升到最小合法 re-raise 金额。"
    )
    PF_LIMP_COMPLETE_BLIND = CodeDef(
        "PF_LIMP_COMPLETE_BLIND", "info", "未命中 RFI：低价补盲（limp）。"
    )

    # --- Preflop v1: SB vs 3bet (4bet path) ---
    PF_ATTACK_4BET = CodeDef(
        "PF_ATTACK_4BET", "info", "面对 3-bet：范围内，选择 4-bet。"
    )
    PF_ATTACK_4BET_MIN_RAISE_ADJUSTED = CodeDef(
        "PF_ATTACK_4BET_MIN_RAISE_ADJUSTED", "info", "已提升到最小合法 4-bet 金额。"
    )

    # --- Flop v1 (role + MDF 对齐新增) ---
    FL_RANGE_ADV_SMALL_BET = CodeDef(
        "FL_RANGE_ADV_SMALL_BET", "info", "范围优势：偏小尺度持续下注。"
    )
    FL_NUT_ADV_POLAR = CodeDef(
        "FL_NUT_ADV_POLAR", "info", "坚果优势：采取极化与较大尺度。"
    )
    FL_MDF_DEFEND = CodeDef(
        "FL_MDF_DEFEND",
        "info",
        "面对下注：按最小防守频率（MDF）需继续防守（跟注或加注）。",
    )
    FL_DELAYED_CBET_PLAN = CodeDef(
        "FL_DELAYED_CBET_PLAN",
        "info",
        "计划：当前过牌，争取转牌位置下注（延迟 c-bet）。",
    )
    FL_MIN_REOPEN_ADJUSTED = CodeDef(
        "FL_MIN_REOPEN_ADJUSTED", "info", "已提升到最小合法 re-open 金额。"
    )
    FL_RAISE_SEMI_BLUFF = CodeDef("FL_RAISE_SEMI_BLUFF", "info", "强听半诈唬加注。")
    FL_RAISE_VALUE = CodeDef("FL_RAISE_VALUE", "info", "价值加注（对手下注较小）。")
    FL_CHECK_RANGE = CodeDef("FL_CHECK_RANGE", "info", "不在下注范围，选择过牌。")


__all__ = [
    "CodeDef",
    "mk_rationale",
    "mk_note",
    "SCodes",
]
