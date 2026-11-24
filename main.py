
from graph import app


def run_support_system():

    print("\n================================")
    print("   AI CUSTOMER SUPPORT SYSTEM")
    print("   LANGGRAPH + GEMINI + RAG")
    print("================================")

    while True:

        user_message = input(
            "\nEnter customer message (or type 'exit'): "
        )

        if user_message.lower() == "exit":
            print("Thank you for using the system!")
            break

        if not user_message.strip():
            print("Please enter a valid message.")
            continue

        initial_state = {
            "message": user_message,
            "category": "",
            "context": "",
            "response": ""
        }

        try:

            result = app.invoke(initial_state)

            print("\n========== FINAL RESULT ==========")

            print("Category:", result["category"])

            print("\nRetrieved Context:")
            print(result["context"])

            print("\nAI Support Response:")
            print(result["response"])

            print("==================================")

        except Exception as e:

            print("\nApplication Error:", str(e))


if __name__ == "__main__":
    run_support_system()
