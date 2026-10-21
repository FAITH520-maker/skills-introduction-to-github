"""自定义多智能体协调器。

流程：
1. 意图分析智能体：提炼主题、决策问题、各方立场与分歧
2. 三位评审智能体（务实派 / 风险派 / 共情派）独立形成意见（第一轮）
3. 三位智能体阅读彼此意见后修订观点（第二轮辩论）
4. 决策主持人综合全部意见，输出决策报告
"""
import json
from concurrent.futures import ThreadPoolExecutor

from llm import LLMClient

PERSONAS = [
    {
        "key": "pragmatic",
        "name": "务实派",
        "emoji": "🛠️",
        "desc": "关注方案的可执行性、成本与资源，主张先保证能落地",
        "temperature": 0.5,
    },
    {
        "key": "risk",
        "name": "风险派",
        "emoji": "⚠️",
        "desc": "关注潜在风险、隐患与失败代价，主张谨慎决策",
        "temperature": 0.5,
    },
    {
        "key": "empathy",
        "name": "共情派",
        "emoji": "💗",
        "desc": "关注成员感受、公平与长期参与体验，主张照顾少数人",
        "temperature": 0.6,
    },
]

INTENT_SYSTEM = """你是一名资深的社群意图分析师，擅长从零散的群聊中提炼结构化的决策信息。
你会收到一段群聊记录，请仔细阅读并分析后，只输出一个 JSON 对象，不要输出任何解释性文字。"""


def _intent_user(transcript: str) -> str:
    return f"""请分析以下群聊记录：
---
{transcript}
---

输出 JSON，字段如下：
- topic: 讨论主题，一句话
- decision_question: 群体真正需要共同做出的决策问题（一个明确的问句）
- summary: 对对话整体情况的概括，120 字以内
- participants: 数组，每项包含 name（发言人）、stance（该成员的立场或倾向，一句话）、key_points（最多 3 条关键诉求或主张）
- shared_views: 字符串数组，群体已有的共识
- disagreements: 字符串数组，主要分歧点

只输出 JSON。"""


def _agent_system(persona: dict) -> str:
    return f"""你是群体决策委员会中的「{persona['name']}」智能体，{persona['desc']}。
你的任务是根据对话记录和意图分析，独立形成你的决策意见。请保持你的角色立场，不要迎合其他角色。
只输出一个 JSON 对象，不要输出任何解释性文字。"""


def _agent_user(intent: dict, transcript: str) -> str:
    return f"""【对话记录】
{transcript}

【意图分析】
{json.dumps(intent, ensure_ascii=False)}

请从你的角色立场出发，输出 JSON：
- stance: 你对如何决策的基本立场，一句话
- proposal: 你建议的具体决策方案，2~4 句，尽量可执行
- reasoning: 支持该方案的主要理由，1~3 句
- concerns: 数组，你担心的问题（1~3 条）
- suggestions: 数组，给最终决策的补充建议（1~3 条）

只输出 JSON。"""


def _debate_system(persona: dict) -> str:
    return f"""你是群体决策委员会中的「{persona['name']}」智能体，{persona['desc']}。
现在进入第二轮辩论：请阅读其他智能体在第一轮的意见，以及你自己第一轮的意见，然后修订并明确你的最终观点。
只输出一个 JSON 对象，不要输出任何解释性文字。"""


def _debate_user(intent: dict, own: dict, others: list[dict]) -> str:
    others_text = "\n".join(
        f"{item['name']}：{item.get('stance', '')}｜建议：{item.get('proposal', '')}" for item in others
    )
    return f"""【意图分析】
{json.dumps(intent, ensure_ascii=False)}

【你的第一轮意见】
{json.dumps(own, ensure_ascii=False)}

【其他智能体的第一轮意见】
{others_text}

输出 JSON：
- final_stance: 你第二轮之后确定的最终立场，一句话
- key_argument: 你最核心的论点，1~2 句
- changed: 布尔值，你的立场相比第一轮是否有调整
- change_reason: 立场调整的原因（若未调整则说明为什么坚持）
- agreements: 数组，你认同其他智能体的点（1~3 条）
- disagreements: 数组，你仍不认同其他智能体的点（1~3 条）

只输出 JSON。"""


REPORT_SYSTEM = """你是一名群体决策主持人，需要综合意图分析和多位智能体的多轮意见，产出最终的决策报告。
报告必须务实、可执行，并如实反映已有共识与仍然存在的分歧。
只输出一个 JSON 对象，不要输出任何解释性文字。"""


def _report_user(intent: dict, round1: list[dict], round2: list[dict]) -> str:
    return f"""【意图分析】
{json.dumps(intent, ensure_ascii=False)}

【智能体第一轮意见】
{json.dumps(round1, ensure_ascii=False)}

【智能体第二轮意见】
{json.dumps(round2, ensure_ascii=False)}

请综合以上信息，输出 JSON：
- title: 决策报告标题
- decision_question: 决策问题
- background: 背景与现状，80 字以内
- participant_summary: 数组，每项 {{name, view}}，概括每位参与者的核心诉求
- consensus: 字符串数组，智能体之间达成的共识
- disagreements: 字符串数组，仍然存在的分歧
- final_decision: 最终决策，明确、可执行，150 字以内
- rationale: 做出该决策的理由，80~120 字
- risks: 字符串数组，主要风险与应对提示（2~4 条）
- action_items: 字符串数组，后续行动清单（3~5 条）
- confidence: 决策置信度，"高" / "中" / "低"

只输出 JSON。"""


