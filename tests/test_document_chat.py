import unittest
from types import SimpleNamespace
from unittest.mock import patch

from api import (
    ChatRequest,
    answer_profile_question,
    chat as chat_endpoint,
    format_extracted_information,
    get_uploaded_document_context
)
from nodes import generate_response


class DocumentChatTests(unittest.TestCase):
    def test_formats_subjects_as_readable_rows(self):
        formatted = format_extracted_information({
            "student_name": "Example Student",
            "subjects": [
                {
                    "subject": "Biology",
                    "marks_obtained": "78",
                    "total_marks": "100",
                    "grade": "A"
                }
            ]
        })

        self.assertIn("Student Name: Example Student", formatted)
        self.assertIn(
            "- Biology (Marks Obtained: 78; Total Marks: 100; Grade: A)",
            formatted
        )

    def test_finds_prior_uploaded_document_messages(self):
        messages = [
            {
                "role": "assistant",
                "content": "Previous chat answer."
            },
            {
                "role": "assistant",
                "content": (
                    "Document type: Marksheet\n"
                    "Extracted information:\n"
                    "Student Name: Example Student"
                )
            }
        ]

        context = get_uploaded_document_context(messages)

        self.assertIn("Student Name: Example Student", context)
        self.assertNotIn("Previous chat answer.", context)

    def test_prefers_the_most_recent_uploaded_document(self):
        context = get_uploaded_document_context([
            {
                "role": "assistant",
                "content": (
                    "Document type: Marksheet\n"
                    "Extracted information:\n"
                    "Student Name: Older Document"
                )
            },
            {
                "role": "assistant",
                "content": (
                    "Document type: Marksheet\n"
                    "Extracted information:\n"
                    "Student Name: Latest Document"
                )
            }
        ])

        response = answer_profile_question(
            "What is my name?",
            {},
            context
        )

        self.assertEqual(
            response,
            "The name shown on the uploaded document is Latest Document."
        )

    def test_name_question_uses_name_from_uploaded_document(self):
        response = answer_profile_question(
            "What is my name?",
            {
                "first_name": "Account",
                "last_name": "Name",
                "email": "user@example.com",
                "phone": None
            },
            "Document type: Marksheet\n"
            "Extracted information:\n"
            "Student Name: Document Name"
        )

        self.assertEqual(
            response,
            "The name shown on the uploaded document is Document Name."
        )

    def test_chat_route_passes_saved_upload_to_response_graph(self):
        uploaded_message = (
            "Document type: Marksheet\n"
            "Extracted information:\n"
            "Student Name: Document Name\n"
            "Subjects:\n"
            "- Biology (Marks Obtained: 78)"
        )
        current_user = {
            "id": 42,
            "email": "user@example.com",
            "role": "customer"
        }

        with patch("api.get_user_conversation", return_value={"id": "chat"}), \
                patch("api.save_message"), \
                patch("api.get_user_profile", return_value={
                    "first_name": "Account",
                    "last_name": "Name",
                    "email": "user@example.com",
                    "phone": None
                }), \
                patch("api.get_conversation_messages", return_value=[
                    {"role": "assistant", "content": uploaded_message}
                ]), \
                patch("api.get_chat_employee_context", return_value=""), \
                patch("api.graph_app.invoke", return_value={
                    "response": "Biology: 78",
                    "category": "General"
                }) as invoke:
            response = chat_endpoint(
                ChatRequest(
                    message="What subjects and marks are shown?",
                    conversation_id="chat"
                ),
                current_user
            )

        initial_state = invoke.call_args.args[0]
        self.assertIn("Biology (Marks Obtained: 78)", initial_state["document_context"])
        self.assertEqual(response["response"], "Biology: 78")

    def test_response_generation_uses_document_context_without_rag_context(self):
        with patch("nodes.llm") as llm:
            llm.invoke.return_value = SimpleNamespace(
                content="The name shown is Document Name."
            )
            response = generate_response(
                category="General",
                message="What is my name?",
                context="",
                history=[{"role": "user", "content": "What is my name?"}],
                document_context="Student Name: Document Name"
            )

        prompt = llm.invoke.call_args.args[0]
        self.assertIn("Student Name: Document Name", prompt)
        self.assertEqual(response, "The name shown is Document Name.")


if __name__ == "__main__":
    unittest.main()
