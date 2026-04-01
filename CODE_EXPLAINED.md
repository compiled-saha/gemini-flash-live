# Gemini Live API — Code Explanation

A full-stack real-time voice/video AI assistant using Google's Gemini Live API.  
The **Python backend** bridges the browser to Gemini via WebSocket, and the **JavaScript frontend** captures media and renders responses.

---

## Architecture Overview

```
Browser (Frontend)
  │  WebSocket (/ws)
  ▼
FastAPI Backend (main.py)
  │  google-genai SDK
  ▼
Gemini Live API
```

---

## Backend

### `requirements.txt`

| Package | Purpose |
|---|---|
| `fastapi` | Web framework & WebSocket server |
| `uvicorn` | ASGI server to run FastAPI |
| `google-genai` | Official Google Generative AI SDK |
| `websockets` | WebSocket support |
| `python-dotenv` | Load `.env` config file |
| `python-multipart` | Form data parsing |

---

### `main.py` — FastAPI Server

**Entry point** for the backend. Handles HTTP and WebSocket connections.

#### Key responsibilities

1. **Serve the frontend** — static files in `frontend/` are mounted at `/static`, and `GET /` returns `index.html`.

2. **WebSocket endpoint `/ws`** — the browser connects here for the entire session lifetime.

```python
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
```

#### Data flow inside the WebSocket handler

```
Browser → WebSocket → websocket_endpoint
                          │
                          ├── bytes (raw PCM audio)  → audio_input_queue
                          ├── JSON {type:"image"}    → video_input_queue (decoded from base64)
                          └── plain text             → text_input_queue
```

Three `asyncio.Queue` objects decouple receiving from the browser and sending to Gemini.

```python
audio_input_queue = asyncio.Queue()
video_input_queue = asyncio.Queue()
text_input_queue  = asyncio.Queue()
```

**`receive_from_client()`** — runs as a background task, continuously reads messages from the browser and routes them to the correct queue.

**`audio_output_callback(data)`** — called by `GeminiLive` when Gemini produces audio; forwards raw PCM bytes directly to the browser via `websocket.send_bytes()`.

**`run_session()`** — iterates over events yielded by `GeminiLive.start_session()` and forwards JSON events (transcriptions, tool calls, etc.) to the browser via `websocket.send_json()`.

#### Configuration (from `.env`)

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | — | Your Google AI Studio API key |
| `MODEL` | `gemini-3.1-flash-live-preview` | Gemini model to use |
| `PORT` | `8000` | Port the server listens on |

---

### `gemini_live.py` — GeminiLive Class

Core class that manages a **live streaming session** with the Gemini API.

#### Constructor

```python
GeminiLive(api_key, model, input_sample_rate, tools=None, tool_mapping=None)
```

| Parameter | Description |
|---|---|
| `api_key` | Gemini API key |
| `model` | Model ID string |
| `input_sample_rate` | Audio sample rate (16 000 Hz) |
| `tools` | List of tool definitions for function calling |
| `tool_mapping` | Dict mapping tool name → Python function |

#### `start_session()` — async generator

```python
async def start_session(
    audio_input_queue, video_input_queue, text_input_queue,
    audio_output_callback, audio_interrupt_callback=None
)
```

Opens a `LiveConnectConfig` with these settings:

| Setting | Value | Effect |
|---|---|---|
| `response_modalities` | `AUDIO` | Gemini responds with audio |
| `voice_name` | `"Puck"` | Built-in voice |
| `system_instruction` | Custom prompt | Tells Gemini to be a helpful assistant with an Irish accent that can see the camera/screen |
| `input_audio_transcription` | Enabled | Gemini transcribes what the user says |
| `output_audio_transcription` | Enabled | Gemini transcribes what it says |
| `turn_coverage` | `TURN_INCLUDES_ONLY_ACTIVITY` | Only active speech is counted per turn |

#### Four concurrent async tasks

| Task | What it does |
|---|---|
| `send_audio()` | Reads PCM chunks from `audio_input_queue`, sends as `audio/pcm` blobs |
| `send_video()` | Reads JPEG frames from `video_input_queue`, sends as `image/jpeg` blobs |
| `send_text()` | Reads strings from `text_input_queue`, sends as text |
| `receive_loop()` | Reads all responses from Gemini and puts events onto `event_queue` |

#### Event types yielded to the caller

| Event | Description |
|---|---|
| `{"type": "user", "text": "..."}` | User speech transcription chunk |
| `{"type": "gemini", "text": "..."}` | Gemini speech transcription chunk |
| `{"type": "turn_complete"}` | Gemini finished its turn |
| `{"type": "interrupted"}` | Gemini was interrupted (e.g. user spoke) |
| `{"type": "tool_call", "name", "args", "result"}` | A function tool was called and returned a result |
| `{"type": "error", "error": "..."}` | An error occurred |
| `None` | Session ended — stop iterating |

#### Function / Tool calling

If Gemini decides to call a tool, `receive_loop` looks up the function in `self.tool_mapping`, calls it (supports both sync and async functions), and sends the result back to Gemini with `session.send_tool_response()`.

---

## Frontend

### `index.html` — UI Shell

Single-page layout with three sections:

