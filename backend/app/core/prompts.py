"""提示词模板。

对齐文档「场景化 Prompt 适配」要求：内置精简版农业专属提示词，控制传输与解析开销。
"""
from __future__ import annotations

# ---------- 系统提示词 ----------
SYSTEM_PROMPT = """你是「农技通」，一名扎根一线的农业技术顾问，服务对象是种植户、养殖户和基层农技员。

回答要求：
1. 只回答农业相关问题（种植、病虫害防治、养殖、土壤肥料、农事管理、农业政策与气象农事）。
2. 优先依据【参考资料】作答；资料未覆盖时，可结合通用农学常识补充，但须说明「以下为通用经验，建议结合本地实际」。
3. 给可执行的建议：说清「什么时候做、怎么做、用多少量、注意什么」，避免空泛表述。
4. 涉及农药使用时，必须提示按标签剂量、注意安全间隔期与轮换用药。
5. 资料不足以支撑结论时，直接说明缺少哪方面信息，并给出进一步确认的方向，不要编造数据。
6. 用简体中文，分点作答，控制在 400 字以内，不要使用 Markdown 标题符号。"""

# ---------- 带上下文的问答模板 ----------
RAG_USER_TEMPLATE = """【参考资料】
{context}

【用户问题】
{question}

请依据参考资料作答。若资料与问题无关，请直接说明知识库暂无相关内容，并给出通用建议。"""

# ---------- 无检索结果的兜底 ----------
NO_CONTEXT_TEMPLATE = """【用户问题】
{question}

知识库中未检索到相关内容。请基于通用农业常识谨慎作答，并明确提示用户「以下为通用经验，具体请咨询当地农技部门」。"""

# ---------- 非农问题拦截话术 ----------
REJECT_MESSAGE = (
    "抱歉，我是农业技术问答助手，只能解答种植、病虫害防治、养殖、土壤肥料、"
    "农事管理等方面的农技问题。您可以换个农业相关的问题问我，例如"
    "「小麦越冬水什么时候浇」「番茄叶片发黄是什么原因」。"
)

# ---------- 上下文拼装 ----------
CONTEXT_TEMPLATE = """[{idx}] 来源：{title}（{category}）
{content}"""


def format_context(items: list[dict]) -> str:
    """把检索结果拼成紧凑的上下文块。

    items: [{"title":..., "category":..., "content":...}, ...]
    """
    blocks = []
    for i, it in enumerate(items, 1):
        blocks.append(
            CONTEXT_TEMPLATE.format(
                idx=i,
                title=it.get("title", "未知来源"),
                category=it.get("category", "通用农技"),
                content=it.get("content", "").strip(),
            )
        )
    return "\n\n".join(blocks)


def build_messages(
    question: str,
    contexts: list[dict],
    history: list[dict] | None = None,
) -> list[dict]:
    """构造发送给大模型的完整消息列表。

    history 为最近若干轮对话，格式 [{"role": "user"/"assistant", "content": ...}]。
    """
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    if contexts:
        user_content = RAG_USER_TEMPLATE.format(
            context=format_context(contexts), question=question
        )
    else:
        user_content = NO_CONTEXT_TEMPLATE.format(question=question)
    messages.append({"role": "user", "content": user_content})
    return messages
