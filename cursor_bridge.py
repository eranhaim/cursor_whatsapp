import os
import re
import threading
import logging
from cursor_sdk import Agent, AgentOptions, LocalAgentOptions, CursorAgentError

log = logging.getLogger(__name__)

SUMMARY_TAG = "TLDR:"
SUMMARY_INSTRUCTION = (
    '\n\n[After completing the task above, add a final line starting with "TLDR:" '
    "followed by a 2-sentence summary of what you did.]"
)


class CursorBridge:
    """Manages Cursor agent sessions per sender.

    Each sender maps to one persistent agent that can be resumed across
    WhatsApp messages, preserving full conversation context.
    """

    def __init__(self):
        self.api_key = os.environ["CURSOR_API_KEY"]
        self.workspace = os.environ.get("CURSOR_WORKSPACE_PATH", os.getcwd())
        self.model = os.environ.get("CURSOR_MODEL", "composer-2.5")
        self._sessions: dict[str, str] = {}  # sender -> agent_id
        self._lock = threading.Lock()

    def send_message(self, sender: str, message: str) -> str:
        augmented = message + SUMMARY_INSTRUCTION
        agent_id = self._get_session(sender)

        try:
            if agent_id:
                return self._resume_and_send(agent_id, sender, augmented)
            return self._create_and_send(sender, augmented)
        except CursorAgentError as e:
            if not e.is_retryable:
                raise
            log.warning("Retryable error, resetting session: %s", e.message)
            self.reset_session(sender)
            return self._create_and_send(sender, augmented)

    def reset_session(self, sender: str):
        with self._lock:
            self._sessions.pop(sender, None)

    def _get_session(self, sender: str) -> str | None:
        with self._lock:
            return self._sessions.get(sender)

    def _save_session(self, sender: str, agent_id: str):
        with self._lock:
            self._sessions[sender] = agent_id

    def _create_and_send(self, sender: str, message: str) -> str:
        with Agent.create(
            model=self.model,
            api_key=self.api_key,
            local=LocalAgentOptions(cwd=self.workspace),
        ) as agent:
            self._save_session(sender, agent.agent_id)
            log.info("Created agent %s for %s", agent.agent_id, sender)
            return self._execute_run(agent, message)

    def _resume_and_send(self, agent_id: str, sender: str, message: str) -> str:
        try:
            with Agent.resume(
                agent_id,
                AgentOptions(api_key=self.api_key),
            ) as agent:
                log.info("Resumed agent %s for %s", agent_id, sender)
                return self._execute_run(agent, message)
        except CursorAgentError:
            log.warning("Could not resume agent %s, creating new session", agent_id)
            self.reset_session(sender)
            return self._create_and_send(sender, message)

    def _execute_run(self, agent, message: str) -> str:
        run = agent.send(message)
        full_text = run.text()

        if not full_text:
            return "Task completed (no text output)."

        log.info("Run completed, response length: %d chars", len(full_text))
        return self._extract_summary(full_text)

    @staticmethod
    def _extract_summary(text: str) -> str:
        if SUMMARY_TAG in text:
            raw = text.split(SUMMARY_TAG)[-1].strip()
            sentences = re.split(r"(?<=[.!?])\s+", raw)
            summary = " ".join(sentences[:2]).strip()
            if summary:
                return summary

        # Fallback: strip code blocks and grab the first 2 meaningful sentences
        clean = re.sub(r"```[\s\S]*?```", "", text)
        clean = re.sub(r"\n+", " ", clean).strip()
        sentences = re.split(r"(?<=[.!?])\s+", clean)
        meaningful = [s for s in sentences if len(s) > 20]
        if meaningful:
            return " ".join(meaningful[:2]).strip()

        return text[:300].strip() + ("..." if len(text) > 300 else "")
