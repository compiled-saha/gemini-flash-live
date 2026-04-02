import asyncio
import inspect
import logging
import re
import traceback
from typing import Any

logger = logging.getLogger(__name__)
from google import genai
from google.genai import types

PASSWORD_PATH_STEPS = [
    'Click "Forgot Password" on the login page.',
    "Enter your email, username, or phone number.",
    "Check email or SMS for a reset link or code.",
    "Use the link or code to set a new password.",
    "Log in with your new password.",
]

CITRIX_PATH_STEPS = [
    "Check internet connection.",
    "Verify username and password.",
    "Update Citrix Workspace to the latest version.",
    "Clear cache or temp files, then restart the app.",
    "Try another browser or device.",
]

VPN_PATH_STEPS = [
    "Check internet connection.",
    "Verify username and password.",
    "Update VPN client to the latest version.",
    "Clear cache and restart the app or device.",
    "Try another network, such as mobile hotspot.",
]

OUTLOOK_PATH_STEPS = [
    "Check internet connection.",
    "Verify recipient email address is correct.",
    "Check your Junk or Spam folder for missing emails.",
    "Clear the Outbox by deleting any stuck or large emails.",
    "Restart Outlook by closing and reopening the application.",
    "Update Outlook to the latest version.",
    "Check mail server settings such as SMTP or Exchange configuration.",
    "Re-authenticate your account if your password was recently changed.",
    "Recreate your Outlook profile if the mailbox is corrupted.",
]

HELPDESK_ESCALATION = "Please contact IT Helpdesk for manual assistance."
MAX_EMPLOYEE_ID_ATTEMPTS = 3


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
            "password": "Reset password using Forgot Password and retry login.",
            "citrix": "Check internet and credentials, then update and restart Citrix Workspace.",
            "vpn": "Check internet and credentials, then update VPN client and retry on another network.",
            "outlook": "Check internet, verify recipient, clear Outbox, restart Outlook, and check mail server settings.",
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
- Supported reply languages are: English, Telugu, Marathi, Bangla.
- If you receive a control message in format "LANGUAGE_PREF: <Language>", switch reply language immediately.
- After language is set, reply only in that language until a new LANGUAGE_PREF message arrives.
- Do not send a standalone acknowledgement for LANGUAGE_PREF control messages.
- Do not provide troubleshooting steps until employee ID is validated.
- Allow at most 3 invalid employee ID attempts.
- On the 3rd invalid attempt, stop verification and instruct caller to contact IT Helpdesk.
- If the issue type is unclear, ask them to choose Password, Citrix, VPN, or Outlook.
- If user asks for all options, call tool get_all_support_paths_summary and summarize briefly.
- When user selects Password issue, call tool get_password_support_path.
- When user selects Citrix issue, call tool get_citrix_support_path.
- When user selects VPN login issue, call tool get_vpn_support_path.
- When user selects Outlook issue, call tool get_outlook_support_path.
- After tool result, guide the user through steps one by one and use tool escalation message when needed.
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
            "get_password_support_path": self._get_password_support_path,
            "get_citrix_support_path": self._get_citrix_support_path,
            "get_vpn_support_path": self._get_vpn_support_path,
            "get_outlook_support_path": self._get_outlook_support_path,
            "get_all_support_paths_summary": self._get_all_support_paths_summary,
        }

    def _validation_required_response(self):
        return {
            "error": "EMPLOYEE_ID_REQUIRED",
            "message": "Employee ID verification is required before troubleshooting.",
            "next_action": "Ask caller for a 4-digit employee ID and call validate_employee_id.",
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
        result["employee_id"] = self.validated_employee_id
        return result

    def _get_citrix_support_path(self):
        if not self.validated_employee_id:
            return self._validation_required_response()
        result = get_citrix_support_path()
        result["employee_id"] = self.validated_employee_id
        return result

    def _get_vpn_support_path(self):
        if not self.validated_employee_id:
            return self._validation_required_response()
        result = get_vpn_support_path()
        result["employee_id"] = self.validated_employee_id
        return result

    def _get_outlook_support_path(self):
        if not self.validated_employee_id:
            return self._validation_required_response()
        result = get_outlook_support_path()
        result["employee_id"] = self.validated_employee_id
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
