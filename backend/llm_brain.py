"""
llm_brain.py  -  LLM Brain using Google Gemini (FREE tier)
"""

import os
import json
import re
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.tools import TOOL_DECLARATIONS, dispatch_tool

load_dotenv()
_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))

GEMINI_MODEL = "gemini-2.5-flash"


def _indian_words_to_number(text: str) -> str:
    """Convert Indian number words to digits. e.g. '10 lakh' -> '1000000'"""
    text = re.sub(
        r"(\d+(?:\.\d+)?)\s*(?:crore|करोड़)",
        lambda m: str(int(float(m.group(1)) * 10_000_000)),
        text, flags=re.IGNORECASE)
    text = re.sub(
        r"(\d+(?:\.\d+)?)\s*(?:lakh|lac|लाख)",
        lambda m: str(int(float(m.group(1)) * 100_000)),
        text, flags=re.IGNORECASE)
    text = re.sub(
        r"(\d+(?:\.\d+)?)\s*(?:thousand|hajar|हज़ार|हजार)",
        lambda m: str(int(float(m.group(1)) * 1000)),
        text, flags=re.IGNORECASE)
    return text


BASE_SYSTEM_PROMPT = """
You are "Vaani", a friendly Home Loan Counselor for HomeFirst Finance India.

## ROLE
Help customers with HOME LOANS ONLY. If asked about personal loans, car loans or anything else,
say: "I specialise only in home loans. How can I help you with a home loan?"

## LANGUAGE LOCK
{language_instruction}

## ENTITIES TO COLLECT
Collect ALL FOUR before checking eligibility:
1. monthly_income - net monthly salary/income in INR (plain integer)
2. property_value - property market value in INR (plain integer)
3. loan_amount_requested - loan amount wanted in INR (plain integer)
4. employment_status - exactly one of: "salaried", "self_employed", "business"

Number conversion: "10 lakh" = 1000000, "50 thousand" = 50000, "1 crore" = 10000000

## TOOL CALLING - CRITICAL RULES
1. The moment you have ALL FOUR entities, you MUST call check_eligibility immediately.
   Do NOT say "please wait" or "let me check" - just call the tool directly.
   Do NOT respond with text first and call the tool later - call it IN THIS SAME TURN.
2. For EMI questions, call calculate_emi immediately.
3. NEVER calculate numbers yourself - always use the tools.
4. After tool returns result, explain it warmly in the locked language.

## FLOW
Greet → ask income → ask property value → ask loan amount → ask employment type
→ call check_eligibility tool immediately → explain result → if HIGH score trigger handoff.

## HANDOFF
When lead_score is HIGH, end your message with exactly:
[HANDOFF TRIGGERED: Routing to Human RM]

## STYLE
- Warm and simple language, no jargon
- Indian number format: Rs 10 lakh, Rs 75,000
- One question at a time
- Do NOT repeat greetings in follow-up messages
"""

LANGUAGE_INSTRUCTIONS = {
    "english": "LOCKED TO: English. Reply ONLY in English always.",
    "hindi":   "LOCKED TO: Hindi. हमेशा केवल हिन्दी में जवाब दें। English में बिल्कुल न बोलें।",
    "marathi": "LOCKED TO: Marathi. नेहमी फक्त मराठीत उत्तर द्या।",
    "tamil":   "LOCKED TO: Tamil. எப்போதும் தமிழிலேயே பதிலளிக்கவும்.",
}

DETECT_LANG_PROMPT = (
    'Reply with ONE word only - the language of this text: english, hindi, marathi, or tamil. '
    'Hinglish = hindi.\nText: "{text}"'
)


def _call_with_retry(fn, *args, **kwargs):
    for attempt in range(4):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                wait = 35
                m = re.search(r"retry in (\d+)", msg)
                if m:
                    wait = int(m.group(1)) + 2
                if attempt < 3:
                    time.sleep(wait)
                    continue
            raise


