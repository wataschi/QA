import json
import re
from openai import OpenAI


SYSTEM_PROMPT = """\
You are a web testing expert. Convert test descriptions into JSON commands.
Use ONLY selectors from the provided page structure. Do NOT invent selectors.

Available actions:
- goto  : open URL.          Fields: action, value
- click : click element.     Fields: action, selector
- type  : enter text.        Fields: action, selector, value
- wait  : wait for element.  Fields: action, selector

Reply with ONLY valid JSON. No markdown fences, no comments, no trailing commas.

Example:
{
  "name": "Login test",
  "url": "https://example.com/login",
  "steps": [
    {"action": "goto", "value": "https://example.com/login"},
    {"action": "type", "selector": "#email", "value": "user@test.com"},
    {"action": "type", "selector": "#password", "value": "pass123"},
    {"action": "click", "selector": "button[type=submit]"},
    {"action": "wait", "selector": ".dashboard"}
  ]
}
"""

SYSTEM_PROMPT_NO_PAGE = """\
You are a web testing expert. Convert test descriptions into JSON commands.

Available actions:
- goto  : open URL.          Fields: action, value
- click : click element.     Fields: action, selector
- type  : enter text.        Fields: action, selector, value
- wait  : wait for element.  Fields: action, selector

Reply with ONLY valid JSON. No markdown fences, no comments, no trailing commas.

Example:
{
  "name": "Login test",
  "url": "https://example.com/login",
  "steps": [
    {"action": "goto", "value": "https://example.com/login"},
    {"action": "type", "selector": "#email", "value": "user@test.com"},
    {"action": "type", "selector": "#password", "value": "pass123"},
    {"action": "click", "selector": "button[type=submit]"},
    {"action": "wait", "selector": ".dashboard"}
  ]
}
"""


class AITestGenerator:
    """Генератор тестових сценаріїв через LM Studio (OpenAI-сумісний API)."""

    def __init__(self, base_url: str = "http://localhost:1234/v1", model: str = "local-model"):
        self.client = OpenAI(base_url=base_url, api_key="not-needed")
        self.model = model

    def generate_test(self, description: str, url: str, page_structure: str | None = None) -> dict:
        """Генерує тестовий сценарій за описом користувача.

        Якщо page_structure передано — AI використає реальні селектори зі сторінки.
        """
        if page_structure:
            system = SYSTEM_PROMPT
            user_message = (
                f"Website: {url}\n"
                f"Task: {description}\n\n"
                f"Page interactive elements:\n{page_structure}\n\n"
                "Generate a test scenario as JSON. Use ONLY selectors from the list above."
            )
        else:
            system = SYSTEM_PROMPT_NO_PAGE
            user_message = (
                f"Website: {url}\n"
                f"Task: {description}\n\n"
                "Generate a test scenario as JSON."
            )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
        )

        raw = response.choices[0].message.content
        return self._parse_json(raw)

    @staticmethod
    def _clean_json_text(text: str) -> str:
        """Прибирає типові проблеми: коментарі, trailing commas."""
        text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
        text = re.sub(r"/\*[\s\S]*?\*/", "", text)
        text = re.sub(r",\s*([}\]])", r"\1", text)
        return text.strip()

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """Видаляє блоки <think>...</think> з відповідей reasoning-моделей."""
        return re.sub(r"<think>[\s\S]*?</think>", "", text).strip()

    @classmethod
    def _parse_json(cls, text: str) -> dict:
        """Витягує JSON з тексту відповіді LLM."""
        text = cls._strip_thinking(text)

        # Спробувати напряму
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        cleaned = cls._clean_json_text(text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Знайти JSON-блок у markdown ```json ... ```
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            try:
                return json.loads(cls._clean_json_text(match.group(1)))
            except json.JSONDecodeError:
                pass

        # Знайти останній { ... } (найімовірніше валідний JSON)
        matches = list(re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text))
        if matches:
            for m in reversed(matches):
                try:
                    return json.loads(cls._clean_json_text(m.group(0)))
                except json.JSONDecodeError:
                    continue

        raise ValueError(
            f"Не вдалося розпарсити JSON з відповіді AI.\n"
            f"Сира відповідь моделі:\n---\n{text}\n---"
        )
