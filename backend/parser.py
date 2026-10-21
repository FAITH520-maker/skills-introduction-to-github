"""解析上传的 TXT / JSON 对话文件，统一成消息列表。

消息结构：{"speaker": 发言人, "content": 内容, "time": 时间（可为空）}
"""
import json
import re


class ParseError(Exception):
    """文件解析失败。"""


SPEAKER_KEYS = ("speaker", "name", "user", "from", "author", "nick")
CONTENT_KEYS = ("content", "text", "message", "msg", "body")
TIME_KEYS = ("time", "timestamp", "date", "datetime", "ts")

# [时间] 昵称: 内容
_BRACKET_RE = re.compile(
    r"^\[\s*(?P<time>[^\]]{1,40})\s*\]\s*(?P<speaker>[^:：\s]{1,40})\s*[:：]\s*(?P<content>.*)$"
)
# 2024-01-01 12:00:00 昵称: 内容
_DATETIME_RE = re.compile(
    r"^(?P<time>\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?)\s+"
    r"(?P<speaker>[^\s:：]{1,40})\s*[:：]\s*(?P<content>.*)$"
)
# 微信导出风格：昵称 12:30（内容在下一行）
_WECHAT_RE = re.compile(r"^(?P<speaker>[^\s:：]{1,40})\s+(?P<time>\d{1,2}:\d{2}(?::\d{2})?)$")
# 昵称: 内容
_COLON_RE = re.compile(r"^(?P<speaker>[^\s:：]{1,40})\s*[:：]\s*(?P<content>.+)$")


def decode_bytes(data: bytes) -> str:
    """按常见编码依次尝试解码。"""
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ParseError("无法识别文件编码，请使用 UTF-8 编码保存文件")


def parse_conversation(text: str, filename: str = "") -> list[dict]:
    """根据内容与文件名选择解析方式，返回消息列表。"""
    text = (text or "").lstrip("\ufeff")
    stripped = text.strip()
    if not stripped:
        raise ParseError("文件内容为空")

    name = (filename or "").lower()
    if name.endswith(".json"):
        return parse_json(stripped)
    if stripped[:1] in ("[", "{"):
        try:
            return parse_json(stripped)
        except ParseError:
            pass  # 形似 JSON 但解析失败时，回退为 TXT 解析
    return parse_txt(stripped)


def parse_txt(text: str) -> list[dict]:
    messages: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip().replace("\u200b", "")
        if not line:
            continue

        match = _BRACKET_RE.match(line) or _DATETIME_RE.match(line)
        if match:
            messages.append(
                {"speaker": match.group("speaker").strip(), "content": match.group("content").strip(), "time": match.group("time").strip()}
            )
            continue

        match = _WECHAT_RE.match(line)
        if match:
            messages.append({"speaker": match.group("speaker").strip(), "content": "", "time": match.group("time")})
            continue

        match = _COLON_RE.match(line)
        if match:
            speaker = match.group("speaker").strip()
            if "/" not in speaker and speaker.lower() not in ("http", "https", "ftp"):
                messages.append({"speaker": speaker, "content": match.group("content").strip(), "time": ""})
                continue

        # 多行消息：接到上一条后面
        if messages and messages[-1]["content"]:
            messages[-1]["content"] += "\n" + line
        elif messages:
            messages[-1]["content"] = line
        else:
            messages.append({"speaker": "系统", "content": line, "time": ""})

    messages = [m for m in messages if m["content"]]
    if not messages:
        raise ParseError("未能识别到对话消息，请确认文件为「昵称: 内容」格式的 TXT，或包含 messages 数组的 JSON")
    return messages


def parse_json(text: str) -> list[dict]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None

    if data is None:
        # 兼容逐行 JSON（JSONL）
        items = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if not items:
            raise ParseError("JSON 文件无法解析，请检查格式")
        data = items

    return _normalize_json(data)


def _normalize_json(data) -> list[dict]:
    if isinstance(data, dict):
        for key in ("messages", "conversation", "chat", "records", "data"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            if _first(data, CONTENT_KEYS):
                data = [data]
            else:
                raise ParseError("JSON 中没有找到消息数组（支持 messages / conversation / data 字段）")
    if not isinstance(data, list):
        raise ParseError("JSON 顶层结构应为消息数组或包含 messages 数组的对象")

    messages: list[dict] = []
    for item in data:
        if isinstance(item, str):
            if item.strip():
                messages.append({"speaker": "未知", "content": item.strip(), "time": ""})
            continue
        if not isinstance(item, dict):
            continue
        speaker = _first(item, SPEAKER_KEYS) or "未知"
        content = _first(item, CONTENT_KEYS) or ""
        time_value = _first(item, TIME_KEYS) or ""
        if isinstance(content, (dict, list)):
            content = json.dumps(content, ensure_ascii=False)
        content = str(content).strip()
        if not content:
            continue
        messages.append({"speaker": str(speaker), "content": content, "time": str(time_value)})

    if not messages:
        raise ParseError("JSON 中没有有效的消息")
    return messages


def _first(data: dict, keys: tuple, default=""):
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return default


def transcript_text(messages: list[dict], max_chars: int = 16000) -> str:
    """把消息列表拼成送给模型的对话文本。"""
    lines = []
    for message in messages:
        speaker = (message.get("speaker") or "未知").strip()
        content = (message.get("content") or "").strip().replace("\n", " ")
        if not content:
            continue
        if len(content) > 600:
            content = content[:600] + "…"
        lines.append(f"{speaker}: {content}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n（…对话较长，已截断）"
    return text
