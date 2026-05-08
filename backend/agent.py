from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from config import get_openai_api_key, get_openai_model
from tools import CRM_TOOLS

SYSTEM_PROMPT = """You are AgentDesk, an intelligent CRM assistant for sales teams. You help sales reps manage accounts, track deals, and take action -- all through natural language. You have access to live CRM data. Always be concise, structured, and business-focused. When drafting emails, be professional but warm. When reporting on deals, highlight urgency and next steps."""

memory = MemorySaver()
_agent_executor = None


def get_agent_executor():
    global _agent_executor
    if _agent_executor is not None:
        return _agent_executor

    api_key = get_openai_api_key()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured. Add it to backend/.env or the project .env file.")

    llm = ChatOpenAI(
        model=get_openai_model(),
        temperature=0.2,
        max_tokens=1200,
        api_key=api_key,
    )
    _agent_executor = create_react_agent(llm, CRM_TOOLS, checkpointer=memory)
    return _agent_executor


def _extract_text(message: AIMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if text:
                    parts.append(str(text))
        return "\n".join(parts)
    return str(content)


async def run_agent(message: str, thread_id: str) -> dict[str, Any]:
    """Run the CRM agent and return the final response plus tool names used."""
    config = {"configurable": {"thread_id": thread_id}}
    tools_used: list[str] = []
    try:
        result = await get_agent_executor().ainvoke(
            {"messages": [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=message)]},
            config=config,
        )
        for msg in result.get("messages", []):
            if isinstance(msg, ToolMessage) and msg.name:
                tools_used.append(msg.name)
        final_message = next(
            (msg for msg in reversed(result.get("messages", [])) if isinstance(msg, AIMessage)),
            AIMessage(content="I could not produce a response."),
        )
        return {"response": _extract_text(final_message), "tools_used": list(dict.fromkeys(tools_used))}
    except Exception as exc:
        return {
            "response": f"I could not complete that CRM request. {exc}",
            "tools_used": list(dict.fromkeys(tools_used)),
        }


async def stream_agent_response(message: str, thread_id: str) -> AsyncGenerator[str, None]:
    """Stream the final agent response token by token for clients that want streaming UX."""
    result = await run_agent(message, thread_id)
    for token in result["response"].split(" "):
        yield token + " "
