import asyncio
from collections import deque
from datetime import datetime

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.spinner import Spinner

from app.graph.workflow import research_graph

console = Console()

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

QUERY = """
Research the latest developments in FDA regulation and approval
of AI-powered medical devices during 2025 and 2026.

Investigate recent FDA regulatory updates, newly authorized
or cleared AI-powered medical devices, changes in requirements
for continuously learning AI models, safety and clinical
validation requirements, post-market monitoring, and
implications for healthcare technology companies.

Use official FDA sources, regulatory documents and credible
industry sources. Include publication dates and actual source
URLs. Clearly distinguish confirmed regulatory decisions
from proposals.
"""

INITIAL_STATE = {
    "topic": QUERY,
    "tasks": [],
    "research_results": [],
    "aggregated_results": None,
    "critic_score": 0.0,
    "critic_feedback": "",
    "critic_acceptable": False,
    "missing_areas": [],
    "unsupported_claims": [],
    "improvement_suggestions": [],
    "retry_tasks": [],
    "retry_count": 0,
    "final_research": "",
}


# --------------------------------------------------
# LIVE EXECUTION DATA
# --------------------------------------------------

logs = deque(maxlen=18)

researchers = {}

current_stage = "Initializing workflow..."
workflow_status = "RUNNING"

tool_count = 0
completed_researchers = 0
total_researchers = 0
retry_count = 0


# --------------------------------------------------
# HELPERS
# --------------------------------------------------


def timestamp():
    return datetime.now().strftime("%H:%M:%S")


def add_log(message, style="white"):
    logs.append(
        Text(
            f"[{timestamp()}] {message}",
            style=style,
        )
    )


def shorten(value, limit=120):
    text = str(value).replace("\n", " ")
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def get_payload(event):
    return event.get("data", {})


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------


def render_dashboard():

    header = Panel(
        Group(
            Text(
                "DEEP RESEARCH AI",
                style="bold cyan",
                justify="center",
            ),
            Text(
                "LIVE WORKFLOW EXECUTION MONITOR",
                style="dim",
                justify="center",
            ),
        ),
        border_style="cyan",
    )

    status_table = Table(
        box=box.ROUNDED,
        expand=True,
    )

    status_table.add_column("METRIC", style="cyan")
    status_table.add_column("VALUE", style="bold white")

    status_table.add_row("Current Stage", current_stage)
    status_table.add_row("Workflow Status", workflow_status)
    status_table.add_row(
        "Researchers",
        f"{completed_researchers}/{total_researchers} completed",
    )
    status_table.add_row("Tool Calls", str(tool_count))
    status_table.add_row("Retry Count", str(retry_count))

    researcher_table = Table(
        title="PARALLEL RESEARCHERS",
        box=box.ROUNDED,
        expand=True,
    )

    researcher_table.add_column("SUBTASK", ratio=4)
    researcher_table.add_column("STATUS", justify="center")

    if researchers:

        for task, info in researchers.items():

            status = info["status"]

            if status == "COMPLETED":
                style = "green"
            elif status == "FAILED":
                style = "red"
            else:
                style = "yellow"

            researcher_table.add_row(
                shorten(task, 65),
                Text(status, style=style),
            )

    else:
        researcher_table.add_row(
            "Waiting for Supervisor...",
            "PENDING",
        )

    log_panel = Panel(
        Group(*list(logs)),
        title="EXECUTION LOGS",
        border_style="blue",
        height=14,
    )

    spinner = Spinner(
        "dots",
        text=f" [bold yellow]{current_stage}[/bold yellow]",
        style="cyan",
    )

    return Group(
        header,
        status_table,
        researcher_table,
        log_panel,
        Panel(spinner, border_style="dim"),
    )


# --------------------------------------------------
# EVENT PROCESSOR
# --------------------------------------------------


