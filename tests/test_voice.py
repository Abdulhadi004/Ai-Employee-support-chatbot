
from voice_agent import transcribe_audio

audio_path = "test_audio.mp3"

text = transcribe_audio(audio_path)

print("\nTranscribed Text:")
print(text)
