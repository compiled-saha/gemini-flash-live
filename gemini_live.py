import asyncio
import inspect
import logging
import re
import traceback
import uuid
from typing import Any

logger = logging.getLogger(__name__)
from google import genai
from google.genai import types

PASSWORD_PATH_STEPS = [
    "Confirm the account is not locked: check if you can still receive company emails or if you get an 'account locked' message.",
    "Try logging in via the company's self-service password reset portal (ask helpdesk for the URL if unknown).",
    "If self-service is unavailable, verify Caps Lock is OFF and re-enter your current password carefully.",
    "If you recently changed your password on another device, wait 2–3 minutes for the change to sync across systems, then try again.",
    "Clear your browser's saved credentials and cookies, then attempt login again.",
    "Try logging in from a different browser or a private/incognito window to rule out browser issues.",
    "If all attempts fail, contact IT Helpdesk to have your account unlocked or password manually reset.",
]

CITRIX_PATH_STEPS = [
    "Confirm your internet connection is active and stable — try opening any website to verify.",
    "Open Citrix Workspace and check that the StoreFront/server URL is correct; ask IT for the correct URL if unsure.",
    "Verify your username and password are correct — remember that Citrix uses your Active Directory (AD) credentials.",
    "Ensure Citrix Workspace app is installed and up to date; download the latest version from the official Citrix download page if needed.",
    "Clear Citrix Workspace cache: go to Advanced Preferences > Reset Workspace, then restart the application.",
    "Disable any VPN or firewall temporarily to check if they are blocking the Citrix connection.",
    "Try accessing your Citrix applications via a web browser instead (use the StoreFront URL directly).",
    "Restart your computer and attempt to reconnect to Citrix.",
    "If login still fails, contact IT Helpdesk and report any error code or message shown on screen.",
]

VPN_PATH_STEPS = [
    "Confirm your internet connection is working — open a browser and try any website before launching VPN.",
    "Check that you are using the correct VPN server address and profile as provided by IT.",
    "Verify your username and password — VPN typically uses your Active Directory (AD) credentials.",
    "If MFA (multi-factor authentication) is required, ensure your authenticator app or token is ready before connecting.",
    "Disconnect and reconnect the VPN client; if it does not respond, close it completely from the system tray and relaunch.",
    "Temporarily disable third-party antivirus or firewall to check if they are blocking the VPN connection.",
    "Update the VPN client to the latest version supported by your organization.",
    "Try connecting from a different network such as a mobile hotspot to rule out local network restrictions.",
    "If the issue persists, contact IT Helpdesk and provide the error code or message displayed.",
]

OUTLOOK_PATH_STEPS = [
    "Confirm your internet connection is active — emails cannot send or receive without network access.",
    "Check the bottom status bar of Outlook for a 'Disconnected' or 'Working Offline' status; click it to go online.",
    "Verify your Outlook password has not expired — if it has, update it and re-authenticate under File > Account Settings.",
    "Check the Outbox folder for any stuck emails; delete or move large or corrupted emails that may be blocking the send queue.",
    "Check your Junk or Spam folder for missing incoming emails and mark legitimate emails as Not Junk.",
    "Wait 5 minutes and try again — Exchange mail sync can sometimes be delayed.",
    "Restart Outlook completely (close from the taskbar, not just minimize) and re-open.",
    "Run Outlook in Safe Mode to check for add-in conflicts: press Win+R, type 'outlook.exe /safe', and press Enter.",
    "Repair your Outlook data file via File > Account Settings > Data Files > Repair.",
    "If the issue continues, contact IT Helpdesk — they can check mailbox quota, Exchange server status, or recreate your mail profile.",
]

HELPDESK_ESCALATION = "Please contact IT Helpdesk for manual assistance."
MAX_EMPLOYEE_ID_ATTEMPTS = 3
SUPPORTED_ISSUES = ["password", "citrix", "vpn", "outlook"]

ISSUE_STEPS_MAP = {
    "password": PASSWORD_PATH_STEPS,
    "citrix": CITRIX_PATH_STEPS,
    "vpn": VPN_PATH_STEPS,
    "outlook": OUTLOOK_PATH_STEPS,
}


def get_password_support_path():
    return {
        "issue_type": "password",
        "steps": PASSWORD_PATH_STEPS,
        "escalation": HELPDESK_ESCALATION,
    }


