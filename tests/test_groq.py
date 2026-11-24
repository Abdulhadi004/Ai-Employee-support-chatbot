
import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_groq import ChatGroq

# Load environment variables from .env
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Get API key
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY not found in .env file")

# Initialize Groq model
llm = ChatGroq(
    model="openai/gpt-oss-20b",
    api_key=GROQ_API_KEY,
    temperature=0,
    max_retries=2
)

# Test the model
response = llm.invoke(
    "Explain what a customer support chatbot does in simple words."
)

print("\nGroq Response:")
print(response.content)
