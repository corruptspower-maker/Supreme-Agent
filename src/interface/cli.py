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
@click.option("--host", default="localhost", help="Web UI host")
@click.option("--port", default=8000, help="Web UI port")
def serve(host: str, port: int) -> None:
    """Start the agent with the web dashboard."""
    async def _serve():
        from src.core.executive import ExecutiveAgent
        agent = ExecutiveAgent()
        # Override UI port from CLI flag
        agent._ui_port = port
        await agent.start()
        console.print(f"[green]Agent running.[/green] Dashboard: http://{host}:{port}")
        try:
            # Keep running until interrupted
            while agent._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await agent.shutdown()

    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down…[/yellow]")


@cli.command()
@click.option("--host", default="localhost", help="Agent web UI host")
@click.option("--port", default=8000, help="Agent web UI port")
def status(host: str, port: int) -> None:
    """Check agent status via the HTTP API."""
    async def _status():
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"http://{host}:{port}/status")
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            console.print(f"[red]Cannot reach agent at http://{host}:{port}/status: {e}[/red]")
            return

        table = Table(title="Agent Status", show_header=False)
        table.add_column("Key", style="cyan")
        table.add_column("Value")

        for key, val in data.items():
            if key == "reasoning_buffer":
                table.add_row(key, str(len(val)) + " entries")
            elif key == "circuit_breaker_states":
                cb_str = ", ".join(f"{k}:{'OPEN' if v else 'closed'}" for k, v in val.items())
                table.add_row(key, cb_str or "—")
            else:
                table.add_row(key, str(val))

        console.print(table)

    asyncio.run(_status())


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

