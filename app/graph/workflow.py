from langgraph.graph import StateGraph, START, END

from app.graph.state import ResearchState

# Nodes
from app.graph.nodes.supervisor import supervisor_node
from app.graph.nodes.researcher import researcher_node
from app.graph.nodes.aggregator import aggregator_node
from app.graph.nodes.critic import critic_node
from app.graph.nodes.retry import retry_node
from app.graph.nodes.final_report import final_report_node

# Dispatchers
from app.graph.dispatchers.research import dispatch_researchers
from app.graph.dispatchers.retry import dispatch_retry_researchers

# Router
from app.graph.routers.critic_router import critic_router

# Initialize graph
builder = StateGraph(ResearchState)


# Register nodes
builder.add_node("supervisor", supervisor_node)
builder.add_node("researcher", researcher_node)
builder.add_node("aggregator", aggregator_node)
builder.add_node("critic", critic_node)
builder.add_node("retry", retry_node)
builder.add_node("final_report", final_report_node)


# START -> SUPERVISOR
builder.add_edge(START, "supervisor")


# SUPERVISOR -> PARALLEL RESEARCHERS
builder.add_conditional_edges(
    "supervisor",
    dispatch_researchers,
    ["researcher"],
)


# RESEARCHERS -> AGGREGATOR
builder.add_edge("researcher", "aggregator")


# AGGREGATOR -> CRITIC
builder.add_edge("aggregator", "critic")


# CRITIC -> FINAL REPORT OR RETRY
builder.add_conditional_edges(
    "critic",
    critic_router,
    {
        "final_report": "final_report",
        "retry_research": "retry",
    },
)


# RETRY -> TARGETED PARALLEL RESEARCHERS
builder.add_conditional_edges(
    "retry",
    dispatch_retry_researchers,
    ["researcher"],
)


# FINAL REPORT -> END
builder.add_edge("final_report", END)


# Compile graph
research_graph = builder.compile()