class LoanCounselorBrain:

    def __init__(self):
        self.conversation_history: list[dict] = []
        self.locked_language:   str | None = None
        self.extracted_data:    dict = {}
        self.last_tool_called:  str | None = None
        self.last_tool_result:  dict = {}
        self.handoff_triggered: bool = False
        self._tools = [
            types.Tool(function_declarations=[
                types.FunctionDeclaration(**t) for t in TOOL_DECLARATIONS
            ])
        ]

    def detect_language(self, text: str) -> str:
        try:
            resp = _call_with_retry(
                _client.models.generate_content,
                model=GEMINI_MODEL,
                contents=DETECT_LANG_PROMPT.format(text=text),
            )
            lang = resp.text.strip().lower()
            if lang in ("english", "hindi", "marathi", "tamil"):
                return lang
        except Exception:
            pass
        return "hindi"

    def _system_prompt(self) -> str:
        lang  = self.locked_language or "english"
        instr = LANGUAGE_INSTRUCTIONS.get(lang, LANGUAGE_INSTRUCTIONS["english"])
        return BASE_SYSTEM_PROMPT.format(language_instruction=instr)

    def _extract_entities(self, text: str):
        match = re.search(r"\{[^{}]*\"monthly_income\"[^{}]*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                for key in ("monthly_income", "property_value",
                            "loan_amount_requested", "employment_status"):
                    if data.get(key) is not None:
                        self.extracted_data[key] = data[key]
            except json.JSONDecodeError:
                pass

    def chat(self, user_message: str, rag_context: str = "") -> dict:
        # Convert Indian number words first
        user_message = _indian_words_to_number(user_message)

        # Lock language on first message
        if self.locked_language is None:
            self.locked_language = self.detect_language(user_message)

        content = user_message
        if rag_context:
            content = f"[Policy Info]:\n{rag_context}\n\n[User]: {user_message}"

        self.conversation_history.append({"role": "user", "parts": [{"text": content}]})

        self.last_tool_called = None
        self.last_tool_result = {}
        final_text = ""

        try:
            config = types.GenerateContentConfig(
                system_instruction=self._system_prompt(),
                tools=self._tools,
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode="AUTO"  # Let model decide when to call tools
                    )
                ),
            )

            response = _call_with_retry(
                _client.models.generate_content,
                model=GEMINI_MODEL,
                contents=self.conversation_history,
                config=config,
            )

            # Tool calling loop
            while True:
                part = response.candidates[0].content.parts[0]

                if hasattr(part, "function_call") and part.function_call:
                    fn     = part.function_call
                    t_name = fn.name
                    t_args = dict(fn.args)

                    self.last_tool_called = t_name
                    result_str            = dispatch_tool(t_name, t_args)
                    self.last_tool_result = json.loads(result_str)

                    if t_name == "check_eligibility":
                        for k in ("monthly_income", "property_value",
                                  "loan_amount_requested", "employment_status"):
                            if k in t_args:
                                self.extracted_data[k] = t_args[k]

                    self.conversation_history.append({
                        "role": "model",
                        "parts": [{"function_call": {"name": t_name, "args": t_args}}],
                    })
                    self.conversation_history.append({
                        "role": "user",
                        "parts": [{"function_response": {
                            "name": t_name,
                            "response": {"result": result_str},
                        }}],
                    })

                    response = _call_with_retry(
                        _client.models.generate_content,
                        model=GEMINI_MODEL,
                        contents=self.conversation_history,
                        config=config,
                    )
                else:
                    final_text = part.text if hasattr(part, "text") else ""
                    break

        except Exception as e:
            final_text = f"[Error: {e}]"

        if final_text:
            self.conversation_history.append({
                "role": "model",
                "parts": [{"text": final_text}],
            })
            self._extract_entities(final_text)

        if "[HANDOFF TRIGGERED" in final_text:
            self.handoff_triggered = True

        return {
            "response_text":  final_text,
            "language":       self.locked_language,
            "extracted_data": self.extracted_data,
            "tool_called":    self.last_tool_called,
            "tool_result":    self.last_tool_result,
            "handoff":        self.handoff_triggered,
        }

    def reset(self):
        self.conversation_history = []
        self.locked_language      = None
        self.extracted_data       = {}
        self.last_tool_called     = None
        self.last_tool_result     = {}
        self.handoff_triggered    = False
