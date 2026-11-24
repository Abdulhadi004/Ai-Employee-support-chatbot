# AI Customer Support and HR Assistant

An enterprise-style customer support application built with **FastAPI**, **LangGraph**, **Groq**, **FAISS**, and **SQLite**. It combines a multilingual-capable chatbot, retrieval-augmented generation (RAG), persistent conversations, OCR document extraction, voice transcription, employee management, leave requests, attendance, and role-based administration.

The system includes a customer-facing chat interface and separate HR dashboards for employee and leave management.

## Key Features

- **LangGraph support workflow** for intent classification and category-specific responses
- **RAG-powered knowledge retrieval** from PDF, DOCX, and text files
- **Groq-powered chat and voice transcription**
- **Persistent chat history and user memory** using SQLite
- **JWT authentication** with employee, HR admin, and super-admin roles
- **OCR document extraction** for identity cards and payment cards
- **Audio transcription** for voice chat
- **Employee registration and approval workflow**
- **Department management and HR reports**
- **Leave request submission and approval**
- **Attendance tracking and dashboard summaries**
- **Responsive employee, leave, and HR web interfaces**

## Application Interfaces

| Interface | URL | Purpose |
|---|---|---|
| Customer chat | `http://localhost:8000/` | Login, chat, voice input, conversations, and memories |
| HR administration | `http://localhost:8000/admin` | Employees, departments, registrations, leave reviews, attendance, and reports |
| Employee leave | `http://localhost:8000/leave` | Submit and review personal leave requests |
| Swagger documentation | `http://localhost:8000/docs` | Interactive REST API documentation |
| Health check | `http://localhost:8000/health` | Service status |

## Technology Stack

- **Backend:** FastAPI, Uvicorn
- **AI orchestration:** LangGraph
- **Language models:** Groq, LangChain
- **Knowledge retrieval:** Hugging Face embeddings, FAISS
- **OCR:** RapidOCR, EasyOCR, OpenCV
- **Voice:** Groq Whisper
- **Authentication:** JWT, `pwdlib`
- **Databases:** SQLite
- **Frontend:** HTML, CSS, JavaScript

## Project Structure

```text
.
├── api.py                  # FastAPI application and REST endpoints
├── auth.py                 # Authentication and role management
├── graph.py                # LangGraph workflow and checkpointing
├── nodes.py                # Classification and support response nodes
├── rag.py                  # FAISS retrieval implementation
├── ingest.py               # Knowledge-base ingestion script
├── hr_db.py                # HR, attendance, and leave database operations
├── chat_db.py              # Conversation persistence
├── user_memory.py          # User preference and memory storage
├── image_ocr.py            # Image preprocessing and OCR
├── document_extractor.py   # Document classification and extraction
├── voice_agent.py          # Groq Whisper transcription
├── frontend/               # Chat, HR, and leave interfaces
├── knowledge_base/         # Source documents for RAG
├── faiss_index/            # Generated vector index
└── tests/                  # OCR, authentication, and feature tests
```

## Prerequisites

- Python 3.10 or later
- A [Groq API key](https://console.groq.com/)
- Windows PowerShell or a compatible shell
- At least 4 GB of available RAM; OCR and embedding models may require more

## Installation

### 1. Clone the repository

```powershell
git clone <repository-url>
cd <repository-folder>
```

### 2. Create and activate a virtual environment

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

If script execution is disabled, use Command Prompt:

```bat
venv\Scripts\activate.bat
```

### 3. Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
GROQ_API_KEY=your_groq_api_key
JWT_SECRET_KEY=replace-with-a-long-random-secret

# Optional: creates the initial super administrator
SUPER_ADMIN_EMAIL=admin@example.com
SUPER_ADMIN_PASSWORD=replace-with-a-unique-password-of-at-least-12-characters
```

Generate a secure JWT secret with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Never commit `.env`, API keys, passwords, database files, or generated indexes to source control.

### 5. Build the knowledge index

Place PDF, DOCX, or TXT documents in `knowledge_base/`, then run:

```powershell
python ingest.py
```

This creates the FAISS index in `faiss_index/`. Re-run ingestion whenever source documents change.

### 6. Start the application

```powershell
python -m uvicorn api:api --reload
```

Open `http://localhost:8000/`.

## Super-Admin Bootstrap

Set `SUPER_ADMIN_EMAIL` and `SUPER_ADMIN_PASSWORD` before the first startup to create the initial super administrator. Both variables must be set together.

The super admin can assign assignable roles through:

```http
PUT /admin/users/role
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "email": "person@example.com",
  "role": "hr_admin"
}
```

Available roles are `employee`, `hr_admin`, and `super_admin`.

## Example API Workflow

1. Register or log in through `/register` or `/login`.
2. Use the returned bearer token to call authenticated endpoints.
3. Send a chat message to `/chat`.
4. Upload an image to `/extract-document`.
5. Upload supported audio to `/voice-chat`.

Example login request:

```http
POST /login
Content-Type: application/json

{
  "email": "employee@example.com",
  "password": "your-password"
}
```

## RAG Workflow

1. Source files are loaded from `knowledge_base/`.
2. LangChain splits documents into overlapping chunks.
3. Hugging Face embeddings are generated locally.
4. Chunks are stored in a FAISS index.
5. LangGraph retrieves relevant context for support requests.
6. Groq generates the final response using the retrieved context.

## Data and Privacy

The application uses local SQLite databases for users, employees, conversations, memories, and checkpoints. HR data is filtered according to the authenticated user's role and identity.

Document extraction masks common sensitive identifiers, such as CNIC and card numbers, before formatting extracted output. Uploaded temporary files should be handled according to your organization's retention policy.

For production use, add:

- Persistent external databases
- Managed secrets
- HTTPS and secure CORS configuration
- Database backups
- Audit logging
- Rate limiting
- Access-control review
- Compliance-specific document retention

## Testing

Run the test suite from the project root:

```powershell
python -m pytest tests
```

Individual tests can be run with:

```powershell
python -m pytest tests/test_auth_roles.py -v
```

## Troubleshooting

### `GROQ_API_KEY not found in .env file`

Verify that `.env` exists in the project root and contains a valid `GROQ_API_KEY`.

### `FAISS index not found`

Run `python ingest.py` before starting or using the API.

### JWT configuration error

Set `JWT_SECRET_KEY` in `.env` and restart the server.

### EasyOCR download or memory issues

RapidOCR is used first. EasyOCR is loaded lazily only when needed and may require additional model downloads and memory.

## Contributing

Contributions are welcome.

1. Fork the repository.
2. Create a feature branch.
3. Make focused changes and add tests.
4. Run the relevant test suite.
5. Submit a pull request with a clear description.

## License

Add a `LICENSE` file and specify the project's license before public distribution.
