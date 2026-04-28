"""
LM Studio client — wraps the OpenAI-compatible local API.

Robust JSON handling:
- Uses LM Studio's response_format=json_object for guaranteed valid JSON
- Falls back to extraction + repair if model ignores the directive
- Returns None instead of raising on unrecoverable parse errors
"""
import json
import re
from typing import Optional, Any
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential


def _extract_json_block(text: str) -> Optional[str]:
    """Find the largest JSON object/array in arbitrary text."""
    text = text.strip()

    # Strip markdown fences
    if text.startswith("```"):
        # Drop first line (```json or ```) and any trailing ```
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"```\s*$", "", text)
        text = text.strip()

    # Find {...} or [...] (largest balanced span)
    obj_start = text.find("{")
    arr_start = text.find("[")
    if obj_start == -1 and arr_start == -1:
        return None

    if obj_start == -1:
        start = arr_start
        open_c, close_c = "[", "]"
    elif arr_start == -1:
        start = obj_start
        open_c, close_c = "{", "}"
    else:
        if obj_start < arr_start:
            start = obj_start
            open_c, close_c = "{", "}"
        else:
            start = arr_start
            open_c, close_c = "[", "]"

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text[start:]


def _repair_json(s: str) -> str:
    """Common-case JSON repairs: trailing commas, smart quotes."""
    # Smart quotes → straight quotes
    s = s.replace("“", '"').replace("”", '"')
    s = s.replace("‘", "'").replace("’", "'")
    # Remove trailing commas before ] or }
    s = re.sub(r",(\s*[}\]])", r"\1", s)
    return s


def parse_llm_json(raw: str) -> Optional[Any]:
    """Best-effort parsing of LLM output as JSON. Returns None on failure."""
    if not raw:
        return None

    # Try direct
    try:
        return json.loads(raw)
    except Exception:
        pass

    # Strip markdown / extract block
    block = _extract_json_block(raw)
    if not block:
        return None

    # Try block
    try:
        return json.loads(block)
    except Exception:
        pass

    # Repair and retry
    try:
        return json.loads(_repair_json(block))
    except Exception:
        return None


class LMStudioClient:
    def __init__(self, config: dict):
        lm_cfg = config.get("lmstudio", {})
        self.client = OpenAI(
            base_url=lm_cfg.get("base_url", "http://localhost:1234/v1"),
            api_key=lm_cfg.get("api_key", "lm-studio"),
        )
        self.model = lm_cfg.get("model", "auto")
        self.temperature = lm_cfg.get("temperature", 0.7)
        self.max_tokens = lm_cfg.get("max_tokens", 2048)
        self._resolved_model: Optional[str] = None

    def _get_model(self) -> str:
        if self._resolved_model:
            return self._resolved_model
        if self.model != "auto":
            self._resolved_model = self.model
            return self.model
        models = self.client.models.list()
        if not models.data:
            raise RuntimeError(
                "No models loaded in LM Studio. Open LM Studio and load a model first."
            )
        self._resolved_model = models.data[0].id
        return self._resolved_model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def chat(
        self,
        messages: list[dict],
        temperature: Optional[float] = None,
        json_mode: bool = False,
        max_tokens: Optional[int] = None,
    ) -> str:
        kwargs = {
            "model": self._get_model(),
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content.strip()

    def chat_json(
        self,
        messages: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Optional[Any]:
        """Chat and return parsed JSON. Returns None on failure (never raises)."""
        # First try with strict JSON mode
        try:
            raw = self.chat(messages, temperature, json_mode=True, max_tokens=max_tokens)
            parsed = parse_llm_json(raw)
            if parsed is not None:
                return parsed
        except Exception:
            pass

        # Fallback: free-form chat + lenient extraction
        try:
            raw = self.chat(messages, temperature, json_mode=False, max_tokens=max_tokens)
            return parse_llm_json(raw)
        except Exception as e:
            print(f"[LLM] chat_json totally failed: {e}")
            return None

    def is_available(self) -> bool:
        try:
            self._get_model()
            return True
        except Exception:
            return False
