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
from pydub import AudioSegment
current_sentence = ""
last_timestamp = 0
sentence_timeout = 1.5

from flask import Flask, render_template
from flask_sockets import Sockets
from google.cloud.speech import RecognitionConfig, StreamingRecognitionConfig
from gtts import gTTS
import openai  # GPT-4 integration
import wave
import audioop

from SpeechClientBridge import SpeechClientBridge

# GPT-4 API setup
openai.api_key = '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'  # Replace with your OpenAI API key

HTTP_SERVER_PORT = 8080

# streadSid = None
# global streamSid

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
        # Append only the new part of the transcription
        if len(transcription) > len(current_sentence):
            current_sentence += transcription[len(current_sentence):]
        
        print("Complete Sentence:", current_sentence)

        gpt_response = get_gpt_response(current_sentence)
        print("GPT Response:", gpt_response)
        send_static_audio(ws)

        # send_gpt_response_as_audio(gpt_response, ws)
        


        current_sentence = ""
        last_timestamp = current_time
    else:

        if len(transcription) > len(current_sentence):
            current_sentence = transcription
            last_timestamp = current_time



def get_gpt_response(prompt):
    """Get response from GPT-4 using the v1/chat/completions endpoint."""
    response = openai.ChatCompletion.create(
        model="gpt-4o",  
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=150  
    )
    return response['choices'][0]['message']['content'].strip()

def send_gpt_response_as_audio(text, ws):
    try:
        # Convert the GPT response to speech (TTS)
        tts = gTTS(text, lang='en')
        audio_fp = BytesIO()
        tts.write_to_fp(audio_fp)
        audio_fp.seek(0)

        # Convert the TTS audio to the required format for Twilio
        audio_segment = AudioSegment.from_mp3(audio_fp)
        audio_segment = audio_segment.set_frame_rate(8000).set_channels(1).set_sample_width(1)
        audio_data = BytesIO()
        audio_segment.export(audio_data, format="wav", codec="pcm_mulaw")
        audio_data = audio_data.getvalue()

        # Split and send the audio data in chunks
        # CHUNK_SIZE = 1024  # Adjust chunk size if necessary
        # for i in range(0, len(audio_data), CHUNK_SIZE):
        #     chunk = audio_data[i:i + CHUNK_SIZE]
        audio_b64 = base64.b64encode(chunk).decode('utf-8')
        message = json.dumps({
            "event": "media",
            "media": {
                "payload": audio_b64
            }
        })
        ws.send(message)
            # sleep(0.1)  # Small delay to prevent overwhelming the WebSocket connection

        print("Audio sent successfully")
    
    except Exception as e:
        print(f"Error sending audio: {e}")

def send_static_audio(ws):
    try:
        with open("tts_output.wav", "rb") as wav_file:
            with wave.open(wav_file, "rb") as wav:
                # Read raw audio data
                raw_wav = wav.readframes(wav.getnframes())

                # Convert raw audio data to AudioSegment
                audio_segment = AudioSegment(
                    data=raw_wav,
                    sample_width=wav.getsampwidth(),
                    frame_rate=wav.getframerate(),
                    channels=wav.getnchannels()
                )

                # Convert to 8kHz and mono if necessary
                if audio_segment.channels == 2:
                    audio_segment = audio_segment.set_channels(1)
                resampled = audioop.ratecv(audio_segment.raw_data, audio_segment.sample_width, 1, audio_segment.frame_rate, 8000, None)[0]
                pcm_audio_segment = AudioSegment(data=resampled, sample_width=audio_segment.sample_width, frame_rate=8000, channels=1)

                # Export audio segment to WAV
                pcm_audio_fp = BytesIO()
                pcm_audio_segment.export(pcm_audio_fp, format='wav')
                pcm_audio_fp.seek(0)
                pcm_data = pcm_audio_fp.read()

                # Convert PCM audio to mu-law
                ulaw_data = audioop.lin2ulaw(pcm_data, pcm_audio_segment.sample_width)

                # Encode audio to base64
                audio_b64 = base64.b64encode(ulaw_data).decode('utf-8')

                # Read streamSid
                with open("streamSid.txt", "r") as f:
                    stream_sid = f.read().strip()

                # Send audio data
                message = json.dumps({
                    'event': 'media',
                    'streamSid': stream_sid,
                    'media': {'payload': audio_b64}
                })
                ws.send(message)
                time.sleep(0.05)  # Small delay to avoid overwhelming the WebSocket connection

        print("Static audio sent successfully")
    except Exception as e:
        print(f"Error sending static audio: {e}")
# def send_static_audio(ws):
#     try:
#         with wave.open("tts_output.wav", "rb") as wav:
#             raw_wav= wav.readframes(wav.getnframes())   
#             audio_b64 = base64.b64encode(raw_wav).decode("utf-8")
#             with open("streamSid.txt", "r") as f:
#                 streamSid = f.read().strip()
#             print("streamid: ", streamSid)
#             message = json.dumps({
#                 "event": "media",
#                 "streamSid": streamSid,
#                 "media": {
#                     "payload": audio_b64
#                 }
#             })
#             ws.send(message)
#             # sleep(0.1)  # Small delay between chunks

#         print("Static audio sent successfully")
#     except Exception as e:
#         print(f"Error sending static audio: {e}")


# def send_static_audio(ws):
#     try:
#         with wave.open("tts_output.wav", "rb") as wav:
#             # Ensure that the audio is in the correct format (PCM mu-law, 8kHz)
#             if wav.getframerate() != 8000 or wav.getsampwidth() != 1 or wav.getnchannels() != 1:
#                 raise ValueError("Audio format is incorrect. Ensure PCM mu-law, 8kHz, mono.")

