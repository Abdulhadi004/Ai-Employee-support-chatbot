
from pathlib import Path

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
FAISS_DIR = BASE_DIR / "faiss_index"

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Minimum relevance score required to accept a document
RELEVANCE_THRESHOLD = 0.35


# --------------------------------------------------
# LOAD EMBEDDING MODEL
# --------------------------------------------------

print("Loading Hugging Face embedding model...")

embeddings = HuggingFaceEmbeddings(
    model_name=EMBEDDING_MODEL,
    model_kwargs={"device": "cpu"},
    encode_kwargs={"normalize_embeddings": True}
)


# --------------------------------------------------
# LOAD FAISS VECTOR DATABASE
# --------------------------------------------------

def load_vector_store():

    if not FAISS_DIR.exists():

        raise FileNotFoundError(
            "FAISS index not found. Run python ingest.py first."
        )

    return FAISS.load_local(
        str(FAISS_DIR),
        embeddings,
        allow_dangerous_deserialization=True
    )


vector_store = load_vector_store()


# --------------------------------------------------
# RETRIEVE RELEVANT COMPANY DOCUMENTS
# --------------------------------------------------


def retrieve_context(
    query,
    k=5,
    distance_threshold=1.1
):

    print("\nSearching knowledge base...")

    # Get raw FAISS distances
    results = vector_store.similarity_search_with_score(
        query,
        k=k
    )

    if not results:

        print("No documents found.")

        return ""

    relevant_documents = []

    for document, distance in results:

        print(f"FAISS distance: {distance:.3f}")

        # Lower distance means greater similarity
        if distance <= distance_threshold:

            print("Document accepted.")

            relevant_documents.append(
                (document, distance)
            )

        else:

            print("Document rejected: distance too high.")

    if not relevant_documents:

        print("\nNo sufficiently relevant documents found.")

        return ""

    context = ""

    for i, (document, distance) in enumerate(
        relevant_documents,
        start=1
    ):

        source = document.metadata.get(
            "source",
            "Unknown"
        )

        context += f"""
Document {i}
Source: {source}
FAISS Distance: {distance:.3f}

Content:
{document.page_content}

"""

    print(
        f"\nRelevant documents retrieved: "
        f"{len(relevant_documents)}"
    )

    return context

if __name__ == "__main__":

    question = input("Enter your question: ")

    context = retrieve_context(question)

    print("\n========== RETRIEVED CONTEXT ==========")

    print(context)