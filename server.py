# thank you lord my code is finally getting transcriptions
import base64
import json
import threading
from io import BytesIO
import time
from pydub import AudioSegment
from flask import Flask, render_template
from flask_sockets import Sockets
from google.cloud.speech import RecognitionConfig, StreamingRecognitionConfig
from gtts import gTTS
import openai  
import wave
import audioop
from SpeechClientBridge import SpeechClientBridge

openai.api_key = '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'  # Replace with your OpenAI API key

HTTP_SERVER_PORT = 8080

partial_transcription = ""

buffer = ""
last_update_time = time.time()

current_sentence = ""
last_timestamp = 0
sentence_timeout = 2.5

buffer_lock = threading.Lock()


config = RecognitionConfig(
    encoding=RecognitionConfig.AudioEncoding.MULAW,
    sample_rate_hertz=8000,
    language_code="te-IN",
)
streaming_config = StreamingRecognitionConfig(config=config, interim_results=True)

app = Flask(__name__)
sockets = Sockets(app)


@app.route("/twiml", methods=["POST"])
def return_twiml():
    print("POST TwiML")
    return render_template("streams.xml")


def check_sentence_completion(ws):
    global buffer, last_update_time
    while True:
        time.sleep(0.1)  # Check every 100ms
        current_time = time.time()
        with buffer_lock:
            if buffer and (current_time - last_update_time > sentence_timeout):
                print("Complete Sentence:", buffer.strip())
                gpt_response = get_gpt_response(buffer.strip())
                print(f"LLM response: ", gpt_response)
                send_gpt_response_as_audio(gpt_response, ws)
                # Here you can add your GPT response and audio sending logic
                buffer = ""
                last_update_time = current_time


def on_transcription_response(response, ws):
    global buffer, last_update_time


    if not response.results:
        return

    result = response.results[0]
    if not result.alternatives:
        return

    transcription = result.alternatives[0].transcript

    with buffer_lock:
        # Update the buffer with the new transcription
        if len(transcription) > len(buffer):
            buffer = transcription
            last_update_time = time.time()

        # Print the partial transcription
        print("Partial:", buffer)



def get_gpt_response(prompt):
    """Get response from GPT-4 using the v1/chat/completions endpoint."""
    response = openai.ChatCompletion.create(
        model="gpt-4o",  
        messages=[
            {"role": "system", "content": "You are a helpful assistant who uses simple words and something concise on output, and whatever language the user's uses respond in that language's scripture or writing."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=150  
    )
    return response['choices'][0]['message']['content'].strip()

def send_gpt_response_as_audio(text, ws):
    try:
        # Convert the GPT response to speech (TTS)
        tts = gTTS(text, lang='te')
        audio_fp = BytesIO()
        tts.write_to_fp(audio_fp)
        audio_fp.seek(0)

        # Convert the TTS audio to the required format for Twilio
        audio_segment = AudioSegment.from_mp3(audio_fp)

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
        time.sleep(0.05)
        
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


def convert_text_to_speech(text):
    print(f"Converting text to speech: {text}")
    try:
        tts = gTTS(text, lang='en')
        audio_fp = BytesIO()
        tts.write_to_fp(audio_fp)
        audio_fp.seek(0)
        audio_data = audio_fp.read()        
        with open("tts_output.mp3", "wb") as f:
            f.write(audio_data)
        print("TTS output saved locally as tts_output.mp3")
        
    except Exception as e:
        print(f"Error in TTS conversion: {e}")


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
    # bridge = SpeechClientBridge(streaming_config, on_transcription_response)
    bridge = SpeechClientBridge(streaming_config, lambda response: on_transcription_response(response, ws))
    t = threading.Thread(target=bridge.start)
    t.start()
    # time.sleep(1.5)  # Delay before processing the first chunk

    sentence_checker = threading.Thread(target=check_sentence_completion, args=(ws,), daemon=True)
    sentence_checker.start()

    while not ws.closed:
        message = ws.receive()
        if message is None:
            bridge.add_request(None)
            bridge.terminate()
            break

        data = json.loads(message)
        if data["event"] in ("connected"):
            print(f"Media WS: Connected event '{data['event']}': {message}")
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