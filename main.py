import os
import subprocess
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
_sent_ids: set[str] = set()
_sent_lock = threading.Lock()


def _extract_text(msg: MessageEv) -> str:
    """Pull text out of a regular message or a quoted/reply message."""
    text = msg.Message.conversation or ""
    if not text and msg.Message.extendedTextMessage.text:
        text = msg.Message.extendedTextMessage.text
    return text.strip()


def _send(client: NewClient, chat, text: str):
    """Send a message and track its ID so we don't react to our own replies."""
    resp = client.send_message(chat, text)
    with _sent_lock:
        _sent_ids.add(resp.ID)
        if len(_sent_ids) > 200:
            _sent_ids.clear()


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

    # Skip: groups, messages from others, empty text
    if is_group or not is_from_me or not text:
        return

    # Skip bot's own replies (prevent infinite loop)
    msg_id = msg.Info.ID
    with _sent_lock:
        if msg_id in _sent_ids:
            return

    # Only respond in the self-chat (chat == sender = your own JID)
    if chat.User != sender.User:
        return

    log.info("Processing message: %s", text[:80])
    sender_id = str(sender.User)
    cmd = text.lower()

    if cmd in ("/new", "/reset"):
        bridge.reset_session(sender_id)
        _send(client, chat, "Session reset. Send a new instruction to start fresh.")
        return

    if cmd == "/status":
        with _busy_lock:
            is_busy = _busy
        _send(
            client, chat,
            "Still working on it..." if is_busy else "Idle. Send me something to do!",
        )
        return

    if cmd == "/projects":
        _send(client, chat, _list_projects())
        return

    if cmd.startswith("/clone "):
        repo_url = text[7:].strip()
        _send(client, chat, f"Cloning {repo_url}...")
        threading.Thread(
            target=_clone_repo, args=(client, chat, repo_url), daemon=True
        ).start()
        return

    if cmd == "/help":
        _send(client, chat, (
            "Commands:\n"
            "/projects - list cloned repos\n"
            "/clone <url> - clone a GitHub repo\n"
            "/new - reset session\n"
            "/status - check if busy\n"
            "/help - this message\n\n"
            "Or just send any instruction for the Cursor agent."
        ))
        return

    with _busy_lock:
        if _busy:
            _send(client, chat, "Still working on the previous task. Wait or send /status.")
            return
        _busy = True

    _send(client, chat, "Got it, working on it...")

    threading.Thread(
        target=_process_message, args=(client, chat, sender_id, text), daemon=True
    ).start()


def _list_projects() -> str:
    base = bridge.base_path
    if not os.path.isdir(base):
        return f"Base path {base} doesn't exist yet."
    dirs = sorted(
        d for d in os.listdir(base)
        if os.path.isdir(os.path.join(base, d)) and not d.startswith(".")
    )
    if not dirs:
        return "No projects yet. Use /clone <url> to add one."
    return "Projects:\n" + "\n".join(f"• {d}" for d in dirs)


def _clone_repo(client: NewClient, chat, repo_url: str):
    try:
        result = subprocess.run(
            ["git", "clone", repo_url],
            cwd=bridge.base_path,
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
            _send(client, chat, f"Cloned '{repo_name}' successfully!\n\n{_list_projects()}")
        else:
            _send(client, chat, f"Clone failed:\n{result.stderr[:300]}")
    except Exception as e:
        log.exception("Clone error")
        _send(client, chat, f"Clone error: {e}")


def _process_message(client: NewClient, chat, sender: str, text: str):
    global _busy
    try:
        log.info("Processing: %s", text[:100])
        summary = bridge.send_message(sender, text)
        _send(client, chat, f"Done!\n\n{summary}")
    except Exception as e:
        log.exception("Error processing message")
        _send(client, chat, f"Error: {str(e)[:300]}")
    finally:
        with _busy_lock:
            _busy = False


if __name__ == "__main__":
    log.info("Starting WhatsApp-Cursor bridge...")
    log.info("Base path: %s", bridge.base_path)
    log.info("Scan the QR code with WhatsApp to connect (first time only)")
    wa.connect()
    event.wait()
