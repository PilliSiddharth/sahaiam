# import base64
# import json
# import threading

# from flask import Flask, render_template
# from flask_sockets import Sockets
# from google.cloud.speech import RecognitionConfig, StreamingRecognitionConfig

# from SpeechClientBridge import SpeechClientBridge

# HTTP_SERVER_PORT = 8080

# config = RecognitionConfig(
#     encoding=RecognitionConfig.AudioEncoding.MULAW,
#     sample_rate_hertz=8000,
#     language_code="en-US",
# )
# streaming_config = StreamingRecognitionConfig(config=config, interim_results=True)

# app = Flask(__name__)
# sockets = Sockets(app)


# @app.route("/twiml", methods=["POST"])
# def return_twiml():
#     print("POST TwiML")
#     return render_template("streams.xml")


# def on_transcription_response(response):
#     if not response.results:
#         return

#     result = response.results[0]
#     if not result.alternatives:
#         return

#     transcription = result.alternatives[0].transcript
#     print("Transcription: " + transcription)


# @sockets.route("/")
# def transcript(ws):
#     print("WS connection opened")
#     bridge = SpeechClientBridge(streaming_config, on_transcription_response)
#     t = threading.Thread(target=bridge.start)
#     t.start()

#     while not ws.closed:
#         message = ws.receive()
#         if message is None:
#             bridge.add_request(None)
#             bridge.terminate()
#             break

#         data = json.loads(message)
#         if data["event"] in ("connected", "start"):
#             print(f"Media WS: Received event '{data['event']}': {message}")
#             continue
#         if data["event"] == "media":
#             media = data["media"]
#             chunk = base64.b64decode(media["payload"])
#             bridge.add_request(chunk)
#         if data["event"] == "stop":
#             print(f"Media WS: Received event 'stop': {message}")
#             print("Stopping...")
#             break

#     bridge.terminate()
#     print("WS connection closed")


# if __name__ == "__main__":
#     from gevent import pywsgi
#     from geventwebsocket.handler import WebSocketHandler

#     server = pywsgi.WSGIServer(
#         ("", HTTP_SERVER_PORT), app, handler_class=WebSocketHandler
#     )
#     print("Server listening on: http://localhost:" + str(HTTP_SERVER_PORT))
#     server.serve_forever()

# thank you lord my code is finally getting transcriptions
import base64
import json
import threading
from io import BytesIO
import time

current_sentence = ""
last_timestamp = 0
sentence_timeout = 1.5

from flask import Flask, render_template
from flask_sockets import Sockets
from google.cloud.speech import RecognitionConfig, StreamingRecognitionConfig
from gtts import gTTS
import openai  # GPT-4 integration

from SpeechClientBridge import SpeechClientBridge

# GPT-4 API setup
openai.api_key = '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'  # Replace with your OpenAI API key

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


# def on_transcription_response(response):
#     if not response.results:
#         return

#     result = response.results[0]
#     if not result.alternatives:
#         return

#     transcription = result.alternatives[0].transcript
#     print("Transcription: " + transcription)

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
        # Append only the new part of the transcription
        if len(transcription) > len(current_sentence):
            current_sentence += transcription[len(current_sentence):]
        
        print("Complete Sentence:", current_sentence)

        gpt_response = get_gpt_response(current_sentence)
        print("GPT Response:", gpt_response)

        current_sentence = ""
        last_timestamp = current_time


# # current_sentence = ""

# def on_transcription_response(response, ws):
#     global current_sentence

#     if not response.results:
#         return

#     result = response.results[0]
#     if not result.alternatives:
#         return

#     transcription = result.alternatives[0].transcript
#     is_final = result.is_final

#     if is_final:
#         current_sentence += transcription
#         print("Final Transcription:", current_sentence)
        
#         # Process the complete sentence with GPT-4
#         gpt_response = get_gpt_response(current_sentence)
#         print("GPT Response:", gpt_response)
        
#         # Convert GPT-4 response to speech and send it back to Twilio
#         # audio_data = convert_text_to_speech(gpt_response)
#         # send_audio_to_twilio(audio_data, ws)
        
#         Reset the current sentence
#         current_sentence = ""
    else:
        # Accumulate partial results
        if len(transcription) > len(current_sentence):
            current_sentence = transcription
            last_timestamp = current_time

# def on_transcription_response(response, ws):
#     if not response.results:
#         return

#     result = response.results[0]
#     if not result.alternatives:
#         return

#     transcription = result.alternatives[0].transcript
#     print("Transcription: " + transcription)
#     # print("Result: "result)

#     # Process transcription with GPT-4
#     gpt_response = get_gpt_response(transcription)
#     print(gpt_response)
    
    # Convert GPT-4 response to speech using gTTS
    # audio_data = convert_text_to_speech(gpt_response)

    # Send the generated audio back to Twilio via WebSocket
    # send_audio_to_twilio(audio_data, ws)


def get_gpt_response(prompt):
    """Get response from GPT-4 using the v1/chat/completions endpoint."""
    response = openai.ChatCompletion.create(
        model="gpt-4",  # Use the chat model (gpt-4)
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=150  # Adjust the token limit based on your needs
    )
    return response['choices'][0]['message']['content'].strip()


def convert_text_to_speech(text):
    """Convert text to speech using gTTS and return the audio data."""
    tts = gTTS(text, lang='en')  # Adjust the language as per your requirements
    audio_fp = BytesIO()
    tts.write_to_fp(audio_fp)
    audio_fp.seek(0)
    return audio_fp.read()


def send_audio_to_twilio(audio_data, ws):
    """Send the audio data to Twilio via WebSocket."""
    # Convert audio data to base64 for streaming
    audio_b64 = base64.b64encode(audio_data).decode('utf-8')
    
    # Frame the WebSocket message in the Twilio Media Stream format
    ws.send(json.dumps({
        "event": "media",
        "media": {
            "payload": audio_b64
        }
    }))


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