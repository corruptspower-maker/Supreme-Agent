"""CLI interface using Click."""

from __future__ import annotations

import asyncio
import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
def cli() -> None:
    """Executive Agent CLI."""
    pass


@cli.command()
@click.option("--text", "-t", required=True, help="Task to execute")
@click.option("--source", default="cli", help="Request source")
def run(text: str, source: str) -> None:
    """Submit a task to the agent."""
    async def _run():
        from src.core.executive import ExecutiveAgent
        agent = ExecutiveAgent()
        await agent.start()
        task = await agent.submit_request(text, source=source)
        console.print(f"[green]Task submitted:[/green] {task.id}")
        await asyncio.sleep(2)
        await agent.shutdown()
    asyncio.run(_run())


@cli.command()
def status() -> None:
    """Check agent status."""
    console.print("[yellow]Agent status check not available without running agent[/yellow]")


@cli.command()
def health() -> None:
    """Run health checks."""
    async def _health():
        from src.utils.lm_studio_client import LMStudioClient
        async with LMStudioClient() as c:
            ok = await c.health_check()
        if ok:
            console.print("[green]✓ LM Studio: online[/green]")
        else:
            console.print("[red]✗ LM Studio: offline[/red]")
    asyncio.run(_health())


if __name__ == "__main__":
    cli()
