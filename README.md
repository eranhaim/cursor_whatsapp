# WhatsApp-Cursor Bridge

Control a Cursor agent from WhatsApp. Send instructions, get 2-sentence summaries back.

## How it works

```
You (WhatsApp) <---> neonize (WhatsApp Web) <---> Cursor SDK agent
                                                       |
                                                 Your local workspace
```

1. You send a WhatsApp message with an instruction
2. The service forwards it to a Cursor agent running against your local workspace
3. The agent does the work, the service extracts a 2-sentence summary
4. You get the summary back on WhatsApp
5. Follow-up messages continue the same conversation (full context preserved)

No Twilio, no webhooks, no ngrok. Just a direct WhatsApp Web connection.

## Prerequisites

- Python 3.11+
- A [Cursor API key](https://cursor.com/dashboard/integrations)

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
copy .env.example .env
```

Edit `.env`:

| Variable | Description |
|---|---|
| `CURSOR_API_KEY` | Your Cursor API key from the dashboard |
| `CURSOR_BASE_PATH` | Root directory the agent works from (e.g. your Desktop). It can create and switch between project folders under here. |
| `CURSOR_MODEL` | Model to use (default: `composer-2.5`) |
| `MY_WHATSAPP_NUMBER` | Your phone number, digits only with country code (e.g. `972501234567`). Optional, restricts access. |

### 3. Run

```bash
python main.py
```

On first run, a **QR code** will appear in the terminal. Scan it with your WhatsApp app:

1. Open WhatsApp on your phone
2. Go to **Settings > Linked Devices > Link a Device**
3. Scan the QR code

The session persists in `session.db` -- you only need to scan once.

## Usage

Send a WhatsApp message to yourself (or to the linked device's chat):

| Message | What happens |
|---|---|
| Any text | Sent as an instruction to the Cursor agent |
| `/new` or `/reset` | Starts a fresh agent session |
| `/status` | Checks if the agent is still working |

### Example

> **You:** Add error handling to the signup form in src/components/SignupForm.tsx
>
> **Bot:** Got it, working on it...
>
> **Bot:** Done!
>
> Added Zod schema validation to the signup form with email format checking and password strength requirements. The form now shows inline error messages and disables the submit button until all fields are valid.

> **You:** Also add unit tests for that
>
> **Bot:** Got it, working on it...
>
> **Bot:** Done!
>
> Created SignupForm.test.tsx with 8 test cases covering valid inputs, invalid emails, weak passwords, and edge cases. All tests pass using Vitest and React Testing Library.

## Files

- **`main.py`** - Neonize WhatsApp client, message handling, orchestration
- **`cursor_bridge.py`** - Cursor SDK agent lifecycle (create / resume / send / summarize)
