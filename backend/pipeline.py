"""分析流水线：在后台线程中执行完整决策流程，并把进度写回会话文件。

阶段：
1. 意图分析
2. 多智能体协作（第一轮意见 → 第二轮辩论）
3. 决策报告合成
"""
import traceback

from coordinator import DecisionCoordinator
from parser import transcript_text

STEPS = [
    ("intent", "分析对话意图"),
    ("collab", "多智能体协作"),
    ("report", "生成决策报告"),
]


def default_steps() -> list[dict]:
    return [{"key": key, "label": label, "status": "pending", "detail": ""} for key, label in STEPS]


def reset_session(session: dict) -> None:
    session["status"] = "running"
    session["progress"] = 4
    session["steps"] = default_steps()
    session["steps"][0]["status"] = "running"
    session["steps"][0]["detail"] = "准备中…"
    session["intent"] = None
    session["agents_round1"] = None
    session["agents_round2"] = None
    session["report"] = None
    session["error"] = None


def _step(session: dict, key: str) -> dict:
    for step in session["steps"]:
        if step["key"] == key:
            return step
    raise KeyError(key)


def _set_step(session: dict, key: str, status: str, detail: str | None = None) -> None:
    step = _step(session, key)
    step["status"] = status
    if detail is not None:
        step["detail"] = detail


def run_pipeline(session_id: str, store, coordinator: DecisionCoordinator) -> None:
    """阻塞式执行完整流程（由后台线程调用）。"""
    try:
        session = store.load(session_id)
    except FileNotFoundError:
        return

    try:
        transcript = transcript_text(session.get("messages") or [])

        # --- 1. 意图分析 ---
        _set_step(session, "intent", "running", "正在阅读对话，提炼主题与各方诉求…")
        session["progress"] = 10
        store.save(session)

        intent = coordinator.analyze_intent(transcript)
        session["intent"] = intent
        participant_count = len(intent.get("participants") or [])
        _set_step(session, "intent", "done", f"已识别 {participant_count} 位参与者与核心决策问题")
        session["progress"] = 30
        store.save(session)

        # --- 2. 多智能体协作 ---
        _set_step(session, "collab", "running", "三位评审智能体正在独立形成意见…")
        session["progress"] = 38
        store.save(session)

        round1 = coordinator.first_round(intent, transcript)
        session["agents_round1"] = round1
        _set_step(session, "collab", "running", "首轮意见已完成，进入第二轮辩论…")
        session["progress"] = 58
        store.save(session)

        round2 = coordinator.second_round(intent, round1)
        session["agents_round2"] = round2
        changed = sum(1 for item in round2 if item.get("changed"))
        _set_step(session, "collab", "done", f"第二轮辩论完成，{changed} 位智能体调整了立场")
        session["progress"] = 78
        store.save(session)

        # --- 3. 决策报告 ---
        _set_step(session, "report", "running", "综合各方意见，撰写最终决策报告…")
        session["progress"] = 86
        store.save(session)

        report = coordinator.synthesize(intent, round1, round2)
        session["report"] = report
        _set_step(session, "report", "done", "决策报告已生成")
        session["status"] = "done"
        session["progress"] = 100
        store.save(session)

    except Exception as exc:  # noqa: BLE001 - 全流程错误统一落到会话状态
        traceback.print_exc()
        for step in session.get("steps", []):
            if step.get("status") == "running":
                step["status"] = "failed"
                step["detail"] = "执行失败"
        session["status"] = "failed"
        session["error"] = str(exc)
        store.save(session)
