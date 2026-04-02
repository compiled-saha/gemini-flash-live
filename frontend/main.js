// --- Main Application Logic ---

const statusDiv = document.getElementById("status");
const authSection = document.getElementById("auth-section");
const appSection = document.getElementById("app-section");
const sessionEndSection = document.getElementById("session-end-section");
const restartBtn = document.getElementById("restartBtn");
const micBtn = document.getElementById("micBtn");
const cameraBtn = document.getElementById("cameraBtn");
const screenBtn = document.getElementById("screenBtn");
const disconnectBtn = document.getElementById("disconnectBtn");
const textInput = document.getElementById("textInput");
const sendBtn = document.getElementById("sendBtn");
const videoPreview = document.getElementById("video-preview");
const videoPlaceholder = document.getElementById("video-placeholder");
const connectBtn = document.getElementById("connectBtn");
const chatLog = document.getElementById("chat-log");
const toolLog = document.getElementById("tool-log");
const languageSelect = document.getElementById("languageSelect");
const activeLanguageBadge = document.getElementById("activeLanguageBadge");
const stepProgressRow = document.getElementById("step-progress-row");
const stepProgressLabel = document.getElementById("step-progress-label");
const stepProgressFill = document.getElementById("step-progress-fill");
const stepIssueBadge = document.getElementById("step-issue-badge");
const audioInputBadge = document.getElementById("audio-input-badge");
const visualInputBadge = document.getElementById("visual-input-badge");
const audioOutputBadge = document.getElementById("audio-output-badge");
const mediaFlowCaption = document.getElementById("media-flow-caption");
const browserHint = document.getElementById("browser-hint");

let currentGeminiMessageDiv = null;
let currentUserMessageDiv = null;
let geminiStreamState = { accumulated: "", lastChunk: "" };
let userStreamState = { accumulated: "", lastChunk: "" };
let audioOutputTimer = null;
let visualCaptionMessageDiv = null;
let latestUserInputText = "";
let visualCaptureCardDiv = null;
let visualCaptureLastUpdateAt = 0;

const mediaState = {
  audioInput: false,
  visualInput: "off",
  audioOutput: false,
  lastVisualFrameAt: null,
  lastAudioPlaybackAt: null,
};

const mediaHandler = new MediaHandler();

function detectBrowserCapabilities() {
  const hasMediaDevices = Boolean(navigator.mediaDevices);
  const hasGetUserMedia = Boolean(
    navigator.mediaDevices && navigator.mediaDevices.getUserMedia
  );
  const hasDisplayMedia = Boolean(
    navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia
  );
  const hasAudioContext = Boolean(window.AudioContext || window.webkitAudioContext);
  const hasAudioWorklet = Boolean(window.AudioWorkletNode);

  return {
    hasMediaDevices,
    hasGetUserMedia,
    hasDisplayMedia,
    hasAudioContext,
    hasAudioWorklet,
  };
}

function applyBrowserCompatibilityUI() {
  const caps = detectBrowserCapabilities();
  const warnings = [];

  micBtn.disabled = !(caps.hasGetUserMedia && caps.hasAudioContext && caps.hasAudioWorklet);
  cameraBtn.disabled = !caps.hasGetUserMedia;
  screenBtn.disabled = !caps.hasDisplayMedia;

  if (!caps.hasMediaDevices) {
    warnings.push("This browser does not support media devices for mic/camera.");
  }
  if (!caps.hasDisplayMedia) {
    warnings.push("Screen sharing is not available in this browser.");
  }
  if (!caps.hasAudioWorklet) {
    warnings.push("Live microphone streaming requires a modern Chrome/Edge browser.");
  }

  if (browserHint) {
    if (warnings.length) {
      browserHint.classList.add("warning");
      browserHint.textContent = `Compatibility warning: ${warnings.join(" ")}`;
    } else {
      browserHint.classList.remove("warning");
      browserHint.textContent =
        "Browser check complete: mic, camera, and screen sharing are supported in this browser.";
    }
  }
}

