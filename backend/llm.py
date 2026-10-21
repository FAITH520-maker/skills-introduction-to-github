"""DeepSeek 兼容的 Chat Completions 客户端。

- 真实调用：POST {LLM_BASE_URL}/chat/completions
- 离线演示：LLM_MOCK=1 时返回固定的演示数据（仅用于无网络 / 无 Key 时验证流程）
"""
import json
import re
import time

import httpx


class LLMError(Exception):
    """大模型调用失败。"""


class LLMClient:
    def __init__(self, settings) -> None:
        self.settings = settings

    def chat(self, messages: list[dict], temperature: float = 0.6, json_mode: bool = False) -> str:
        """返回模型的文本回复。"""
        if self.settings.mock:
            return _mock_reply(messages)
        if not self.settings.api_key:
            raise LLMError("未配置 LLM_API_KEY：请在项目根目录 .env 中填写，或设置 LLM_MOCK=1 使用离线演示模式")

        url = f"{self.settings.base_url}/chat/completions"
        payload = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=self.settings.timeout) as client:
                    response = client.post(url, json=payload, headers=headers)
                if response.status_code >= 500:
                    last_error = LLMError(f"模型服务暂时不可用（HTTP {response.status_code}）")
                elif response.status_code >= 400:
                    raise LLMError(f"模型接口返回错误（HTTP {response.status_code}）：{response.text[:300]}")
                else:
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    if not content:
                        raise LLMError("模型返回了空内容")
                    return content
            except LLMError:
                raise
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
                last_error = LLMError(f"模型调用异常：{exc}")
            time.sleep(1.2 * (attempt + 1))

        raise last_error or LLMError("模型调用失败")

    def chat_json(self, messages: list[dict], temperature: float = 0.4) -> dict:
        """要求模型输出 JSON 对象并解析。"""
        content = self.chat(messages, temperature=temperature, json_mode=True)
        return parse_json_text(content)


def parse_json_text(text: str) -> dict:
    """从模型输出中尽量解析出 JSON 对象。"""
    text = (text or "").strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fenced:
        text = fenced.group(1).strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # 扫描第一个平衡的 { ... }
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            else:
                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            data = json.loads(text[start : index + 1])
                            if isinstance(data, dict):
                                return data
                        except json.JSONDecodeError:
                            pass
                        break
        start = text.find("{", start + 1)

    raise LLMError("模型输出无法解析为 JSON")


# ---------------------------------------------------------------------------
# 离线演示数据（LLM_MOCK=1）
# ---------------------------------------------------------------------------

_PERSONA_RE = re.compile(r"「(.+?)」")

_MOCK_INTENT = {
    "topic": "下次读书会的选题、时间与组织形式",
    "decision_question": "下周的读书会应该选什么书、在什么时间、以怎样的方式组织？",
    "summary": "成员围绕读书会选题方向和活动安排展开讨论，普遍认可周六下午举办，但对内容难度和准备工作存在分歧。",
    "participants": [
        {"name": "林小雨", "stance": "希望尽快敲定选题并提前准备导读材料", "key_points": ["两个选题方向", "提前一周发书单"]},
        {"name": "陈默", "stance": "支持《置身事内》，建议补充导读", "key_points": ["选题有共鸣", "先发概念清单"]},
        {"name": "苏晴", "stance": "担心内容过难影响新成员，愿意承担场地和资料工作", "key_points": ["照顾新成员", "协调场地"]},
    ],
    "shared_views": ["活动时间倾向周六下午", "需要照顾新成员", "加一个简短的破冰环节"],
    "disagreements": ["选题是否过于硬核", "导读准备工作由谁承担"],
}

_MOCK_ROUND1 = {
    "务实派": {
        "stance": "先保证活动能办成、人人有事干，再谈内容深度。",
        "proposal": "确定《置身事内》为选题，周六下午举办，安排 20 分钟导读和一张资料清单，把导读、找资料、场地、流程分工落实到人。",
        "reasoning": "现有材料与人力足够支撑一次高质量活动，执行成本可控，且讨论内容与大家近期工作经历相关。",
        "concerns": ["导读准备时间可能来不及", "场地尚未确认"],
        "suggestions": ["提前一周发布阅读清单", "把导读任务拆给两人协作完成"],
    },
    "风险派": {
        "stance": "必须提前控制内容难度和准备风险，避免冷场。",
        "proposal": "选择难度适中的导读方式，活动前做一次小范围试讲；场地未确认前保留线上备选方案，并设置一个备选议题以防现场效果不佳。",
        "reasoning": "新成员占比不低，单一硬核选题可能导致参与度下降；场地与准备是本次活动最大的不确定项。",
        "concerns": ["选题过难导致冷场", "场地临时变化导致活动取消"],
        "suggestions": ["设置备选议题", "活动前做一次彩排"],
    },
    "共情派": {
        "stance": "让每位成员都能参与表达，活动才有长期价值。",
        "proposal": "保留《置身事内》但降低门槛，加入破冰环节和自由讨论时间，安排每人一分钟的发言机会，照顾新成员的参与感。",
        "reasoning": "社群活动的价值在于参与感与连接感，而不仅是内容深度；新成员第一次参与更需要被照顾。",
        "concerns": ["新成员可能不敢发言", "讨论时间容易被少数人占据"],
        "suggestions": ["设置每人一分钟发言环节", "安排主持人控场"],
    },
}

