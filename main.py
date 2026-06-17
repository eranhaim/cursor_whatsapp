import os
import threading
import logging
import segno
from dotenv import load_dotenv
from neonize.client import NewClient
from neonize.events import MessageEv, ConnectedEv, event
from cursor_bridge import CursorBridge

load_dotenv()
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bridge.log"),
    ],
)
log = logging.getLogger(__name__)

wa = NewClient("cursor_bridge")
bridge = CursorBridge()

MY_NUMBER = os.environ.get("MY_WHATSAPP_NUMBER", "")
_busy = False
_busy_lock = threading.Lock()


def _extract_text(msg: MessageEv) -> str:
    """Pull text out of a regular message or a quoted/reply message."""
    text = msg.Message.conversation or ""
    if not text and msg.Message.extendedTextMessage.text:
        text = msg.Message.extendedTextMessage.text
    return text.strip()


QR_PATH = os.path.join(os.path.dirname(__file__), "qr.png")


@wa.qr
def on_qr(_client: NewClient, qr_data: bytes):
    segno.make_qr(qr_data).save(QR_PATH, scale=10)
    log.info("QR code saved to %s  -- open it and scan with WhatsApp", QR_PATH)


@wa.event(ConnectedEv)
def on_connected(_client: NewClient, _evt: ConnectedEv):
    log.info("Connected to WhatsApp!")
    if os.path.exists(QR_PATH):
        os.remove(QR_PATH)


@wa.event(MessageEv)
def on_message(client: NewClient, msg: MessageEv):
    global _busy
    try:
        _handle_message(client, msg)
    except Exception:
        log.exception("CRASH in on_message")


def _handle_message(client: NewClient, msg: MessageEv):
    global _busy

    chat = msg.Info.MessageSource.Chat
    sender = msg.Info.MessageSource.Sender
    is_from_me = msg.Info.MessageSource.IsFromMe
    is_group = msg.Info.MessageSource.IsGroup

    text = _extract_text(msg)

    log.info(
        "RAW | chat_user=%s chat_server=%s | sender_user=%s sender_server=%s | from_me=%s | group=%s | text=%s",
        chat.User, chat.Server, sender.User, sender.Server,
        is_from_me, is_group, (text or "<empty>")[:60],
    )

    # Only process: non-group, from-me (user messaging themselves), with text
    if is_group or not is_from_me or not text:
        return

    log.info("Processing message: %s", text[:80])
    sender_id = str(sender.User)
    cmd = text.lower()

    if cmd in ("/new", "/reset"):
        bridge.reset_session(sender_id)
        client.send_message(chat, "Session reset. Send a new instruction to start fresh.")
        return

    if cmd == "/status":
        with _busy_lock:
            is_busy = _busy
        client.send_message(
            chat,
            "Still working on it..." if is_busy else "Idle. Send me something to do!",
        )
        return

    with _busy_lock:
        if _busy:
            client.send_message(chat, "Still working on the previous task. Wait or send /status.")
            return
        _busy = True

    client.send_message(chat, "Got it, working on it...")

    threading.Thread(
        target=_process_message, args=(client, chat, sender_id, text), daemon=True
    ).start()


def _process_message(client: NewClient, chat, sender: str, text: str):
    global _busy
    try:
        log.info("Processing: %s", text[:100])
        summary = bridge.send_message(sender, text)
        client.send_message(chat, f"Done!\n\n{summary}")
    except Exception as e:
        log.exception("Error processing message")
        client.send_message(chat, f"Error: {str(e)[:300]}")
    finally:
        with _busy_lock:
            _busy = False


if __name__ == "__main__":
    log.info("Starting WhatsApp-Cursor bridge...")
    log.info("Base path: %s", bridge.base_path)
    log.info("Scan the QR code with WhatsApp to connect (first time only)")
    wa.connect()
    event.wait()
