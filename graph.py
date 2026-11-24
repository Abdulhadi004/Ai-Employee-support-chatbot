from pathlib import Path
import sqlite3

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

from state import SupportState

from nodes import (
    classify_message,
    retrieve_knowledge,
    payment_handler,
    account_handler,
    leave_handler,
    general_handler
)


# ----------------------------------
# ROUTING FUNCTION
# ----------------------------------

def route_category(state):

    category = state["category"]

    if category == "Payment":
        return "payment"

    elif category == "Account":
        return "account"

    elif category == "Leave":
        return "leave"

    else:
        return "general"


# ----------------------------------
# CREATE GRAPH
# ----------------------------------

workflow = StateGraph(SupportState)


# Register nodes
workflow.add_node("classifier", classify_message)
workflow.add_node("retriever", retrieve_knowledge)

workflow.add_node("payment", payment_handler)
workflow.add_node("account", account_handler)
workflow.add_node("leave", leave_handler)
workflow.add_node("general", general_handler)


# ----------------------------------
# CONNECT NODES
# ----------------------------------

workflow.add_edge(START, "classifier")

workflow.add_edge("classifier", "retriever")


# Conditional routing
workflow.add_conditional_edges(
    "retriever",
    route_category,
    {
        "payment": "payment",
        "account": "account",
        "leave": "leave",
        "general": "general"
    }
)


# Connect handlers to END
workflow.add_edge("payment", END)
workflow.add_edge("account", END)
workflow.add_edge("leave", END)
workflow.add_edge("general", END)


# ----------------------------------
# SQLITE PERSISTENT CHECKPOINTING
# ----------------------------------

BASE_DIR = Path(__file__).resolve().parent

CHECKPOINT_DB = BASE_DIR / "checkpoints.sqlite"

# Create SQLite connection
connection = sqlite3.connect(
    str(CHECKPOINT_DB),
    check_same_thread=False
)

# Initialize persistent checkpointer
memory = SqliteSaver(connection)

# Create checkpoint tables if they do not exist
memory.setup()

# Compile graph with persistent memory
app = workflow.compile(checkpointer=memory)

print("LangGraph initialized with SQLite persistent memory.")