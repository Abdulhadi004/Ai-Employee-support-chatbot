
from pathlib import Path

from langchain_community.document_loaders import (
    DirectoryLoader,
    TextLoader,
    PyPDFLoader,
    Docx2txtLoader
)

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS


BASE_DIR = Path(__file__).resolve().parent
KNOWLEDGE_BASE_DIR = BASE_DIR / "knowledge_base"
FAISS_DIR = BASE_DIR / "faiss_index"

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def ingest_documents():

    print("Loading knowledge base documents...")

    if not KNOWLEDGE_BASE_DIR.exists():
        raise FileNotFoundError(
            f"Knowledge base folder not found: {KNOWLEDGE_BASE_DIR}"
        )

    documents = []

    # Load TXT files
    print("\nLoading TXT files...")

    txt_loader = DirectoryLoader(
        str(KNOWLEDGE_BASE_DIR),
        glob="**/*.txt",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"}
    )

    txt_documents = txt_loader.load()
    documents.extend(txt_documents)

    # Load PDF files
    print("Loading PDF files...")

    pdf_loader = DirectoryLoader(
        str(KNOWLEDGE_BASE_DIR),
        glob="**/*.pdf",
        loader_cls=PyPDFLoader
    )

    pdf_documents = pdf_loader.load()
    documents.extend(pdf_documents)

    # Load Word DOCX files
    print("Loading Word documents...")

    docx_loader = DirectoryLoader(
        str(KNOWLEDGE_BASE_DIR),
        glob="**/*.docx",
        loader_cls=Docx2txtLoader
    )

    docx_documents = docx_loader.load()
    documents.extend(docx_documents)

    if not documents:
        raise ValueError(
            "No PDF, DOCX, or TXT documents found in knowledge_base."
        )

    print(f"\nTotal document pages/files loaded: {len(documents)}")
    print(f"TXT files: {len(txt_documents)}")
    print(f"PDF pages: {len(pdf_documents)}")
    print(f"DOCX files: {len(docx_documents)}")

    print("\nSplitting documents into chunks...")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=100
    )

    chunks = text_splitter.split_documents(documents)

    print(f"Total chunks created: {len(chunks)}")

    print("\nLoading Hugging Face embedding model...")

    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True}
    )

    print("\nCreating FAISS vector database...")

    vector_store = FAISS.from_documents(
        documents=chunks,
        embedding=embeddings
    )

    print("\nSaving FAISS index...")

    FAISS_DIR.mkdir(parents=True, exist_ok=True)

    vector_store.save_local(str(FAISS_DIR))

    print("\nIngestion completed successfully!")
    print(f"Loaded documents/pages: {len(documents)}")
    print(f"Total chunks: {len(chunks)}")
    print(f"FAISS location: {FAISS_DIR}")


if __name__ == "__main__":
    ingest_documents()
