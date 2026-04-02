"""Shared pytest fixtures and configuration."""

import pytest


@pytest.fixture
def sample_user_request():
    """Return a minimal UserRequest for use in tests."""
    from src.core.models import UserRequest

    return UserRequest(text="Find insurance PDF and email to doctor", source="cli")


@pytest.fixture
def sample_plan_step():
    """Return a minimal PlanStep for use in tests."""
    from src.core.models import PlanStep

    return PlanStep(description="Search for insurance PDF", tool_name="file_tool")


@pytest.fixture
def sample_plan(sample_plan_step):
    """Return a minimal Plan containing one step."""
    from src.core.models import Plan

    return Plan(
        task_id="test-task-id",
        steps=[sample_plan_step],
        reasoning="Find then email",
        confidence=0.9,
    )
