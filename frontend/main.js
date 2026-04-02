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

let currentGeminiMessageDiv = null;
let currentUserMessageDiv = null;
let geminiStreamState = { accumulated: "", lastChunk: "" };
let userStreamState = { accumulated: "", lastChunk: "" };

const mediaHandler = new MediaHandler();

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
  }
}

function appendStreamingText(role, chunkText, messageDiv, streamState) {
  if (!chunkText) return messageDiv;

  if (!messageDiv) {
    streamState.accumulated = chunkText;
    streamState.lastChunk = chunkText;
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
    micBtn.textContent = "Start Mic";
  } else {
    try {
      await mediaHandler.startAudio((data) => {
        if (geminiClient.isConnected()) {
          geminiClient.send(data);
        }
      });
      micBtn.textContent = "Stop Mic";
    } catch (e) {
      alert("Could not start audio capture");
    }
  }
};

cameraBtn.onclick = async () => {
  if (cameraBtn.textContent === "Stop Camera") {
    mediaHandler.stopVideo(videoPreview);
    cameraBtn.textContent = "Start Camera";
    screenBtn.textContent = "Share Screen";
    videoPlaceholder.classList.remove("hidden");
  } else {
    // If another stream is active (e.g. Screen), stop it first
    if (mediaHandler.videoStream) {
      mediaHandler.stopVideo(videoPreview);
      screenBtn.textContent = "Share Screen";
    }

    try {
      await mediaHandler.startVideo(videoPreview, (base64Data) => {
        if (geminiClient.isConnected()) {
          geminiClient.sendImage(base64Data);
        }
      });
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
    screenBtn.textContent = "Share Screen";
    cameraBtn.textContent = "Start Camera";
    videoPlaceholder.classList.remove("hidden");
  } else {
    // If another stream is active (e.g. Camera), stop it first
    if (mediaHandler.videoStream) {
      mediaHandler.stopVideo(videoPreview);
      cameraBtn.textContent = "Start Camera";
    }

    try {
      await mediaHandler.startScreen(
        videoPreview,
        (base64Data) => {
          if (geminiClient.isConnected()) {
            geminiClient.sendImage(base64Data);
          }
        },
        () => {
          // onEnded callback (e.g. user stopped sharing from browser)
          screenBtn.textContent = "Share Screen";
          videoPlaceholder.classList.remove("hidden");
        }
      );
      screenBtn.textContent = "Stop Sharing";
      cameraBtn.textContent = "Start Camera";
      videoPlaceholder.classList.add("hidden");
    } catch (e) {
      alert("Could not share screen");
    }
  }
};

sendBtn.onclick = sendText;
textInput.onkeypress = (e) => {
  if (e.key === "Enter") sendText();
};

function sendText() {
  const text = textInput.value;
  if (text && geminiClient.isConnected()) {
    geminiClient.sendText(text);
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