def get_citrix_support_path():
    return {
        "issue_type": "citrix",
        "steps": CITRIX_PATH_STEPS,
        "escalation": HELPDESK_ESCALATION,
    }


def get_vpn_support_path():
    return {
        "issue_type": "vpn",
        "steps": VPN_PATH_STEPS,
        "escalation": HELPDESK_ESCALATION,
    }


def get_outlook_support_path():
    return {
        "issue_type": "outlook",
        "steps": OUTLOOK_PATH_STEPS,
        "escalation": HELPDESK_ESCALATION,
    }


def get_all_support_paths_summary():
    return {
        "issue_types": ["password", "citrix", "vpn", "outlook"],
        "summary": {
            "password": "Check if account is locked, use self-service password reset portal, clear browser credentials, or contact IT to unlock.",
            "citrix": "Verify internet, check StoreFront URL and AD credentials, update or reset Citrix Workspace, try browser access.",
            "vpn": "Verify internet and VPN server address, confirm AD credentials and MFA, check firewall settings, update VPN client.",
            "outlook": "Check network and Offline mode, re-authenticate if password expired, clear Outbox, repair data file, or contact IT for mailbox issues.",
        },
        "escalation": HELPDESK_ESCALATION,
    }


def validate_employee_id(employee_id: str):
    cleaned = re.sub(r"\D", "", str(employee_id or ""))
    is_valid = len(cleaned) == 4
    return {
        "is_valid": is_valid,
        "employee_id": cleaned if is_valid else None,
        "message": "Employee ID verified." if is_valid else "Invalid employee ID. Please provide a 4-digit employee ID.",
    }


def classify_support_intent(user_text: str):
    text = str(user_text or "").strip().lower()
    if not text:
        return {
            "intent": "unknown",
            "confidence": 0.0,
            "reason": "Empty input.",
            "supported_intents": SUPPORTED_ISSUES + ["handoff", "unknown"],
        }

    handoff_keywords = ["human", "agent", "helpdesk", "representative", "escalate"]
    if any(k in text for k in handoff_keywords):
        return {
            "intent": "handoff",
            "confidence": 0.95,
            "reason": "User requested human/escalation support.",
            "supported_intents": SUPPORTED_ISSUES + ["handoff", "unknown"],
        }

    issue_keywords = {
        "password": ["password", "forgot", "reset", "login", "sign in"],
        "citrix": ["citrix", "workspace", "ica"],
        "vpn": ["vpn", "network tunnel", "secure connect"],
        "outlook": ["outlook", "email", "mail", "inbox", "outbox", "smtp", "exchange"],
    }

    scores = {issue: 0 for issue in issue_keywords}
    for issue, keywords in issue_keywords.items():
        scores[issue] = sum(1 for kw in keywords if kw in text)

    best_issue = max(scores, key=lambda issue: scores[issue])
    best_score = scores[best_issue]
    if best_score == 0:
        return {
            "intent": "unknown",
            "confidence": 0.2,
            "reason": "No strong keyword match.",
            "supported_intents": SUPPORTED_ISSUES + ["handoff", "unknown"],
        }

    confidence = min(0.99, 0.55 + (0.15 * best_score))
    return {
        "intent": best_issue,
        "confidence": round(confidence, 2),
        "reason": f"Matched {best_score} keyword(s) for {best_issue}.",
        "supported_intents": SUPPORTED_ISSUES + ["handoff", "unknown"],
    }


