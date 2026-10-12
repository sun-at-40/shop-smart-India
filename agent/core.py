"""
ShopSmart AI Agent Core — ReAct loop with Gemini (google-genai SDK).
"""
import json
import time
import traceback

from google import genai
from google.genai import types

import config
from agent import context
from agent.prompts import SYSTEM_PROMPT
from agent.tools import web_search, price_scraper, price_tracker, price_analyzer, notifier


# ── Tool Registry ──────────────────────────────────────────
TOOL_FUNCTIONS = {
    "search_product": web_search.search_product,
    "scrape_price": price_scraper.scrape_price,
    "track_price": price_tracker.track_price,
    "get_tracked_products": price_tracker.get_tracked_products,
    "analyze_price": price_analyzer.analyze_price,
    "send_notification": notifier.send_notification,
}

# Pass callables directly — genai SDK auto-generates the schema from type hints.
_TOOL_CALLABLES = list(TOOL_FUNCTIONS.values())


class ShopSmartAgent:
    """AI Shopping Agent powered by Gemini with tool-use."""

    def __init__(self):
        if not config.GEMINI_API_KEY:
            raise ValueError(
                "GEMINI_API_KEY not configured! "
                "Set environment variable GEMINI_API_KEY."
            )

        self.client = genai.Client(api_key=config.GEMINI_API_KEY)

        # Disable the SDK's automatic function calling so we can intercept each
        # tool call, execute it ourselves, and report it back to the frontend.
        self._config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=_TOOL_CALLABLES,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )

        self._model = config.GEMINI_MODEL
        self.chat = self.client.chats.create(
            model=self._model,
            config=self._config,
        )
        print("[OK] ShopSmart Agent initialized successfully.")

    def reset_chat(self):
        """Reset the chat session."""
        self._model = config.GEMINI_MODEL
        self.chat = self.client.chats.create(
            model=self._model,
            config=self._config,
        )

    def _send(self, message):
        """Send a message, retrying on transient 503/429 errors, then falling
        back to GEMINI_FALLBACK_MODEL (keeping chat history) if configured."""
        delays = [1, 3, 6]
        for attempt in range(len(delays) + 1):
            try:
                return self.chat.send_message(message)
            except Exception as e:
                code = getattr(e, "code", None)
                transient = code in (429, 503) or "UNAVAILABLE" in str(e)
                if not transient:
                    raise
                if attempt < len(delays):
                    time.sleep(delays[attempt])
                    continue
                fallback = config.GEMINI_FALLBACK_MODEL
                if not fallback or fallback == self._model:
                    raise
                print(f"[WARN] {self._model} overloaded, falling back to {fallback}")
                history = self.chat.get_history()
                self._model = fallback
                self.chat = self.client.chats.create(
                    model=fallback, config=self._config, history=history
                )
                return self.chat.send_message(message)

    def process_message(self, user_message: str, user_id=None) -> dict:
        """
        Process a user message through the ReAct loop.

        Args:
            user_message: the user's text.
            user_id: the authenticated user's id, made available to tools
                (e.g. track_price) via agent.context during this call.

        Returns:
            dict with keys: response (str), tool_calls (list), error (str|None)
        """
        tool_calls = []
        _ctx_token = context.set_current_user_id(user_id)

        try:
            response = self._send(user_message)

            # ReAct loop — keep processing until we get a text response.
            iterations = 0
            while iterations < config.MAX_AGENT_ITERATIONS:
                iterations += 1

                function_calls = self._extract_function_calls(response)
                if not function_calls:
                    break

                function_response_parts = []
                for fc in function_calls:
                    fn_name = fc.name
                    fn_args = dict(fc.args) if fc.args else {}

                    print(f"  [TOOL] {fn_name}({fn_args})")

                    tool_result = self._execute_tool(fn_name, fn_args)

                    tool_calls.append({
                        "tool": fn_name,
                        "args": fn_args,
                        "result_preview": tool_result[:200] + "..."
                                          if len(tool_result) > 200 else tool_result,
                    })

                    function_response_parts.append(
                        types.Part.from_function_response(
                            name=fn_name,
                            response={"result": tool_result},
                        )
                    )

                # Send all function responses back to Gemini.
                response = self._send(function_response_parts)

            final_text = self._extract_text(response)
            if not final_text:
                # Tool-call limit reached without a text answer: ask for a summary.
                try:
                    response = self._send(
                        "Using the information gathered so far, give the user your "
                        "best final answer in English. Do not call any more tools."
                    )
                    final_text = self._extract_text(response)
                except Exception:
                    final_text = ""
            if not final_text:
                final_text = "Sorry, I couldn't process this request. Please try again."

            return {
                "response": final_text,
                "tool_calls": tool_calls,
                "error": None,
            }

        except Exception as e:
            traceback.print_exc()
            error_msg = str(e)

            if "API_KEY" in error_msg.upper() or "authentication" in error_msg.lower():
                return {
                    "response": "Invalid API key! Please check GEMINI_API_KEY.",
                    "tool_calls": tool_calls,
                    "error": error_msg,
                }

            if "quota" in error_msg.lower() or "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                return {
                    "response": "API quota exceeded. Please wait a few minutes or create a new API key at https://aistudio.google.com/apikey",
                    "tool_calls": tool_calls,
                    "error": error_msg,
                }

            return {
                "response": f"An error occurred: {error_msg}",
                "tool_calls": tool_calls,
                "error": error_msg,
            }
        finally:
            context.reset_current_user_id(_ctx_token)

    @staticmethod
    def _extract_function_calls(response) -> list:
        """Collect all function_call parts from a model response."""
        calls = []
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            if not content or not getattr(content, "parts", None):
                continue
            for part in content.parts:
                fc = getattr(part, "function_call", None)
                if fc and fc.name:
                    calls.append(fc)
        return calls

    @staticmethod
    def _extract_text(response) -> str:
        """Concatenate all text parts from a model response."""
        # response.text is provided by the SDK as a convenience accessor.
        text = getattr(response, "text", None)
        if text:
            return text

        collected = ""
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            if not content or not getattr(content, "parts", None):
                continue
            for part in content.parts:
                part_text = getattr(part, "text", None)
                if part_text:
                    collected += part_text
        return collected

    def _execute_tool(self, name: str, args: dict) -> str:
        """Execute a tool by name with given arguments."""
        fn = TOOL_FUNCTIONS.get(name)
        if not fn:
            return json.dumps({
                "success": False,
                "message": f"Tool '{name}' does not exist."
            })

        try:
            return fn(**args)
        except TypeError as e:
            return json.dumps({
                "success": False,
                "message": f"Argument error for tool '{name}': {str(e)}"
            })
        except Exception as e:
            return json.dumps({
                "success": False,
                "message": f"Error executing tool '{name}': {str(e)}"
            })


def create_agent():
    """Create the chat agent for the configured LLM provider (config.LLM_PROVIDER)."""
    if config.LLM_PROVIDER == "openai":
        from agent.openai_core import OpenAIAgent
        return OpenAIAgent()
    return ShopSmartAgent()