| Section | ID | Shown when |
|---|---|---|
| Auth / Connect | `auth-section` | Before connecting |
| Live App | `app-section` | During a session |
| Session Ended | `session-end-section` | After disconnect |

UI elements: video preview, mic/camera/screen buttons, disconnect button, chat log, text input.

---

### `gemini-client.js` — `GeminiClient` class

Thin wrapper around the browser `WebSocket` API.

| Method | What it does |
|---|---|
| `connect()` | Opens `ws://` or `wss://` to `/ws` |
| `send(data)` | Sends raw data (bytes or string) |
| `sendText(text)` | Sends `{"text": "..."}` as JSON string |
| `sendImage(base64, mimeType)` | Sends `{"type":"image","data":"..."}` as JSON |
| `disconnect()` | Closes the socket |
| `isConnected()` | Returns `true` if socket is `OPEN` |

Callbacks configured at construction: `onOpen`, `onMessage`, `onClose`, `onError`.

---

### `media-handler.js` — `MediaHandler` class

Manages microphone, camera, screen capture, and audio playback using Web APIs.

#### Audio capture pipeline

```
Microphone (getUserMedia)
  → MediaStreamSource
  → AudioWorkletNode (pcm-processor)
  → downsample to 16 kHz
  → convertFloat32ToInt16
  → onAudioData callback (→ WebSocket as binary)
```

| Method | Description |
|---|---|
| `initializeAudio()` | Creates `AudioContext`, loads `pcm-processor` worklet |
| `startAudio(onAudioData)` | Starts mic capture, calls `onAudioData` with PCM `ArrayBuffer` |
| `stopAudio()` | Stops mic, cleans up worklet |

#### Video capture pipeline

```
Camera / Screen (getUserMedia / getDisplayMedia)
  → <video> element (preview)
  → setInterval 1 FPS
  → drawImage on Canvas (640×480)
  → toDataURL("image/jpeg", 0.7) → base64
  → onFrame callback (→ WebSocket as JSON)
```

| Method | Description |
|---|---|
| `startVideo(videoEl, onFrame)` | Starts camera at 1 FPS |
| `startScreen(videoEl, onFrame, onEnded)` | Starts screen capture at 1 FPS |
| `stopVideo(videoEl)` | Stops stream and frame interval |
| `captureFrame(videoEl, onFrame)` | Single JPEG capture |

#### Audio playback pipeline

```
WebSocket binary message (Int16 PCM @ 24 kHz)
  → Int16Array → Float32Array (÷ 32768)
  → AudioBuffer (1 ch, 24 kHz)
  → BufferSource → AudioContext.destination
  (scheduled with nextStartTime for gapless playback)
```

| Method | Description |
|---|---|
| `playAudio(arrayBuffer)` | Decodes and schedules PCM for playback |
| `stopAudioPlayback()` | Cancels all scheduled audio (on interrupt) |

---

### `pcm-processor.js` — `PCMProcessor` AudioWorklet

Runs in the browser's audio rendering thread. Accumulates raw `Float32` audio samples into 4096-sample chunks and posts them to the main thread.

```
AudioWorkletProcessor.process()
  → buffer fills to 4096 samples
  → port.postMessage(buffer)   ← picked up by MediaHandler
```

---

### `main.js` — Application Logic

Wires all the above together:

1. **Connect button** → `mediaHandler.initializeAudio()` then `geminiClient.connect()`.
2. On `onOpen` → sends a hidden system prompt instructing Gemini to introduce itself.
3. On `onMessage`:
   - **Binary** → `mediaHandler.playAudio()` (Gemini's voice).
   - **JSON string** → `handleJsonMessage()`.
4. **`handleJsonMessage()`** updates the chat log:
   - `"user"` / `"gemini"` transcription chunks are appended to the current message div (streaming).
   - `"turn_complete"` resets the current message divs.
   - `"interrupted"` stops audio playback and resets divs.
5. **Mic button** → toggle `mediaHandler.startAudio()` / `stopAudio()`.
6. **Camera / Screen buttons** — mutually exclusive; toggle `startVideo()` / `startScreen()` / `stopVideo()`.
7. **Text input** → `geminiClient.sendText()` on Enter or Send button.
8. **Disconnect** → `geminiClient.disconnect()` → triggers `onClose` → `showSessionEnd()`.
9. **Restart button** → `resetUI()` which clears everything and shows the connect screen again.

---

## End-to-End Data Flow Summary

```
User speaks into mic
  → PCMProcessor (AudioWorklet, 4096-sample chunks)
  → MediaHandler (downsample 48kHz→16kHz, Float32→Int16)
  → WebSocket (binary)
  → main.py: audio_input_queue
  → GeminiLive.send_audio(): Blob(audio/pcm;rate=16000)
  → Gemini Live API

Gemini generates audio response
  → GeminiLive.receive_loop(): part.inline_data.data
  → audio_output_callback → WebSocket (binary)
  → MediaHandler.playAudio() (Int16@24kHz → AudioContext)
  → User hears Gemini's voice

Gemini transcribes both sides
  → event_queue events (type:"user" / type:"gemini")
  → WebSocket JSON
  → handleJsonMessage() → chat log
```
