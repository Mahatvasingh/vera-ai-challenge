# magicpin Vera AI Challenge — Team:VEXA AI

This is our submission for the magicpin Vera AI challenge. The project is a FastAPI-based backend that generates context-aware, outbound WhatsApp messages for local merchants and handles multi-turn replies.

## How It Works

Instead of passing raw data straight to an LLM and hoping it doesn't hallucinate, the bot uses a two-step generation process:

1. **Deterministic Baseline:** `core/composer.py` maps each trigger (like `perf_dip` or `recall_due`) to a strict Python template. This extracts the exact numbers, dates, and names from the JSON payloads so the core facts are guaranteed to be 100% accurate.
2. **LLM Formatting:** We pass that grounded baseline to the LLM (OpenAI `gpt-4o-mini`) along with the category tone guidelines. The LLM acts as a formatter—making the tone natural, ensuring it fits the merchant's vertical (like using "Dr." for dentists), and ending with a single binary Call-To-Action (e.g., "Reply 1 or 2").

### Guardrails & Safety
* **No Hallucinated Numbers:** Before sending, `guardrails.py` runs `passes_grounding()`. It scans the final message for any numbers, percentages, or prices. If a number exists in the message that wasn't in the input contexts, the message is blocked and it falls back to the safe template.
* **Taboo Filtering:** Checks against the vertical's `vocab_taboo` list to prevent medical overclaims or banned words.
* **Auto-Reply Loops:** Tracks conversation history. If it sees 3 identical messages or common WhatsApp auto-reply phrases, it ends the conversation to prevent bot-to-bot spam loops.
* **Hostility & Opt-Outs:** Detects "stop", "spam", etc. If the user is hostile, the bot triggers a clean `end` action.

## Project Structure

* `bot.py`: The main FastAPI server containing the 5 required endpoints (`/healthz`, `/metadata`, `/context`, `/tick`, `/reply`).
* `core/composer.py`: The routing logic for all 25 trigger types and prompt generation.
* `core/guardrails.py`: Safety checks for numbers, taboos, and repeat loops.
* `core/schemas.py`: Pydantic models enforcing the API contract.
* `judge_simulator.py`: The local test harness to run the benchmarks.

## Running the Project Locally

**1. Install dependencies**
```bash
python -m venv venv
source venv/bin/activate  # Or venv\Scripts\activate on Windows
pip install -r requirements.txt
