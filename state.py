
from typing import TypedDict, Annotated
import operator


class SupportState(TypedDict):

    # Current customer message
    message: str

    # Customer account ID
    user_id: int

    # Message classification
    category: str

    # Retrieved company knowledge
    context: str

    # Retrieved long-term user memories
    user_memories: str

    # HR data restricted to the authenticated user's access scope
    employee_context: str

    # Extracted information from documents uploaded in this conversation
    document_context: str

    # Summary of older conversation messages
    conversation_summary: str
    
    # Number of messages already included in the summary
    summarized_message_count: int

    # Generated AI response
    response: str

    # Previous user and assistant messages
    chat_history: Annotated[list[dict], operator.add]
