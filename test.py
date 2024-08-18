import base64
import json
import threading
from io import BytesIO
import time
from pydub import AudioSegment
current_sentence = ""
last_timestamp = 0
sentence_timeout = 1.5
from flask import Flask, render_template
from flask_sockets import Sockets
from google.cloud.speech import RecognitionConfig, StreamingRecognitionConfig
import openai  # GPT-4 integration
# from elevenlabs import generate, set_api_key  # Eleven Labs TTS
from elevenlabs.client import ElevenLabs
from SpeechClientBridge import SpeechClientBridge

# GPT-4 API setup
openai.api_key = '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'  # Replace with your OpenAI API key

# Eleven Labs API setup
client = ElevenLabs(
  api_key="sk_bcbf6be3edcfe4f0090f713496dc0be33fd8cb481f51c257", # Defaults to ELEVEN_API_KEY
)

HTTP_SERVER_PORT = 8080

config = RecognitionConfig(
    encoding=RecognitionConfig.AudioEncoding.MULAW,
    sample_rate_hertz=8000,
    language_code="en-US",
)
streaming_config = StreamingRecognitionConfig(config=config, interim_results=True)

app = Flask(__name__)
sockets = Sockets(app)


@app.route("/twiml", methods=["POST"])
def return_twiml():
    print("POST TwiML")
    return render_template("streams.xml")


def on_transcription_response(response, ws):
    global current_sentence, last_timestamp

    if not response.results:
        return

    result = response.results[0]
    if not result.alternatives:
        return

    transcription = result.alternatives[0].transcript
    stability = result.stability
    is_final = result.is_final

    current_time = time.time()

    if is_final or (current_time - last_timestamp > sentence_timeout and stability > 0.8):
        if len(transcription) > len(current_sentence):
            current_sentence += transcription[len(current_sentence):]
        
        print("Complete Sentence:", current_sentence)

        gpt_response = get_gpt_response(current_sentence)
        print("GPT Response:", gpt_response)
        send_gpt_response_as_audio(gpt_response, ws)

        current_sentence = ""
        last_timestamp = current_time
    else:
        if len(transcription) > len(current_sentence):
            current_sentence = transcription
            last_timestamp = current_time


def get_gpt_response(prompt):
    """Get response from GPT-4 using the v1/chat/completions endpoint."""
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=150
    )
    return response['choices'][0]['message']['content'].strip()


def send_gpt_response_as_audio(text, ws):
    try:
        # Convert the GPT response to speech (TTS) using Eleven Labs
        tts_audio = client.generate(text=text, voice="21m00Tcm4TlvDq8ikWAM", model="eleven_monolingual_v1")  # Adjust voice and model as needed
        audio_fp = BytesIO(tts_audio)
        
        # Convert the TTS audio to the required format for Twilio
        audio_segment = AudioSegment.from_file(audio_fp, format="mp3")
        audio_segment = audio_segment.set_frame_rate(8000).set_channels(1).set_sample_width(1)
        audio_data = BytesIO()
        audio_segment.export(audio_data, format="wav", codec="pcm_mulaw")
        audio_data = audio_data.getvalue()

        # Split and send the audio data in chunks
        CHUNK_SIZE = 1024
        for i in range(0, len(audio_data), CHUNK_SIZE):
            chunk = audio_data[i:i + CHUNK_SIZE]
            audio_b64 = base64.b64encode(chunk).decode('utf-8')
            message = json.dumps({
                "event": "media",
                "media": {
                    "payload": audio_b64
                }
            })
            ws.send(message)

        print("Audio sent successfully")
    
    except Exception as e:
        print(f"Error sending audio: {e}")


@sockets.route("/")
def transcript(ws):
    print("WS connection opened")
    bridge = SpeechClientBridge(streaming_config, lambda response: on_transcription_response(response, ws))
    t = threading.Thread(target=bridge.start)
    t.start()

    while not ws.closed:
        message = ws.receive()
        if message is None:
            bridge.add_request(None)
            bridge.terminate()
            break

        data = json.loads(message)
        if data["event"] in ("connected", "start"):
            print(f"Media WS: Received event '{data['event']}': {message}")
            continue
        if data["event"] == "media":
            media = data["media"]
            chunk = base64.b64decode(media["payload"])
            bridge.add_request(chunk)
        if data["event"] == "stop":
            print(f"Media WS: Received event 'stop': {message}")
            print("Stopping...")
            break

    bridge.terminate()
    print("WS connection closed")


if __name__ == "__main__":
    from gevent import pywsgi
    from geventwebsocket.handler import WebSocketHandler

    server = pywsgi.WSGIServer(
        ("", HTTP_SERVER_PORT), app, handler_class=WebSocketHandler
    )
    print("Server listening on: http://localhost:" + str(HTTP_SERVER_PORT))
    server.serve_forever()
