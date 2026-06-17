import os
import threading
import logging
from dotenv import load_dotenv
from neonize.client import NewClient
from neonize.events import MessageEv, ConnectedEv, event
from cursor_bridge import CursorBridge

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
log = logging.getLogger(__name__)

wa = NewClient("cursor_bridge", database="./session.db")
bridge = CursorBridge()

MY_NUMBER = os.environ.get("MY_WHATSAPP_NUMBER", "")
_busy = False
_busy_lock = threading.Lock()


def _extract_text(msg: MessageEv) -> str:
    """Pull text out of a regular message or a quoted/reply message."""
    text = ""
    try:
        text = msg.message.conversation or ""
    except (AttributeError, TypeError):
        pass
    if not text:
        try:
            text = msg.message.extendedTextMessage.text or ""
        except (AttributeError, TypeError):
            pass
    return text.strip()


@wa.event(ConnectedEv)
def on_connected(_client: NewClient, _evt: ConnectedEv):
    log.info("Connected to WhatsApp!")


@wa.event(MessageEv)
def on_message(client: NewClient, msg: MessageEv):
    global _busy

    if msg.info.message_source.is_from_me:
        return

    sender = str(msg.info.message_source.sender)
    chat = msg.info.message_source.chat

    if MY_NUMBER and MY_NUMBER not in sender:
        return

    text = _extract_text(msg)
    if not text:
        return

    cmd = text.lower()

    if cmd in ("/new", "/reset"):
        bridge.reset_session(sender)
        client.reply_message("Session reset. Send a new instruction to start fresh.", msg)
        return

    if cmd == "/status":
        with _busy_lock:
            is_busy = _busy
        client.reply_message(
            "Still working on it..." if is_busy else "Idle. Send me something to do!",
            msg,
        )
        return

    with _busy_lock:
        if _busy:
            client.reply_message(
                "Still working on the previous task. Wait or send /status.", msg
            )
            return
        _busy = True

    client.reply_message("Got it, working on it...", msg)

    threading.Thread(
        target=_process_message, args=(client, chat, sender, text), daemon=True
    ).start()


def _process_message(client: NewClient, chat, sender: str, text: str):
    global _busy
    try:
        log.info("Processing: %s", text[:100])
        summary = bridge.send_message(sender, text)
        client.send_message(chat, text=f"Done!\n\n{summary}")
    except Exception as e:
        log.exception("Error processing message")
        client.send_message(chat, text=f"Error: {str(e)[:300]}")
    finally:
        with _busy_lock:
            _busy = False


if __name__ == "__main__":
    log.info("Starting WhatsApp-Cursor bridge...")
    log.info("Workspace: %s", bridge.workspace)
    log.info("Scan the QR code with WhatsApp to connect (first time only)")
    wa.connect()
    event.wait()