_MOCK_ROUND2 = {
    "务实派": {
        "final_stance": "坚持选择《置身事内》并落实分工，但接受把导读量控制在 20 分钟内以降低准备压力。",
        "key_argument": "执行成本可控是这类活动能持续办下去的关键，分工到人后准备工作完全来得及。",
        "changed": False,
        "change_reason": "其他智能体的担忧有道理，但可以通过压缩导读时长来化解，不需要推翻方案。",
        "agreements": ["需要照顾新成员参与感", "需要设置备选方案"],
        "disagreements": ["不必更换选题方向"],
    },
    "风险派": {
        "final_stance": "同意选择《置身事内》，但必须保留备选议题与线上备选方案，活动前完成一次试讲。",
        "key_argument": "风险控制可以和活动质量并存，提前试讲与保留备选就能把不确定性降到可接受水平。",
        "changed": True,
        "change_reason": "务实派的成本论证让我相信选题本身可行，关键是把风险控制措施落到位。",
        "agreements": ["分工到人可保证执行", "破冰环节能改善现场氛围"],
        "disagreements": ["对试讲和备选方案的重视仍应高于其他事项"],
    },
    "共情派": {
        "final_stance": "坚持加入破冰与每人一分钟发言环节，这是照顾新成员最重要的安排。",
        "key_argument": "内容可以调整，但参与感一旦缺失，新成员下期就不会再来。",
        "changed": False,
        "change_reason": "其他智能体已基本接受破冰环节，无需调整立场。",
        "agreements": ["选题方向可行", "需要有主持人控场"],
        "disagreements": ["发言时长不应被随意压缩"],
    },
}

_MOCK_REPORT = {
    "title": "下次读书会活动方案决策",
    "decision_question": "下周的读书会应该选什么书、在什么时间、以怎样的方式组织？",
    "background": "读书会成员围绕选题与组织安排讨论，整体倾向尽快确定方案并落实分工。",
    "participant_summary": [
        {"name": "林小雨", "view": "希望敲定选题并提前准备导读材料"},
        {"name": "陈默", "view": "支持《置身事内》，建议配导读清单"},
        {"name": "苏晴", "view": "关注新成员体验，愿意负责场地与资料"},
        {"name": "赵磊", "view": "担心准备工作量，倾向周六下午举办"},
        {"name": "王浩", "view": "愿意承担导读，需要人协助找资料"},
    ],
    "consensus": ["时间定在周六下午", "选题确定为《置身事内》并配导读", "加入破冰环节照顾新成员"],
    "disagreements": ["导读准备工作的时间投入", "场地是否能在周六下午落实"],
    "final_decision": "周六下午举办《置身事内》读书会：由王浩负责 20 分钟导读、苏晴协助资料并确认社区活动中心场地、林小雨提前一周发布书单与概念清单、陈默安排破冰与控场；同时准备一个备选议题应对现场冷场。",
    "rationale": "方案兼顾了选题深度与成员参与感，分工明确、成本可控，并对场地和内容难度做了风险预案，是当前条件下确定性最高的选择。",
    "risks": ["导读准备时间不足可能导致开场质量下降", "场地未能确认时需启用线上备选方案", "新成员参与度可能低于预期"],
    "action_items": ["林小雨今晚起草流程并发群确认", "苏晴三天内确认社区活动中心场地", "王浩与陈默本周完成导读试讲", "林小雨提前一周发布书单与概念清单"],
    "confidence": "中",
}


def _mock_reply(messages: list[dict]) -> str:
    system = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")
    if "意图分析师" in system:
        data = _MOCK_INTENT
    elif "决策主持人" in system:
        data = _MOCK_REPORT
    else:
        match = _PERSONA_RE.search(system)
        persona = match.group(1) if match else "务实派"
        if "第二轮" in system or "修订" in system:
            data = _MOCK_ROUND2.get(persona) or _MOCK_ROUND2["务实派"]
        else:
            data = _MOCK_ROUND1.get(persona) or _MOCK_ROUND1["务实派"]
    return json.dumps(data, ensure_ascii=False)
