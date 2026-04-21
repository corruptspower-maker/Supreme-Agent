"""API entrypoint for routing tasks through Supreme Agent."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from src.core.executive import ExecutiveAgent

router = APIRouter()
agent = ExecutiveAgent()


class RunAgentRequest(BaseModel):
    goal: str


@router.post("/run_agent")
async def run_agent(req: RunAgentRequest) -> dict:
    """Execute a goal through Supreme Agent as the single control hub."""
    result = await agent.run_async(req.goal, source="api")
    return {"result": result}