#             # Read raw audio data
#             raw_wav = wav.readframes(wav.getnframes())

#             # Convert raw audio to mu-law if necessary
#             if wav.getsampwidth() != 1:
#                 raw_wav = audioop.lin2ulaw(raw_wav, wav.getsampwidth())

#             # Break the raw_wav data into smaller chunks
#             CHUNK_SIZE = 1024  # Adjust this size as necessary
#             with open("streamSid.txt", "r") as f:
#                 streamSid = f.read().strip()
            
#             for i in range(0, len(raw_wav), CHUNK_SIZE):
#                 chunk = raw_wav[i:i + CHUNK_SIZE]
#                 audio_b64 = base64.b64encode(chunk).decode("utf-8")
#                 message = json.dumps({
#                     "event": "media",
#                     "streamSid": streamSid,
#                     "media": {
#                         "payload": audio_b64
#                     }
#                 })
#                 ws.send(message)
#                 time.sleep(0.05)

#         print("Static audio sent successfully")
#     except Exception as e:
#         print(f"Error sending static audio: {e}")

# def send_static_audio(ws):
#     try:
#         # Open the TTS output file
#         with wave.open("tts_output.wav", "rb") as wav:
#             # Check and ensure the format (PCM mu-law, 8kHz, mono)
#             if wav.getframerate() != 8000 or wav.getsampwidth() != 1 or wav.getnchannels() != 1:
#                 # Convert to PCM mu-law, 8kHz, mono if needed
#                 audio_data = wav.readframes(wav.getnframes())
#                 converted_audio = audioop.lin2ulaw(audio_data, wav.getsampwidth())

#                 # Create a new wave file with the correct format
#                 with wave.open("converted_output.wav", "wb") as converted_wav:
#                     converted_wav.setnchannels(1)  # mono
#                     converted_wav.setsampwidth(1)  # 8-bit mu-law
#                     converted_wav.setframerate(8000)  # 8kHz
#                     converted_wav.writeframes(converted_audio)

#                 # Use the newly created file for streaming
#                 with wave.open("converted_output.wav", "rb") as final_wav:
#                     raw_wav = final_wav.readframes(final_wav.getnframes())
#             else:
#                 # Use the original file if no conversion is needed
#                 raw_wav = wav.readframes(wav.getnframes())

#             # Stream the audio data in chunks
#             CHUNK_SIZE = 1024  # Adjust this size as necessary
#             with open("streamSid.txt", "r") as f:
#                 streamSid = f.read().strip()
            
#             for i in range(0, len(raw_wav), CHUNK_SIZE):
#                 chunk = raw_wav[i:i + CHUNK_SIZE]
#                 audio_b64 = base64.b64encode(chunk).decode("utf-8")
#                 message = json.dumps({
#                     "event": "media",
#                     "streamSid": streamSid,
#                     "media": {
#                         "payload": audio_b64
#                     }
#                 })
#                 ws.send(message)
#                 time.sleep(0.05)

#         print("Static audio sent successfully")
#     except Exception as e:
#         print(f"Error sending static audio: {e}")

# def send_gpt_response_as_audio(text, ws):
#     audio_data = convert_text_to_speech(text)
#     converted_audio = convert_audio_for_twilio(audio_data)
#     send_audio_to_twilio(converted_audio, ws)


def convert_text_to_speech(text, save_locally=True):
    print(f"Converting text to speech: {text}")
    try:
        tts = gTTS(text, lang='en')
        audio_fp = BytesIO()
        tts.write_to_fp(audio_fp)
        audio_fp.seek(0)
        audio_data = audio_fp.read()
        print(f"TTS conversion complete, audio data length: {len(audio_data)}")
        
        if save_locally:
            with open("tts_output.mp3", "wb") as f:
                f.write(audio_data)
            print("TTS output saved locally as tts_output.mp3")
        
        return audio_data
    except Exception as e:
        print(f"Error in TTS conversion: {e}")
        return None


def convert_audio_for_twilio(audio_data):
    """Convert audio to 8-bit mu-law audio at 8kHz."""
    audio = AudioSegment.from_mp3(BytesIO(audio_data))
    audio = audio.set_frame_rate(8000).set_channels(1)
    buffer = BytesIO()
    audio.export(buffer, format="wav", codec="pcm_mulaw")
    return buffer.getvalue()

def send_audio_to_twilio(audio_data, ws):
    """Send the audio data to Twilio via WebSocket."""
    if ws.closed:
        print("WebSocket is closed. Cannot send audio.")
        return
    audio_b64 = base64.b64encode(audio_data).decode('utf-8')
    try:
        message = json.dumps({
            "event": "media",
            "media": {
                "payload": audio_b64
            }
        })
        print(f"Sending audio message of length: {len(message)}")
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
        if data["event"] in ("connected"):
            print(f"Media WS: Connected event '{data['event']}': {message}")
            # streamSid = data.get("start", {}).get("streamSid")
            # print(f"Stream SID: {streamSid}")
            # with open("streamSid.txt", "w") as f:
            #         f.write(streamSid)
            continue
        if data["event"] in ("start"):
            print(f"Media WS: Received event '{data['event']}': {message}")
            streamSid = data.get("start", {}).get("streamSid")
            print(f"Stream SID: {streamSid}")
            with open("streamSid.txt", "w") as f:
                    f.write(streamSid)
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