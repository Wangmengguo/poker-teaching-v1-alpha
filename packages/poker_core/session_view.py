from poker_core.session_types import SessionView


# 从持久化 Session 折叠（在 Django 层调用）
def snapshot_session_from_model(session_model) -> SessionView:
    return SessionView(
        session_id=session_model.session_id,
        button=int(session_model.button),
        stacks=tuple(session_model.stacks),  # [p0,p1] -> (p0,p1)
        hand_no=int(session_model.hand_counter),
        current_hand_id=None,  # 可由内存映射补充
    )
