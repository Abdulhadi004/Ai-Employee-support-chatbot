
from groq import Groq
import os
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def transcribe_audio(audio_path):
    """
    Convert an audio file into text using Groq Whisper.
    Supports automatic language detection.
    """

    try:
        with open(audio_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                file=audio_file,
                model="whisper-large-v3-turbo",
                response_format="text",
                temperature=0.0
            )

        return transcription

    except Exception as e:
        print(f"Audio transcription error: {e}")
        raise
