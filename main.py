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
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
log = logging.getLogger(__name__)

wa = NewClient("cursor_bridge")
bridge = CursorBridge()

MY_NUMBER = os.environ.get("MY_WHATSAPP_NUMBER", "")
_busy = False
_busy_lock = threading.Lock()


def _is_self_chat(chat_str: str) -> bool:
    """Check if this is the 'Message yourself' / 'Note to self' chat."""
    return MY_NUMBER in chat_str


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

    chat = msg.Info.MessageSource.Chat
    chat_str = str(chat)
    sender = str(msg.Info.MessageSource.Sender)
    is_from_me = msg.Info.MessageSource.IsFromMe
    is_group = msg.Info.MessageSource.IsGroup

    text = _extract_text(msg)

    log.info(
        "RAW EVENT | chat=%s | sender=%s | from_me=%s | group=%s | text=%s",
        chat_str, sender, is_from_me, is_group, (text or "<empty>")[:60],
    )
    log.info("MY_NUMBER=%s | in_chat=%s", MY_NUMBER, MY_NUMBER in chat_str if MY_NUMBER else "no_filter")

    if MY_NUMBER and MY_NUMBER not in chat_str:
        log.info("SKIPPED: chat does not match MY_NUMBER")
        return

    if not text:
        log.info("SKIPPED: no text content")
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
    log.info("Base path: %s", bridge.base_path)
    log.info("Scan the QR code with WhatsApp to connect (first time only)")
    wa.connect()
    event.wait()