def process_event(event):

    global current_stage
    global tool_count
    global completed_researchers
    global total_researchers
    global retry_count

    event_name = event.get("event")
    name = event.get("name", "")
    metadata = event.get("metadata", {})
    payload = get_payload(event)

    # ----------------------------------------------
    # CUSTOM RESEARCHER EVENTS
    # ----------------------------------------------

    if event_name == "on_custom_event":

        if name == "researcher_started":

            task = payload.get("subtask", "Unknown task")

            researchers[task] = {
                "status": "RUNNING",
            }

            total_researchers += 1

            current_stage = f"Researching: {task}"

            add_log(
                f"RESEARCH STARTED | {task}",
                "bold yellow",
            )

        elif name == "researcher_completed":

            task = payload.get("subtask", "Unknown task")

            if task in researchers:
                researchers[task]["status"] = "COMPLETED"

            completed_researchers += 1

            source_count = payload.get("source_count", 0)

            add_log(
                f"RESEARCH COMPLETED | {task} | Sources: {source_count}",
                "bold green",
            )

        elif name == "researcher_failed":

            task = payload.get("subtask", "Unknown task")

            if task in researchers:
                researchers[task]["status"] = "FAILED"

            add_log(
                f"RESEARCH FAILED | {task} | {payload.get('error')}",
                "bold red",
            )

    # ----------------------------------------------
    # LANGGRAPH NODE EVENTS
    # ----------------------------------------------

    elif event_name == "on_chain_start":

        node = metadata.get("langgraph_node")

        if node:

            current_stage = node.upper()

            add_log(
                f"NODE STARTED | {node}",
                "bold cyan",
            )

    elif event_name == "on_chain_end":

        node = metadata.get("langgraph_node")

        if node:
            add_log(
                f"NODE COMPLETED | {node}",
                "green",
            )

        # Root graph output
        if not event.get("parent_ids"):

            output = payload.get("output")

            if isinstance(output, dict):
                return output

    # ----------------------------------------------
    # TOOL EVENTS
    # ----------------------------------------------

    elif event_name == "on_tool_start":

        tool_count += 1

        current_stage = f"Executing Tool: {name}"

        tool_input = payload.get("input", {})

        add_log(
            f"TOOL STARTED | {name} | {shorten(tool_input)}",
            "bold magenta",
        )

    elif event_name == "on_tool_end":

        output = payload.get("output", "")

        add_log(
            f"TOOL COMPLETED | {name} | {shorten(output)}",
            "green",
        )

    elif event_name == "on_tool_error":

        add_log(
            f"TOOL ERROR | {name} | {shorten(payload)}",
            "bold red",
        )

    # ----------------------------------------------
    # LLM EVENTS
    # ----------------------------------------------

    elif event_name == "on_chat_model_start":

        add_log(
            f"LLM STARTED | {name}",
            "blue",
        )

    elif event_name == "on_chat_model_end":

        add_log(
            f"LLM COMPLETED | {name}",
            "blue",
        )

    return None


# --------------------------------------------------
# MAIN WORKFLOW
# --------------------------------------------------


async def main():

    global workflow_status
    global current_stage
    global retry_count

    final_state = None

    add_log(
        "Initializing DeepResearch workflow...",
        "bold cyan",
    )

    console.print()

    try:

        with Live(
            render_dashboard(),
            console=console,
            refresh_per_second=8,
            screen=False,
        ) as live:

            async for event in research_graph.astream_events(
                INITIAL_STATE,
                version="v2",
                config={
                    "recursion_limit": 50,
                },
            ):

                output = process_event(event)

                if output is not None:
                    final_state = output

                # Keep retry count synchronized
                if final_state:
                    retry_count = final_state.get("retry_count", retry_count)

                live.update(render_dashboard())

        workflow_status = "COMPLETED"
        current_stage = "Workflow finished"

        console.print()

        console.print(
            Panel(
                "[bold green]WORKFLOW COMPLETED SUCCESSFULLY[/bold green]",
                border_style="green",
            )
        )

        if final_state:

            retry_count = final_state.get("retry_count", 0)

            report = final_state.get("final_research", "")

            console.print(
                Panel(
                    report or "No final research generated.",
                    title="FINAL RESEARCH REPORT",
                    border_style="green",
                    expand=True,
                )
            )

            console.print(
                f"\n[bold cyan]Final Critic Score:[/bold cyan] "
                f"{final_state.get('critic_score', 'N/A')}"
            )

            console.print(f"[bold cyan]Total Retries:[/bold cyan] " f"{retry_count}")

        else:

            console.print(
                "[yellow]Graph finished, but final state was not captured.[/yellow]"
            )

    except Exception as exc:

        workflow_status = "FAILED"

        console.print()

        console.print(
            Panel(
                f"[bold red]WORKFLOW FAILED[/bold red]\n\n{exc}",
                border_style="red",
            )
        )

        raise


if __name__ == "__main__":
    asyncio.run(main())