function formatClockTime(value) {
  if (!value) return "";
  return new Date(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function setBadgeState(element, text, stateClass) {
  if (!element) return;
  element.textContent = text;
  element.className = `media-caption-badge ${stateClass}`;
}

function buildMediaFlowText() {
  const parts = [];

  if (mediaState.audioInput) {
    parts.push("mic audio is streaming in");
  }

  if (mediaState.visualInput === "camera") {
    parts.push("camera image frames are being sent");
  } else if (mediaState.visualInput === "screen") {
    parts.push("screen image frames are being sent");
  }

  if (mediaState.audioOutput) {
    parts.push("assistant audio is playing back");
  }

  if (parts.length === 0) {
    return "Flow: connect and start mic, camera, or screen share to see live media activity.";
  }

  const meta = [];
  if (mediaState.lastVisualFrameAt && mediaState.visualInput !== "off") {
    meta.push(`last image ${formatClockTime(mediaState.lastVisualFrameAt)}`);
  }
  if (mediaState.lastAudioPlaybackAt) {
    meta.push(`last audio ${formatClockTime(mediaState.lastAudioPlaybackAt)}`);
  }

  const suffix = meta.length ? ` (${meta.join(" | ")})` : "";
  return `Flow: ${parts.join(", ")}.${suffix}`;
}

function updateMediaCaptionPanel() {
  setBadgeState(
    audioInputBadge,
    mediaState.audioInput ? "Live" : "Off",
    mediaState.audioInput ? "active" : "idle"
  );

  if (mediaState.visualInput === "camera") {
    setBadgeState(visualInputBadge, "Camera", "live");
  } else if (mediaState.visualInput === "screen") {
    setBadgeState(visualInputBadge, "Screen", "live");
  } else {
    setBadgeState(visualInputBadge, "Off", "idle");
  }

  setBadgeState(
    audioOutputBadge,
    mediaState.audioOutput ? "Playing" : "Idle",
    mediaState.audioOutput ? "active" : "idle"
  );

  if (mediaFlowCaption) {
    mediaFlowCaption.textContent = buildMediaFlowText();
  }
}

function updateVisualCaptionInChat() {
  visualCaptionMessageDiv = null;
}

function getOrCreateVisualCaptureCard() {
  if (visualCaptureCardDiv && chatLog.contains(visualCaptureCardDiv)) {
    return visualCaptureCardDiv;
  }

  const card = document.createElement("div");
  card.className = "message system visual-capture-card";

  const title = document.createElement("div");
  title.className = "visual-capture-title";
  title.textContent = "Visual Capture";

  const image = document.createElement("img");
  image.className = "visual-capture-image";
  image.alt = "Latest captured frame";

  const source = document.createElement("div");
  source.className = "visual-capture-source";

  const input = document.createElement("div");
  input.className = "visual-capture-input";

  card.appendChild(title);
  card.appendChild(image);
  card.appendChild(source);
  card.appendChild(input);

  chatLog.appendChild(card);
  chatLog.scrollTop = chatLog.scrollHeight;
  visualCaptureCardDiv = card;
  return card;
}

function updateVisualCaptureInputText() {
  if (!visualCaptureCardDiv || !chatLog.contains(visualCaptureCardDiv)) return;
  const input = visualCaptureCardDiv.querySelector(".visual-capture-input");
  if (!input) return;
  input.textContent = latestUserInputText
    ? `Linked user input: ${latestUserInputText}`
    : "Linked user input: (waiting for speech/text)";
}

function updateVisualCaptureCard(base64Data, sourceType) {
  if (!chatLog) return;
  const now = Date.now();
  if (now - visualCaptureLastUpdateAt < 1200) return;
  visualCaptureLastUpdateAt = now;

  const card = getOrCreateVisualCaptureCard();
  const image = card.querySelector(".visual-capture-image");
  const source = card.querySelector(".visual-capture-source");

  if (image) {
    image.src = `data:image/jpeg;base64,${base64Data}`;
  }

  if (source) {
    const sourceName = sourceType === "screen" ? "Screen Share" : "Camera";
    source.textContent = `${sourceName} | ${new Date().toLocaleTimeString()}`;
  }

  updateVisualCaptureInputText();
}

function appendSystemCaption(text) {
  if (!text) return;
  appendMessage("system", text);
}

function setVisualMode(mode) {
  mediaState.visualInput = mode;
  if (mode === "off") {
    mediaState.lastVisualFrameAt = null;
    visualCaptureCardDiv = null;
  }
  updateMediaCaptionPanel();
}

function markVisualFrame(mode) {
  mediaState.visualInput = mode;
  mediaState.lastVisualFrameAt = Date.now();
  updateMediaCaptionPanel();
}

function markAssistantAudioPlayback() {
  mediaState.audioOutput = true;
  mediaState.lastAudioPlaybackAt = Date.now();
  updateMediaCaptionPanel();

  if (audioOutputTimer) {
    clearTimeout(audioOutputTimer);
  }

  audioOutputTimer = setTimeout(() => {
    mediaState.audioOutput = false;
    updateMediaCaptionPanel();
  }, 2200);
}

function resetMediaState() {
  mediaState.audioInput = false;
  mediaState.visualInput = "off";
  mediaState.audioOutput = false;
  mediaState.lastVisualFrameAt = null;
  mediaState.lastAudioPlaybackAt = null;
  latestUserInputText = "";
  visualCaptionMessageDiv = null;
  visualCaptureCardDiv = null;
  visualCaptureLastUpdateAt = 0;
  if (audioOutputTimer) {
    clearTimeout(audioOutputTimer);
    audioOutputTimer = null;
  }
  updateMediaCaptionPanel();
}

function getSelectedLanguageName() {
  const value = (languageSelect?.value || "english").toLowerCase();
  if (value === "hindi") return "Hindi";
  if (value === "german") return "German";
  if (value === "spanish") return "Spanish";
  return "English";
}

function updateLanguageBadge() {
  if (activeLanguageBadge) {
    activeLanguageBadge.textContent = getSelectedLanguageName();
  }
}

function sendLanguagePreference() {
  const selectedLanguage = getSelectedLanguageName();
  geminiClient.sendText(
    `LANGUAGE_PREF: ${selectedLanguage}. Respond only in ${selectedLanguage} until language is changed again. This is a control update; do not send a standalone reply for this message.`
  );
}

const geminiClient = new GeminiClient({
  onOpen: () => {
    statusDiv.textContent = "Connected";
    statusDiv.className = "status connected";
    authSection.classList.add("hidden");
    appSection.classList.remove("hidden");

    // Use a single startup turn to avoid duplicate model responses.
    const selectedLanguage = getSelectedLanguageName();
    geminiClient.sendText(
      `LANGUAGE_PREF: ${selectedLanguage}. Respond only in ${selectedLanguage} until language is changed again. Start now. Greet the caller and ask for employee ID.`
    );
  },
  onMessage: (event) => {
    if (typeof event.data === "string") {
      try {
        const msg = JSON.parse(event.data);
        handleJsonMessage(msg);
      } catch (e) {
        console.error("Parse error:", e);
      }
    } else {
      markAssistantAudioPlayback();
      mediaHandler.playAudio(event.data);
    }
  },
  onClose: (e) => {
    console.log("WS Closed:", e);
    statusDiv.textContent = "Disconnected";
    statusDiv.className = "status disconnected";
    showSessionEnd();
  },
  onError: (e) => {
    console.error("WS Error:", e);
    statusDiv.textContent = "Connection Error";
    statusDiv.className = "status error";
  },
});

function handleJsonMessage(msg) {
  if (msg.type === "interrupted") {
    mediaHandler.stopAudioPlayback();
    currentGeminiMessageDiv = null;
    currentUserMessageDiv = null;
    geminiStreamState = { accumulated: "", lastChunk: "" };
    userStreamState = { accumulated: "", lastChunk: "" };
  } else if (msg.type === "turn_complete") {
    currentGeminiMessageDiv = null;
    currentUserMessageDiv = null;
    geminiStreamState = { accumulated: "", lastChunk: "" };
    userStreamState = { accumulated: "", lastChunk: "" };
  } else if (msg.type === "user") {
    currentUserMessageDiv = appendStreamingText(
      "user",
      msg.text,
      currentUserMessageDiv,
      userStreamState
    );
  } else if (msg.type === "gemini") {
    currentGeminiMessageDiv = appendStreamingText(
      "gemini",
      msg.text,
      currentGeminiMessageDiv,
      geminiStreamState
    );
  } else if (msg.type === "tool_call") {
    appendToolEvent(msg);
  } else if (msg.type === "error") {
    const message = msg.message || "The live session ended unexpectedly.";
    appendMessage("gemini", message);
    statusDiv.textContent = msg.code === "resource_exhausted" ? "Quota Reached" : "Session Error";
    statusDiv.className = "status error";
  }
}

function appendStreamingText(role, chunkText, messageDiv, streamState) {
  if (!chunkText) return messageDiv;

  if (!messageDiv) {
    streamState.accumulated = chunkText;
    streamState.lastChunk = chunkText;
    if (role === "user") {
      latestUserInputText = chunkText;
      updateVisualCaptureInputText();
    }
    return appendMessage(role, chunkText);
  }

  // Handle cumulative transcripts: model sends full text-so-far.
  if (chunkText.startsWith(streamState.accumulated)) {
    const delta = chunkText.slice(streamState.accumulated.length);
    if (delta) {
      messageDiv.textContent += delta;
      chatLog.scrollTop = chatLog.scrollHeight;
    }
    streamState.accumulated = chunkText;
    streamState.lastChunk = chunkText;
    if (role === "user") {
      latestUserInputText = chunkText;
      updateVisualCaptureInputText();
    }
    return messageDiv;
  }

  // Ignore exact repeated chunks.
  if (chunkText === streamState.lastChunk || streamState.accumulated.endsWith(chunkText)) {
    return messageDiv;
  }

  // Fallback for true delta chunks.
  messageDiv.textContent += chunkText;
  chatLog.scrollTop = chatLog.scrollHeight;
  streamState.accumulated += chunkText;
  streamState.lastChunk = chunkText;
  if (role === "user") {
    latestUserInputText = streamState.accumulated;
    updateVisualCaptureInputText();
  }
  return messageDiv;
}

function appendMessage(type, text) {
  const msgDiv = document.createElement("div");
  msgDiv.className = `message ${type}`;
  msgDiv.textContent = text;
  chatLog.appendChild(msgDiv);
  chatLog.scrollTop = chatLog.scrollHeight;
  return msgDiv;
}

function appendToolEvent(msg) {
  if (!toolLog) return;
  const eventDiv = document.createElement("div");
  eventDiv.className = "tool-event";
  const result = msg.result || {};
  const isBlocked = Boolean(result.blocked);
  if (isBlocked) {
    eventDiv.classList.add("tool-event-warning");
  }

  // Update step progress bar whenever a step navigation result arrives
  updateStepProgress(result);

  const title = document.createElement("div");
  title.className = "tool-event-title";
  let titleText = `Tool: ${msg.name}`;
  if (typeof result.attempts_used === "number") {
    titleText += ` | Attempts: ${result.attempts_used}`;
    if (typeof result.attempts_remaining === "number") {
      titleText += ` | Remaining: ${result.attempts_remaining}`;
    }
  }
  if (isBlocked) {
    titleText += " | Escalated";
  }
  titleText += ` | ${new Date().toLocaleTimeString()}`;
  title.textContent = titleText;

  const body = document.createElement("div");
  body.className = "tool-event-body";
  body.appendChild(renderStructuredData(result));

  eventDiv.appendChild(title);
  eventDiv.appendChild(body);
  toolLog.appendChild(eventDiv);
  toolLog.scrollTop = toolLog.scrollHeight;
}

function renderStructuredData(value) {
  if (value === null || value === undefined) {
    const span = document.createElement("span");
    span.className = "tool-value";
    span.textContent = String(value);
    return span;
  }

  if (Array.isArray(value)) {
    const list = document.createElement("ul");
    list.className = "tool-list";
    value.forEach((item) => {
      const li = document.createElement("li");
      li.appendChild(renderStructuredData(item));
      list.appendChild(li);
    });
    return list;
  }

  if (typeof value === "object") {
    const wrapper = document.createElement("div");
    wrapper.className = "tool-kv-grid";
    Object.entries(value).forEach(([key, val]) => {
      const row = document.createElement("div");
      row.className = "tool-kv-row";

      const keyEl = document.createElement("span");
      keyEl.className = "tool-key";
      keyEl.textContent = key;

      const valEl = document.createElement("div");
      valEl.className = "tool-value";
      valEl.appendChild(renderStructuredData(val));

      row.appendChild(keyEl);
      row.appendChild(valEl);
      wrapper.appendChild(row);
    });
    return wrapper;
  }

  const span = document.createElement("span");
  span.className = "tool-value";
  span.textContent = String(value);
  return span;
}

// Step progress bar updater
function updateStepProgress(result) {
  if (!stepProgressRow) return;
  // Accept step data directly or nested inside step_state
  const step = result.step_number || (result.step_state && result.step_state.step_number);
  const total = result.total_steps || (result.step_state && result.step_state.total_steps);
  const issue = result.issue_type || (result.step_state && result.step_state.issue_type);

  if (step && total && issue) {
    stepProgressRow.style.display = "flex";
    stepProgressLabel.textContent = `Step ${step} of ${total}`;
    stepProgressFill.style.width = `${Math.round((step / total) * 100)}%`;
    stepIssueBadge.textContent = issue;
  }

  // Hide progress bar if issue was fully resolved
  if (result.outcome === "resolved") {
    stepProgressRow.style.display = "none";
  }
}

// Connect Button Handler
connectBtn.onclick = async () => {
  statusDiv.textContent = "Connecting...";
  connectBtn.disabled = true;

  try {
    // Initialize audio context on user gesture
    await mediaHandler.initializeAudio();

    geminiClient.connect();
  } catch (error) {
    console.error("Connection error:", error);
    statusDiv.textContent = "Connection Failed: " + error.message;
    statusDiv.className = "status error";
    connectBtn.disabled = false;
  }
};

// UI Controls
disconnectBtn.onclick = () => {
  geminiClient.disconnect();
};

micBtn.onclick = async () => {
  if (mediaHandler.isRecording) {
    mediaHandler.stopAudio();
    mediaState.audioInput = false;
    updateMediaCaptionPanel();
    appendSystemCaption("Mic stopped. Audio input is no longer being sent.");
    micBtn.textContent = "Start Mic";
  } else {
    try {
      await mediaHandler.startAudio((data) => {
        if (geminiClient.isConnected()) {
          geminiClient.send(data);
        }
      });
      mediaState.audioInput = true;
      updateMediaCaptionPanel();
      appendSystemCaption("Mic started. Your audio is now streaming to the assistant.");
      micBtn.textContent = "Stop Mic";
    } catch (e) {
      alert("Could not start audio capture");
    }
  }
};

cameraBtn.onclick = async () => {
  if (cameraBtn.textContent === "Stop Camera") {
    mediaHandler.stopVideo(videoPreview);
    setVisualMode("off");
    appendSystemCaption("Camera stopped. No image frames are being sent.");
    cameraBtn.textContent = "Start Camera";
    screenBtn.textContent = "Share Screen";
    videoPlaceholder.classList.remove("hidden");
  } else {
    // If another stream is active (e.g. Screen), stop it first
    if (mediaHandler.videoStream) {
      mediaHandler.stopVideo(videoPreview);
      setVisualMode("off");
      screenBtn.textContent = "Share Screen";
    }

    try {
      await mediaHandler.startVideo(videoPreview, (base64Data) => {
        if (geminiClient.isConnected()) {
          markVisualFrame("camera");
          updateVisualCaptureCard(base64Data, "camera");
          geminiClient.sendImage(base64Data);
        }
      });
      setVisualMode("camera");
      appendSystemCaption("Camera started. Image frames from the camera are now being sent.");
      cameraBtn.textContent = "Stop Camera";
      screenBtn.textContent = "Share Screen";
      videoPlaceholder.classList.add("hidden");
    } catch (e) {
      alert("Could not access camera");
    }
  }
};

screenBtn.onclick = async () => {
  if (screenBtn.textContent === "Stop Sharing") {
    mediaHandler.stopVideo(videoPreview);
    setVisualMode("off");
    appendSystemCaption("Screen sharing stopped. No screen image frames are being sent.");
    screenBtn.textContent = "Share Screen";
    cameraBtn.textContent = "Start Camera";
    videoPlaceholder.classList.remove("hidden");
  } else {
    // If another stream is active (e.g. Camera), stop it first
    if (mediaHandler.videoStream) {
      mediaHandler.stopVideo(videoPreview);
      setVisualMode("off");
      cameraBtn.textContent = "Start Camera";
    }

    try {
      await mediaHandler.startScreen(
        videoPreview,
        (base64Data) => {
          if (geminiClient.isConnected()) {
            markVisualFrame("screen");
            updateVisualCaptureCard(base64Data, "screen");
            geminiClient.sendImage(base64Data);
          }
        },
        () => {
          // onEnded callback (e.g. user stopped sharing from browser)
          setVisualMode("off");
          appendSystemCaption("Screen sharing ended from the browser. Visual input is now off.");
          screenBtn.textContent = "Share Screen";
          videoPlaceholder.classList.remove("hidden");
        }
      );
      setVisualMode("screen");
      appendSystemCaption("Screen sharing started. Screen image frames are now being sent.");
      screenBtn.textContent = "Stop Sharing";
      cameraBtn.textContent = "Start Camera";
      videoPlaceholder.classList.add("hidden");
    } catch (e) {
      alert("Could not share screen");
    }
  }
};

sendBtn.onclick = sendText;
textInput.onkeydown = (e) => {
  if (e.key === "Enter") sendText();
};

function sendText() {
  const text = textInput.value;
  if (text && geminiClient.isConnected()) {
    geminiClient.sendText(text);
    latestUserInputText = text;
    updateVisualCaptureInputText();
    appendMessage("user", text);
    textInput.value = "";
  }
}

function resetUI() {
  authSection.classList.remove("hidden");
  appSection.classList.add("hidden");
  sessionEndSection.classList.add("hidden");

  mediaHandler.stopAudio();
  mediaHandler.stopVideo(videoPreview);
  resetMediaState();
  videoPlaceholder.classList.remove("hidden");

  micBtn.textContent = "Start Mic";
  cameraBtn.textContent = "Start Camera";
  screenBtn.textContent = "Share Screen";
  chatLog.innerHTML = "";
  if (toolLog) {
    toolLog.innerHTML = "";
  }
  if (stepProgressRow) {
    stepProgressRow.style.display = "none";
  }
  connectBtn.disabled = false;
}

function showSessionEnd() {
  appSection.classList.add("hidden");
  sessionEndSection.classList.remove("hidden");
  mediaHandler.stopAudio();
  mediaHandler.stopVideo(videoPreview);
  resetMediaState();
}

restartBtn.onclick = () => {
  resetUI();
};

updateLanguageBadge();

if (languageSelect) {
  languageSelect.addEventListener("change", () => {
    updateLanguageBadge();
    if (geminiClient.isConnected()) {
      sendLanguagePreference();
    }
  });
}

// Chip button quick-action handlers
document.querySelectorAll(".chip[data-cmd]").forEach((chip) => {
  chip.addEventListener("click", () => {
    if (!geminiClient.isConnected()) return;
    const cmd = chip.dataset.cmd;
    const text = cmd === "escalate" ? "I need to escalate this issue to a human agent." : cmd;
    geminiClient.sendText(text);
    appendMessage("user", text);
  });
});

updateMediaCaptionPanel();
applyBrowserCompatibilityUI();