class DecisionCoordinator:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def analyze_intent(self, transcript: str) -> dict:
        data = self.llm.chat_json(
            [
                {"role": "system", "content": INTENT_SYSTEM},
                {"role": "user", "content": _intent_user(transcript)},
            ],
            temperature=0.3,
        )
        return _normalize_intent(data)

    def first_round(self, intent: dict, transcript: str) -> list[dict]:
        def ask(persona: dict) -> dict:
            data = self.llm.chat_json(
                [
                    {"role": "system", "content": _agent_system(persona)},
                    {"role": "user", "content": _agent_user(intent, transcript)},
                ],
                temperature=persona["temperature"],
            )
            return _normalize_round1(persona, data)

        with ThreadPoolExecutor(max_workers=len(PERSONAS)) as pool:
            return list(pool.map(ask, PERSONAS))

    def second_round(self, intent: dict, round1: list[dict]) -> list[dict]:
        personas = {persona["key"]: persona for persona in PERSONAS}

        def ask(own: dict) -> dict:
            persona = personas.get(own["key"], PERSONAS[0])
            others = [item for item in round1 if item["key"] != own["key"]]
            data = self.llm.chat_json(
                [
                    {"role": "system", "content": _debate_system(persona)},
                    {"role": "user", "content": _debate_user(intent, own, others)},
                ],
                temperature=persona["temperature"],
            )
            return _normalize_round2(own, data)

        with ThreadPoolExecutor(max_workers=len(round1)) as pool:
            return list(pool.map(ask, round1))

    def synthesize(self, intent: dict, round1: list[dict], round2: list[dict]) -> dict:
        data = self.llm.chat_json(
            [
                {"role": "system", "content": REPORT_SYSTEM},
                {"role": "user", "content": _report_user(intent, round1, round2)},
            ],
            temperature=0.3,
        )
        return _normalize_report(data)


# ---------------------------------------------------------------------------
# 结果规范化：保证前端拿到的字段完整
# ---------------------------------------------------------------------------


def _text(value, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip() or default


def _list(value, limit: int = 6) -> list[str]:
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return items[:limit]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _normalize_intent(data: dict) -> dict:
    participants = []
    for item in data.get("participants") or []:
        if not isinstance(item, dict):
            continue
        participants.append(
            {
                "name": _text(item.get("name"), "参与者"),
                "stance": _text(item.get("stance")),
                "key_points": _list(item.get("key_points"), 3),
            }
        )
    return {
        "topic": _text(data.get("topic"), "未识别"),
        "decision_question": _text(data.get("decision_question")),
        "summary": _text(data.get("summary")),
        "participants": participants,
        "shared_views": _list(data.get("shared_views")),
        "disagreements": _list(data.get("disagreements")),
    }


def _normalize_round1(persona: dict, data: dict) -> dict:
    return {
        "key": persona["key"],
        "name": persona["name"],
        "emoji": persona["emoji"],
        "desc": persona["desc"],
        "stance": _text(data.get("stance")),
        "proposal": _text(data.get("proposal")),
        "reasoning": _text(data.get("reasoning")),
        "concerns": _list(data.get("concerns"), 3),
        "suggestions": _list(data.get("suggestions"), 3),
    }


def _normalize_round2(own: dict, data: dict) -> dict:
    return {
        "key": own["key"],
        "name": own["name"],
        "emoji": own["emoji"],
        "final_stance": _text(data.get("final_stance")),
        "key_argument": _text(data.get("key_argument")),
        "changed": bool(data.get("changed")),
        "change_reason": _text(data.get("change_reason")),
        "agreements": _list(data.get("agreements"), 3),
        "disagreements": _list(data.get("disagreements"), 3),
    }


def _normalize_report(data: dict) -> dict:
    summary = []
    for item in data.get("participant_summary") or []:
        if isinstance(item, dict):
            summary.append({"name": _text(item.get("name"), "参与者"), "view": _text(item.get("view"))})
        elif isinstance(item, str) and item.strip():
            summary.append({"name": "参与者", "view": item.strip()})
    confidence = _text(data.get("confidence"), "中")
    if confidence not in {"高", "中", "低"}:
        confidence = "中"
    return {
        "title": _text(data.get("title"), "决策报告"),
        "decision_question": _text(data.get("decision_question")),
        "background": _text(data.get("background")),
        "participant_summary": summary,
        "consensus": _list(data.get("consensus")),
        "disagreements": _list(data.get("disagreements")),
        "final_decision": _text(data.get("final_decision"), "—"),
        "rationale": _text(data.get("rationale")),
        "risks": _list(data.get("risks"), 4),
        "action_items": _list(data.get("action_items"), 5),
        "confidence": confidence,
    }
