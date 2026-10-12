"""
ShopSmart AI Agent — OpenAI backend (Chat Completions with tool calling).

Same public interface as the Gemini agent in agent.core:
    process_message(user_message, user_id) -> {"response", "tool_calls", "error"}
    reset_chat()
"""
import json
import traceback

import config
from agent import context
from agent.prompts import SYSTEM_PROMPT
from agent.tools import (
    web_search, price_scraper, price_tracker, price_analyzer, notifier,
)

TOOL_FUNCTIONS = {
    "search_product": web_search.search_product,
    "scrape_price": price_scraper.scrape_price,
    "track_price": price_tracker.track_price,
    "get_tracked_products": price_tracker.get_tracked_products,
    "analyze_price": price_analyzer.analyze_price,
    "send_notification": notifier.send_notification,
}

_TOOL_DEFS = [
    web_search.TOOL_DEFINITION,
    price_scraper.TOOL_DEFINITION,
    *price_tracker.TOOL_DEFINITIONS,
    price_analyzer.TOOL_DEFINITION,
    notifier.TOOL_DEFINITION,
]

OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": d["name"],
            "description": d["description"],
            "parameters": d.get("parameters") or {"type": "object", "properties": {}},
        },
    }
    for d in _TOOL_DEFS
]

# Keep the conversation bounded: tool outputs can be large.
_MAX_TOOL_RESULT_CHARS = 8000
_MAX_HISTORY_MESSAGES = 40


class OpenAIAgent:
    """AI shopping agent powered by OpenAI with tool use."""

    def __init__(self):
        if not config.OPENAI_API_KEY:
            raise ValueError(
                "OPENAI_API_KEY not configured! "
                "Set the OPENAI_API_KEY environment variable."
            )
        from openai import OpenAI

        self.client = OpenAI(
            api_key=config.OPENAI_API_KEY,
            timeout=60.0,
            max_retries=3,  # built-in backoff for 429 / 5xx
        )
        self._model = config.OPENAI_MODEL
        self.messages = []
        print(f"[OK] ShopSmart Agent initialized with OpenAI ({self._model}).")

    def reset_chat(self):
        """Reset the chat session."""
        self.messages = []

    def _trim_history(self):
        """Drop the oldest turns, always cutting at a user message boundary so
        tool_calls and their tool responses are never separated."""
        while len(self.messages) > _MAX_HISTORY_MESSAGES:
            for i in range(1, len(self.messages)):
                if self.messages[i].get("role") == "user":
                    del self.messages[:i]
                    break
            else:
                break

    def _complete(self, allow_tools=True):
        kwargs = {
            "model": self._model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + self.messages,
        }
        if allow_tools:
            kwargs["tools"] = OPENAI_TOOLS
        return self.client.chat.completions.create(**kwargs).choices[0].message

    def _append_assistant(self, msg):
        entry = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments or "{}",
                    },
                }
                for tc in msg.tool_calls
            ]
        self.messages.append(entry)

    def process_message(self, user_message: str, user_id=None) -> dict:
        tool_calls = []
        _ctx_token = context.set_current_user_id(user_id)
        start_len = len(self.messages)

        try:
            self._trim_history()
            self.messages.append({"role": "user", "content": user_message})

            msg = self._complete()
            self._append_assistant(msg)

            iterations = 0
            while msg.tool_calls and iterations < config.MAX_AGENT_ITERATIONS:
                iterations += 1

                for tc in msg.tool_calls:
                    fn_name = tc.function.name
                    try:
                        fn_args = json.loads(tc.function.arguments or "{}")
                        if not isinstance(fn_args, dict):
                            fn_args = {}
                    except json.JSONDecodeError:
                        fn_args = {}

                    print(f"  [TOOL] {fn_name}({fn_args})")
                    tool_result = self._execute_tool(fn_name, fn_args)

                    tool_calls.append({
                        "tool": fn_name,
                        "args": fn_args,
                        "result_preview": tool_result[:200] + "..."
                                          if len(tool_result) > 200 else tool_result,
                    })
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result[:_MAX_TOOL_RESULT_CHARS],
                    })

                msg = self._complete()
                self._append_assistant(msg)

            # Tool-call limit hit without a text answer: force a final summary.
            if msg.tool_calls:
                # Every tool_call must be answered before another request.
                for tc in msg.tool_calls:
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps({"success": False,
                                               "message": "Tool-call limit reached."}),
                    })
                self.messages.append({
                    "role": "user",
                    "content": "Using the information gathered so far, give your best "
                               "final answer in English. Do not call any more tools.",
                })
                msg = self._complete(allow_tools=False)
                self._append_assistant(msg)

            final_text = (msg.content or "").strip()
            if not final_text:
                final_text = "Sorry, I couldn't process this request. Please try again."

            return {"response": final_text, "tool_calls": tool_calls, "error": None}

        except Exception as e:
            traceback.print_exc()
            # Roll back this turn so the history stays consistent.
            del self.messages[start_len:]
            return self._error_result(e, tool_calls)
        finally:
            context.reset_current_user_id(_ctx_token)

    @staticmethod
    def _error_result(e, tool_calls) -> dict:
        error_msg = str(e)
        status = getattr(e, "status_code", None)
        low = error_msg.lower()

        if status in (401, 403) or "api key" in low or "authentication" in low:
            text = "Invalid API key! Please check OPENAI_API_KEY."
        elif status == 429 or "quota" in low or "rate limit" in low:
            text = ("OpenAI rate limit or quota reached. Please wait a moment or "
                    "check your plan at https://platform.openai.com/settings/organization/billing")
        elif status == 404 or "model" in low and "not" in low and "exist" in low:
            text = f"Model '{config.OPENAI_MODEL}' is not available. Check OPENAI_MODEL."
        else:
            text = f"An error occurred: {error_msg}"
        return {"response": text, "tool_calls": tool_calls, "error": error_msg}

    @staticmethod
    def _execute_tool(name: str, args: dict) -> str:
        fn = TOOL_FUNCTIONS.get(name)
        if not fn:
            return json.dumps({"success": False,
                               "message": f"Tool '{name}' does not exist."})
        try:
            return fn(**args)
        except TypeError as e:
            return json.dumps({"success": False,
                               "message": f"Argument error for tool '{name}': {str(e)}"})
        except Exception as e:
            return json.dumps({"success": False,
                               "message": f"Error executing tool '{name}': {str(e)}"})