IT_SUPPORT_SYSTEM_INSTRUCTION = """
You are an IT Helpdesk voice bot for login support calls.

Primary behavior:
- Keep responses short, clear, and step-by-step.
- Ask only one question at a time.
- Wait for user confirmation before moving to the next step.
- Stay on this IT support use case only.

Conversation flow:
1) Start with: "Thank you for calling. Please say your employee ID."
2) Validate the employee ID by calling tool validate_employee_id.
3) If validation fails, ask for employee ID again and do not continue.
4) After successful validation, confirm with: "Thank you for providing employee ID <ID>. How can I help you today?"
3) Ask them to choose exactly one issue type:
    - Password issue
    - Citrix issue
    - VPN login issue
    - Outlook issue

Extra rules:
- Supported reply languages are: English, Hindi, German, Spanish.
- If you receive a control message in format "LANGUAGE_PREF: <Language>", switch reply language immediately.
- After language is set, reply only in that language until a new LANGUAGE_PREF message arrives.
- Do not send a standalone acknowledgement for LANGUAGE_PREF control messages.
- Do not provide troubleshooting steps until employee ID is validated.
- Allow at most 3 invalid employee ID attempts.
- On the 3rd invalid attempt, stop verification and instruct caller to contact IT Helpdesk.
- If the issue type is unclear, ask them to choose Password, Citrix, VPN, or Outlook.
- For free-form issue descriptions, call classify_support_intent first.
- After identifying an issue, call start_step_navigation to begin guided troubleshooting.
- For user commands like next, repeat, back, skip, start over, call navigate_support_step.
- Do not repeat the navigation command list in every response.
- Mention navigation commands only once when starting step navigation, or if user asks for help.
- After presenting each troubleshooting step, always ask: "Were you able to try that? Did it resolve your issue?"
- Wait for the user to confirm before moving to the next step.
- If user says yes / it worked / resolved: call confirm_step_outcome with outcome=resolved.
- If user says no / still broken / didn't work: call confirm_step_outcome with outcome=not_resolved, then call navigate_support_step with command=next.
- If confirm_step_outcome returns all_steps_exhausted=true, call get_smart_escalation_summary immediately.
- Always read back the ticket_id from get_smart_escalation_summary so the caller can note it down.
- If user asks for all options, call tool get_all_support_paths_summary and summarize briefly.
- When user selects Password issue, call tool get_password_support_path.
- When user selects Citrix issue, call tool get_citrix_support_path.
- When user selects VPN login issue, call tool get_vpn_support_path.
- When user selects Outlook issue, call tool get_outlook_support_path.
- After tool result, guide the user through steps one by one and use tool escalation message when needed.
- If user asks for escalation or issue remains unresolved, call get_smart_escalation_summary.
- Be polite and supportive, but do not add unrelated troubleshooting steps.
""".strip()

