"""A `[quiet]` reply on a real agent graph: no loop, and where the platform posts every scheduled
run's reply (MDA's schedule delivery, an `after_agent` hook installed ahead of the authored ones),
what it posts is the status line, never the marker or an earlier reply."""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from design_agent.middleware.quiet import SENTINEL_MARK, QuietReplyMiddleware
from design_agent.testing.scripted_model import ScriptedChatModel, reply


class NewestTextDelivery(AgentMiddleware[AgentState[Any], Any, Any]):
    """Stands in for MDA's schedule delivery: posts the newest non-empty assistant text."""

    def __init__(self) -> None:
        super().__init__()
        self.posted: list[str] = []

    def after_agent(self, state: AgentState[Any], runtime: Runtime[Any]) -> None:
        for message in reversed(state["messages"]):
            if isinstance(message, AIMessage) and str(message.text).strip():
                self.posted.append(str(message.text).strip())
                return


def graph(
    model: ScriptedChatModel, *, running: bool, status: Any
) -> tuple[Any, NewestTextDelivery]:
    delivery = NewestTextDelivery()
    quiet = QuietReplyMiddleware(lambda _t: running, lambda: "t1", status)
    return create_agent(model, tools=[], middleware=[delivery, quiet]), delivery


async def test_a_quiet_reply_is_posted_as_the_status_line() -> None:
    agent, delivery = graph(
        ScriptedChatModel(steps=[lambda _m: reply("[quiet]")]),
        running=True,
        status=lambda _t: "Still working: act 2 (4 min).",
    )
    result = await agent.ainvoke(
        {
            "messages": [
                AIMessage("The earlier reply."),
                HumanMessage("<check-in>Look at the render."),
            ]
        }
    )
    assert delivery.posted == ["Still working: act 2 (4 min)."]
    assert result["messages"][-1].text == "Still working: act 2 (4 min)."


async def test_without_a_status_a_quiet_reply_stays_for_the_poster_to_drop() -> None:
    agent, delivery = graph(
        ScriptedChatModel(steps=[lambda _m: reply("[quiet]")]), running=False, status=None
    )
    result = await agent.ainvoke({"messages": [HumanMessage("<check-in>Look.")]})
    assert result["messages"][-1].text == "[quiet]"


async def test_a_watchdog_turn_with_work_running_ends_without_a_model_call() -> None:
    model = ScriptedChatModel(steps=[])
    agent, delivery = graph(model, running=True, status=lambda _t: "Still working: act 2 (20 min).")
    await agent.ainvoke(
        {"messages": [HumanMessage(f"{SENTINEL_MARK}>\nA restart may have stopped work.")]}
    )
    assert model.call_count == 0
    assert delivery.posted == ["Still working: act 2 (20 min)."]