class GeminiLive:
    """
    Handles the interaction with the Gemini Live API.
    """
    def __init__(self, api_key, model, input_sample_rate, tools=None, tool_mapping=None):
        """
        Initializes the GeminiLive client.

        Args:
            api_key (str): The Gemini API Key.
            model (str): The model name to use.
            input_sample_rate (int): The sample rate for audio input.
            tools (list, optional): List of tools to enable. Defaults to None.
            tool_mapping (dict, optional): Mapping of tool names to functions. Defaults to None.
        """
        self.api_key = api_key
        self.model = model
        self.input_sample_rate = input_sample_rate
        self.client = genai.Client(api_key=api_key)
        self.validated_employee_id = None
        self.employee_id_attempts = 0
        self.current_issue_type = None
        self.current_step_index = 0
        self.visited_step_indexes = set()
        self.step_outcomes = {}  # {step_index: "resolved" | "not_resolved"}
        self.ticket_id = None
        self.active_language = "English"
        self.tools = tools or [
            {
                "function_declarations": [
                    {
                        "name": "validate_employee_id",
                        "description": "Validates a caller employee ID. Only 4-digit numeric IDs are accepted.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "employee_id": {
                                    "type": "string",
                                    "description": "Employee ID provided by caller."
                                }
                            },
                            "required": ["employee_id"],
                        },
                    },
                    {
                        "name": "classify_support_intent",
                        "description": "Classifies user issue intent into password, citrix, vpn, outlook, handoff, or unknown.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "user_text": {
                                    "type": "string",
                                    "description": "User's free-form issue description."
                                }
                            },
                            "required": ["user_text"],
                        },
                    },
                    {
                        "name": "start_step_navigation",
                        "description": "Starts stateful troubleshooting for a specific issue type and returns the first step.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "issue_type": {
                                    "type": "string",
                                    "description": "One of: password, citrix, vpn, outlook"
                                }
                            },
                            "required": ["issue_type"],
                        },
                    },
                    {
                        "name": "navigate_support_step",
                        "description": "Navigates current issue steps using commands: next, repeat, back, skip, start_over, status.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command": {
                                    "type": "string",
                                    "description": "Navigation command: next, repeat, back, skip, start_over, status"
                                }
                            },
                            "required": ["command"],
                        },
                    },
                    {
                        "name": "get_smart_escalation_summary",
                        "description": "Builds a concise escalation summary with issue context and attempted steps.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "reason": {
                                    "type": "string",
                                    "description": "Optional escalation reason from user or bot context."
                                }
                            },
                        },
                    },
                    {
                        "name": "confirm_step_outcome",
                        "description": "Records whether the current troubleshooting step resolved the issue. Call this after the user says yes or no to 'Did that work?'",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "outcome": {
                                    "type": "string",
                                    "description": "User outcome: 'resolved' if step worked, 'not_resolved' if it did not."
                                }
                            },
                            "required": ["outcome"],
                        },
                    },
                    {
                        "name": "get_password_support_path",
                        "description": "Returns the approved troubleshooting steps for password login issues.",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                        },
                    },
                    {
                        "name": "get_citrix_support_path",
                        "description": "Returns the approved troubleshooting steps for Citrix login issues.",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                        },
                    },
                    {
                        "name": "get_vpn_support_path",
                        "description": "Returns the approved troubleshooting steps for VPN login issues.",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                        },
                    },
                    {
                        "name": "get_outlook_support_path",
                        "description": "Returns the approved troubleshooting steps for Microsoft Outlook email issues such as emails not sending, not receiving, Outbox stuck, profile errors, or mail server configuration problems.",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                        },
                    },
                    {
                        "name": "get_all_support_paths_summary",
                        "description": "Returns a short summary for all support paths: password, Citrix, and VPN.",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                        },
                    },
                ]
            }
        ]
        self.tool_mapping = tool_mapping or {
            "validate_employee_id": self._validate_employee_id,
            "classify_support_intent": self._classify_support_intent,
            "start_step_navigation": self._start_step_navigation,
            "navigate_support_step": self._navigate_support_step,
            "confirm_step_outcome": self._confirm_step_outcome,
            "get_smart_escalation_summary": self._get_smart_escalation_summary,
            "get_password_support_path": self._get_password_support_path,
            "get_citrix_support_path": self._get_citrix_support_path,
            "get_vpn_support_path": self._get_vpn_support_path,
            "get_outlook_support_path": self._get_outlook_support_path,
            "get_all_support_paths_summary": self._get_all_support_paths_summary,
        }

    def _set_issue_state(self, issue_type: str):
        self.current_issue_type = issue_type
        self.current_step_index = 0
        self.visited_step_indexes = {0}

    def _get_step_state_payload(self, issue_type: str, step_index: int):
        steps = ISSUE_STEPS_MAP[issue_type]
        step_index = max(0, min(step_index, len(steps) - 1))
        self.visited_step_indexes.add(step_index)
        return {
            "issue_type": issue_type,
            "step_number": step_index + 1,
            "total_steps": len(steps),
            "step_text": steps[step_index],
            "commands": ["next", "repeat", "back", "skip", "start_over", "status"],
            "escalation": HELPDESK_ESCALATION,
        }

    def _validation_required_response(self):
        return {
            "error": "EMPLOYEE_ID_REQUIRED",
            "message": "Employee ID verification is required before troubleshooting.",
            "next_action": "Ask caller for a 4-digit employee ID and call validate_employee_id.",
        }

    def _classify_support_intent(self, user_text: str):
        if not self.validated_employee_id:
            return self._validation_required_response()
        result = classify_support_intent(user_text)
        result["employee_id"] = self.validated_employee_id
        return result

    def _start_step_navigation(self, issue_type: str):
        if not self.validated_employee_id:
            return self._validation_required_response()

        normalized = str(issue_type or "").strip().lower()
        if normalized not in ISSUE_STEPS_MAP:
            return {
                "error": "UNSUPPORTED_ISSUE_TYPE",
                "message": "Supported issue types are password, citrix, vpn, and outlook.",
                "supported_issue_types": list(ISSUE_STEPS_MAP.keys()),
            }

        self._set_issue_state(normalized)
        payload = self._get_step_state_payload(normalized, 0)
        payload["employee_id"] = self.validated_employee_id
        return payload

    def _confirm_step_outcome(self, outcome: str):
        if not self.validated_employee_id:
            return self._validation_required_response()
        if not self.current_issue_type or self.current_issue_type not in ISSUE_STEPS_MAP:
            return {
                "error": "NO_ACTIVE_ISSUE",
                "message": "No active issue navigation. Call start_step_navigation first.",
            }

        raw = str(outcome or "").strip().lower()
        resolved_words = {"yes", "resolved", "fixed", "done", "worked", "ok", "okay", "it worked", "that worked"}
        not_resolved_words = {"no", "not_resolved", "still", "nope", "did not", "didn't", "not working", "didn't work"}
        norm = "resolved" if any(w in raw for w in resolved_words) else (
               "not_resolved" if any(w in raw for w in not_resolved_words) else raw)

        if norm not in ("resolved", "not_resolved"):
            return {
                "error": "INVALID_OUTCOME",
                "message": "Outcome must be 'resolved' or 'not_resolved'.",
            }

        self.step_outcomes[self.current_step_index] = norm
        steps = ISSUE_STEPS_MAP[self.current_issue_type]

        if norm == "resolved":
            return {
                "outcome": "resolved",
                "employee_id": self.validated_employee_id,
                "issue_type": self.current_issue_type,
                "resolved_at_step": self.current_step_index + 1,
                "message": "Glad to hear that. Your issue is resolved. Is there anything else I can help with?",
            }

        # not_resolved — suggest next step or escalate
        if self.current_step_index < len(steps) - 1:
            return {
                "outcome": "not_resolved",
                "employee_id": self.validated_employee_id,
                "issue_type": self.current_issue_type,
                "current_step": self.current_step_index + 1,
                "next_action": "Call navigate_support_step with command=next to proceed.",
                "message": "Understood. Let's try the next step.",
            }
        else:
            return {
                "outcome": "not_resolved",
                "all_steps_exhausted": True,
                "employee_id": self.validated_employee_id,
                "issue_type": self.current_issue_type,
                "message": "All troubleshooting steps have been tried without resolution. Escalating to IT Helpdesk.",
                "escalation": HELPDESK_ESCALATION,
                "next_action": "Call get_smart_escalation_summary to generate a ticket.",
            }

    def _navigate_support_step(self, command: str):
        if not self.validated_employee_id:
            return self._validation_required_response()
        if not self.current_issue_type or self.current_issue_type not in ISSUE_STEPS_MAP:
            return {
                "error": "NO_ACTIVE_ISSUE",
                "message": "No active issue navigation found. Call start_step_navigation first.",
            }

        steps = ISSUE_STEPS_MAP[self.current_issue_type]
        cmd = str(command or "").strip().lower()

        if cmd in ["next", "skip"]:
            if self.current_step_index < len(steps) - 1:
                self.current_step_index += 1
            else:
                return {
                    "issue_type": self.current_issue_type,
                    "resolved_candidate": False,
                    "message": "All troubleshooting steps are completed. If issue persists, escalate to IT Helpdesk.",
                    "escalation": HELPDESK_ESCALATION,
                }
        elif cmd == "back":
            self.current_step_index = max(0, self.current_step_index - 1)
        elif cmd == "start_over":
            self.current_step_index = 0
            self.visited_step_indexes = {0}
        elif cmd in ["repeat", "status"]:
            pass
        else:
            return {
                "error": "INVALID_COMMAND",
                "message": "Use one of: next, repeat, back, skip, start_over, status.",
            }

        payload = self._get_step_state_payload(self.current_issue_type, self.current_step_index)
        payload["employee_id"] = self.validated_employee_id
        return payload

    def _get_smart_escalation_summary(self, reason: str = "User requested escalation"):
        if not self.validated_employee_id:
            return self._validation_required_response()

        if not self.ticket_id:
            self.ticket_id = f"TKT-{uuid.uuid4().hex[:8].upper()}"

        issue = self.current_issue_type or "unknown"
        steps = ISSUE_STEPS_MAP.get(issue, [])
        attempted = [steps[i] for i in sorted(self.visited_step_indexes) if i < len(steps)]
        current_step_text = None
        if steps and 0 <= self.current_step_index < len(steps):
            current_step_text = steps[self.current_step_index]

        step_outcomes_display = {
            f"Step {i + 1}": f"{outcome} — {steps[i][:55]}"
            for i, outcome in self.step_outcomes.items()
            if i < len(steps)
        }

        return {
            "ticket_id": self.ticket_id,
            "employee_id": self.validated_employee_id,
            "language": self.active_language,
            "issue_type": issue,
            "current_step_number": self.current_step_index + 1 if steps else None,
            "current_step_text": current_step_text,
            "attempted_steps": attempted,
            "step_outcomes": step_outcomes_display,
            "employee_id_validation_attempts": self.employee_id_attempts,
            "reason": reason,
            "escalation": HELPDESK_ESCALATION,
        }

    def _validate_employee_id(self, employee_id: str):
        result = validate_employee_id(employee_id)
        if result["is_valid"]:
            self.validated_employee_id = result["employee_id"]
            self.employee_id_attempts = 0
            result["attempts_used"] = 0
            result["attempts_remaining"] = MAX_EMPLOYEE_ID_ATTEMPTS
            return result

        self.employee_id_attempts += 1
        attempts_remaining = max(0, MAX_EMPLOYEE_ID_ATTEMPTS - self.employee_id_attempts)
        result["attempts_used"] = self.employee_id_attempts
        result["attempts_remaining"] = attempts_remaining

        if self.employee_id_attempts >= MAX_EMPLOYEE_ID_ATTEMPTS:
            result["blocked"] = True
            result["error"] = "EMPLOYEE_ID_MAX_ATTEMPTS_REACHED"
            result["message"] = (
                "Maximum employee ID attempts reached. "
                "Please contact IT Helpdesk for manual assistance."
            )
            result["escalation"] = HELPDESK_ESCALATION
        return result

    def _get_password_support_path(self):
        if not self.validated_employee_id:
            return self._validation_required_response()
        result = get_password_support_path()
        self._set_issue_state("password")
        result["employee_id"] = self.validated_employee_id
        result["step_state"] = self._get_step_state_payload("password", self.current_step_index)
        return result

    def _get_citrix_support_path(self):
        if not self.validated_employee_id:
            return self._validation_required_response()
        result = get_citrix_support_path()
        self._set_issue_state("citrix")
        result["employee_id"] = self.validated_employee_id
        result["step_state"] = self._get_step_state_payload("citrix", self.current_step_index)
        return result

    def _get_vpn_support_path(self):
        if not self.validated_employee_id:
            return self._validation_required_response()
        result = get_vpn_support_path()
        self._set_issue_state("vpn")
        result["employee_id"] = self.validated_employee_id
        result["step_state"] = self._get_step_state_payload("vpn", self.current_step_index)
        return result

    def _get_outlook_support_path(self):
        if not self.validated_employee_id:
            return self._validation_required_response()
        result = get_outlook_support_path()
        self._set_issue_state("outlook")
        result["employee_id"] = self.validated_employee_id
        result["step_state"] = self._get_step_state_payload("outlook", self.current_step_index)
        return result

    def _get_all_support_paths_summary(self):
        if not self.validated_employee_id:
            return self._validation_required_response()
        result = get_all_support_paths_summary()
        result["employee_id"] = self.validated_employee_id
        return result

    async def start_session(self, audio_input_queue, video_input_queue, text_input_queue, audio_output_callback, audio_interrupt_callback=None):
        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Puck"
                    )
                )
            ),
            system_instruction=types.Content(parts=[types.Part(text=IT_SUPPORT_SYSTEM_INSTRUCTION)]),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            realtime_input_config=types.RealtimeInputConfig(
                turn_coverage=types.TurnCoverage.TURN_INCLUDES_ONLY_ACTIVITY,
            ),
            tools=self.tools,
        )
        
        
        logger.info(f"Connecting to Gemini Live with model={self.model}")
        try:
          async with self.client.aio.live.connect(model=self.model, config=config) as session:
            logger.info("Gemini Live session opened successfully")
            
            async def send_audio():
                try:
                    while True:
                        chunk = await audio_input_queue.get()
                        await session.send_realtime_input(
                            audio=types.Blob(data=chunk, mime_type=f"audio/pcm;rate={self.input_sample_rate}")
                        )
                except asyncio.CancelledError:
                    logger.debug("send_audio task cancelled")
                except Exception as e:
                    logger.error(f"send_audio error: {e}\n{traceback.format_exc()}")

            async def send_video():
                try:
                    while True:
                        chunk = await video_input_queue.get()
                        logger.info(f"Sending video frame to Gemini: {len(chunk)} bytes")
                        await session.send_realtime_input(
                            video=types.Blob(data=chunk, mime_type="image/jpeg")
                        )
                except asyncio.CancelledError:
                    logger.debug("send_video task cancelled")
                except Exception as e:
                    logger.error(f"send_video error: {e}\n{traceback.format_exc()}")

            async def send_text():
                try:
                    while True:
                        text = await text_input_queue.get()
                        lang_match = re.search(r"LANGUAGE_PREF:\s*([A-Za-z]+)", str(text or ""), flags=re.IGNORECASE)
                        if lang_match:
                            self.active_language = lang_match.group(1).capitalize()
                        logger.info(f"Sending text to Gemini: {text}")
                        await session.send_realtime_input(text=text)
                except asyncio.CancelledError:
                    logger.debug("send_text task cancelled")
                except Exception as e:
                    logger.error(f"send_text error: {e}\n{traceback.format_exc()}")

            event_queue = asyncio.Queue()

            async def receive_loop():
                try:
                    while True:
                        async for response in session.receive():
                            logger.debug(f"Received response from Gemini: {response}")
                            
                            # Log the raw response type for debugging
                            if response.go_away:
                                logger.warning(f"Received GoAway from Gemini: {response.go_away}")
                            if response.session_resumption_update:
                                logger.info(f"Session resumption update: {response.session_resumption_update}")
                            
                            server_content = response.server_content
                            tool_call = response.tool_call
                            
                            if server_content:
                                if server_content.model_turn:
                                    for part in (server_content.model_turn.parts or []):
                                        if part.inline_data:
                                            if inspect.iscoroutinefunction(audio_output_callback):
                                                await audio_output_callback(part.inline_data.data)
                                            else:
                                                audio_output_callback(part.inline_data.data)
                                
                                if server_content.input_transcription and server_content.input_transcription.text:
                                    await event_queue.put({"type": "user", "text": server_content.input_transcription.text})
                                
                                if server_content.output_transcription and server_content.output_transcription.text:
                                    await event_queue.put({"type": "gemini", "text": server_content.output_transcription.text})
                                
                                if server_content.turn_complete:
                                    await event_queue.put({"type": "turn_complete"})
                                
                                if server_content.interrupted:
                                    if audio_interrupt_callback:
                                        if inspect.iscoroutinefunction(audio_interrupt_callback):
                                            await audio_interrupt_callback()
                                        else:
                                            audio_interrupt_callback()
                                    await event_queue.put({"type": "interrupted"})

                            if tool_call:
                                function_responses = []
                                for fc in (tool_call.function_calls or []):
                                    func_name = fc.name
                                    if not func_name:
                                        continue
                                    args = fc.args or {}
                                    
                                    if func_name in self.tool_mapping:
                                        try:
                                            tool_func = self.tool_mapping[func_name]
                                            if inspect.iscoroutinefunction(tool_func):
                                                result = await tool_func(**args)
                                            else:
                                                loop = asyncio.get_running_loop()
                                                result = await loop.run_in_executor(None, lambda: tool_func(**args))
                                        except Exception as e:
                                            result = f"Error: {e}"
                                        
                                        function_responses.append(types.FunctionResponse(
                                            name=func_name,
                                            id=fc.id,
                                            response={"result": result}
                                        ))
                                        await event_queue.put({"type": "tool_call", "name": func_name, "args": args, "result": result})
                                
                                await session.send_tool_response(function_responses=function_responses)
                        
                        # session.receive() iterator ended (e.g. after turn_complete) — re-enter to keep listening
                        logger.debug("Gemini receive iterator completed, re-entering receive loop")

                except asyncio.CancelledError:
                    logger.debug("receive_loop task cancelled")
                except Exception as e:
                    logger.error(f"receive_loop error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
                    await event_queue.put({"type": "error", "error": f"{type(e).__name__}: {e}"})
                finally:
                    logger.info("receive_loop exiting")
                    await event_queue.put(None)

            send_audio_task = asyncio.create_task(send_audio())
            send_video_task = asyncio.create_task(send_video())
            send_text_task = asyncio.create_task(send_text())
            receive_task = asyncio.create_task(receive_loop())

            try:
                while True:
                    event = await event_queue.get()
                    if event is None:
                        break
                    if isinstance(event, dict) and event.get("type") == "error":
                        # Just yield the error event, don't raise to keep the stream alive if possible or let caller handle
                        yield event
                        break 
                    yield event
            finally:
                logger.info("Cleaning up Gemini Live session tasks")
                send_audio_task.cancel()
                send_video_task.cancel()
                send_text_task.cancel()
                receive_task.cancel()
        except Exception as e:
            logger.error(f"Gemini Live session error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            raise
        finally:
            logger.info("Gemini Live session closed")
