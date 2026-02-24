import json
import re
from openai import OpenAI


ACTIONS_REF = """Step: {"action":"NAME","selector":"CSS","value":"VAL"}
Actions: goto,click,type,clear,hover,select,scroll,press,pause,wait,wait_hidden,wait_visible,wait_url,assert_text,assert_visible,assert_not_visible,assert_url,assert_title,assert_count,assert_attribute,screenshot
"""

SYSTEM_PROMPT = """\
You are a Senior QA Engineer following ISTQB standards.
Generate a FUNCTIONAL test scenario as JSON. Focus on user behavior, not implementation.

QA Checklist:
- Positive flow: verify the feature works as expected
- Verify UI state: elements visible, text correct, URLs match
- Each action MUST be followed by an assertion
- No duplicate steps. No invented selectors.
- Navigation: "-> /path" means assert_url "/path"
- [hover X first]: add hover step before click on dropdown items

Output: ONLY valid JSON, no markdown.
""" + ACTIONS_REF

SYSTEM_PROMPT_NO_PAGE = """\
You are a Senior QA Engineer following ISTQB standards.
Generate a FUNCTIONAL test scenario as JSON.
Focus on user behavior. Each action must have an assertion. No duplicates.
Output: ONLY valid JSON, no markdown.
""" + ACTIONS_REF

SYSTEM_PROMPT_SPEC = """\
You are a Senior QA Engineer. Generate test cases from a specification document.
Follow ISTQB methodology: positive tests, negative tests, boundary values, edge cases.

Rules:
1. Generate MULTIPLE independent test scenarios covering the specification
2. Each scenario: {"name":"short_id","description":"what is tested","priority":"high|medium|low","steps":[...]}
3. Wrap all in: {"scenarios":[...]}
4. Use selectors from page structure when available. Otherwise use reasonable CSS selectors.
5. Every action MUST have an assertion verifying expected result
6. Tests must be FUNCTIONAL — test user behavior described in the spec, not site-specific details
7. Cover: happy path, validation errors, edge cases, required fields, navigation
8. [hover X first]: add hover before clicking dropdown items
9. Output: ONLY valid JSON, no markdown.

""" + ACTIONS_REF


class AITestGenerator:
    """Генератор тестових сценаріїв через LM Studio (OpenAI-сумісний API)."""

    def __init__(self, base_url: str = "http://localhost:1234/v1", model: str = "local-model"):
        self.client = OpenAI(base_url=base_url, api_key="not-needed")
        self.model = model

    def _call_llm(self, system: str, user_message: str, max_tokens: int = 2048) -> str:
        """Відправляє запит до LLM і повертає сиру відповідь."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    def generate_test(self, description: str, url: str,
                      page_structure: str | None = None,
                      page_data: dict | None = None) -> dict:
        """Генерує тестовий сценарій за описом користувача."""
        self._page_data = page_data
        if page_structure:
            system = SYSTEM_PROMPT
            user_message = (
                f"Site: {url}\nTask: {description}\n\n"
                f"{page_structure}\n\n"
                "JSON test scenario:"
            )
        else:
            system = SYSTEM_PROMPT_NO_PAGE
            user_message = (
                f"Website: {url}\n"
                f"Task: {description}\n\n"
                "Generate a test scenario as JSON."
            )

        raw = self._call_llm(system, user_message)
        data = self._parse_json(raw)
        if isinstance(data, list):
            data = {"steps": data}
        if "steps" not in data:
            for key, val in data.items():
                if isinstance(val, list) and val:
                    data["steps"] = val
                    break
        if "steps" in data:
            dropdown_map = self._build_dropdown_map(self._page_data) if self._page_data else {}
            data["steps"] = self._postprocess_steps(data["steps"], dropdown_map)
        return data

    def generate_from_spec(self, spec_text: str, url: str,
                           page_structure: str | None = None,
                           page_data: dict | None = None) -> list[dict]:
        """Генерує набір тест-кейсів за специфікацією/ТЗ.

        Повертає список сценаріїв, кожен — dict з name, description, priority, steps.
        """
        self._page_data = page_data
        dropdown_map = self._build_dropdown_map(page_data) if page_data else {}

        parts = [f"URL: {url}", f"\nSPECIFICATION:\n{spec_text}"]
        if page_structure:
            parts.append(f"\nPAGE STRUCTURE:\n{page_structure}")
        parts.append("\nGenerate test scenarios as JSON:")
        user_message = "\n".join(parts)

        raw = self._call_llm(SYSTEM_PROMPT_SPEC, user_message, max_tokens=4096)
        try:
            data = self._parse_json(raw)
        except ValueError:
            data = {"scenarios": self._extract_partial_scenarios(raw)}

        if isinstance(data, list):
            scenarios = data
        elif "scenarios" in data:
            scenarios = data["scenarios"]
        else:
            for val in data.values():
                if isinstance(val, list) and val:
                    scenarios = val
                    break
            else:
                scenarios = [data]

        result = []
        for sc in scenarios:
            if not isinstance(sc, dict):
                continue
            if "steps" not in sc:
                for key, val in sc.items():
                    if isinstance(val, list) and val:
                        sc["steps"] = val
                        break
            if "steps" in sc:
                sc["steps"] = self._postprocess_steps(sc["steps"], dropdown_map)
            if not sc.get("url"):
                sc["url"] = url
            result.append(sc)

        return result

    @classmethod
    def _extract_partial_scenarios(cls, text: str) -> list[dict]:
        """Витягує валідні JSON-об'єкти сценаріїв з частково обрізаного тексту."""
        text = cls._strip_thinking(text)
        text = cls._clean_json_text(text)
        results = []
        pos = 0
        while pos < len(text):
            start = text.find('{"name"', pos)
            if start == -1:
                start = text.find('{"action"', pos)
            if start == -1:
                break

            depth = 0
            in_str = False
            esc = False
            for i in range(start, len(text)):
                ch = text[i]
                if esc:
                    esc = False
                    continue
                if ch == '\\':
                    esc = True
                    continue
                if ch == '"':
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        candidate = text[start:i + 1]
                        try:
                            obj = json.loads(candidate)
                            if isinstance(obj, dict) and ("steps" in obj or "name" in obj):
                                results.append(obj)
                        except json.JSONDecodeError:
                            pass
                        pos = i + 1
                        break
            else:
                break
        return results

    @staticmethod
    def _build_dropdown_map(page_data: dict) -> dict[str, str]:
        """Будує карту: selector dropdown-елемента -> selector для hover."""
        mapping = {}
        for nav in page_data.get("navigation", []):
            if nav.get("dropdown") and nav.get("hoverFirst"):
                sel = nav["selector"]
                mapping[sel] = nav["hoverFirst"]
                text = nav.get("text", "")
                if text:
                    mapping[f'a:has-text("{text}")'] = nav["hoverFirst"]
                    mapping[f'a:text("{text}")'] = nav["hoverFirst"]
                    mapping[f'a.dropdown-item:text("{text}")'] = nav["hoverFirst"]
                    mapping[f'a.dropdown-item:has-text("{text}")'] = nav["hoverFirst"]
        return mapping

    _SELECTOR_ACTIONS = {
        "click", "type", "clear", "hover", "wait", "wait_visible",
        "wait_hidden", "select", "scroll", "assert_text",
        "assert_visible", "assert_not_visible", "assert_count", "assert_attribute",
    }
    _VALUE_ACTIONS = {
        "goto", "wait_url", "assert_url", "assert_title", "press", "pause", "screenshot",
    }

    @classmethod
    def _normalize_step(cls, step) -> dict:
        """Нормалізує крок з будь-якого формату до стандартного {action, selector, value}."""
        if isinstance(step, str):
            return cls._parse_string_step(step)
        if not isinstance(step, dict):
            return {"action": "unknown"}
        if "action" in step:
            return step

        for key, val in step.items():
            if key in cls._SELECTOR_ACTIONS:
                result = {"action": key, "selector": val}
                if "value" in step:
                    result["value"] = step["value"]
                return result
            if key in cls._VALUE_ACTIONS:
                return {"action": key, "value": val}
        return step

    @classmethod
    def _parse_string_step(cls, text: str) -> dict:
        """Парсить крок формату 'action(args)' у dict."""
        m = re.match(r"(\w+)\((.+)\)$", text.strip())
        if not m:
            return {"action": "unknown"}
        action = m.group(1)
        args_str = m.group(2)

        result = {"action": action}
        if action in cls._VALUE_ACTIONS:
            val = re.sub(r"^value=", "", args_str)
            result["value"] = val
        elif action in cls._SELECTOR_ACTIONS:
            parts = args_str.split(",", 1)
            result["selector"] = parts[0].strip()
            if len(parts) > 1:
                val = parts[1].strip()
                val = re.sub(r"^value=", "", val)
                result["value"] = val
        else:
            result["value"] = args_str
        return result

    @staticmethod
    def _postprocess_steps(steps: list[dict], dropdown_map: dict[str, str] | None = None) -> list[dict]:
        """Очищує кроки: нормалізація, auto-hover для dropdown, дедуплікація."""
        if not steps:
            return steps

        dropdown_map = dropdown_map or {}
        steps = [AITestGenerator._normalize_step(s) for s in steps]

        # Auto-assert: якщо click має value що виглядає як URL path, додати assert_url
        with_asserts = []
        for step in steps:
            action = step.get("action", "")
            value = str(step.get("value", "")).strip().strip('"')
            if action == "click" and value and value.startswith("/"):
                step_clean = {k: v for k, v in step.items() if k != "value" or not str(v).startswith("/")}
                step_clean.pop("value", None)
                with_asserts.append(step_clean)
                with_asserts.append({"action": "assert_url", "value": value})
            else:
                with_asserts.append(step)
        steps = with_asserts

        # Auto-hover: вставити hover перед click на dropdown-елемент
        expanded = []
        for step in steps:
            action = step.get("action", "")
            selector = step.get("selector", "")
            if action == "click" and selector in dropdown_map:
                hover_sel = dropdown_map[selector]
                need_hover = True
                if expanded:
                    prev = expanded[-1]
                    if prev.get("action") == "hover" and prev.get("selector") == hover_sel:
                        need_hover = False
                if need_hover:
                    expanded.append({"action": "hover", "selector": hover_sel})
            expanded.append(step)
        steps = expanded

        cleaned = []
        seen_signatures = set()

        for i, step in enumerate(steps):
            action = step.get("action", "")
            selector = step.get("selector", "")
            value = step.get("value", "")
            sig = f"{action}|{selector}|{value}"

            if cleaned and sig == f"{cleaned[-1].get('action')}|{cleaned[-1].get('selector', '')}|{cleaned[-1].get('value', '')}":
                continue

            if action == "assert_url" and cleaned:
                prev = cleaned[-1]
                if prev.get("action") == "wait_url" and prev.get("value", "").rstrip("$") == value.rstrip("$"):
                    cleaned[-1] = step
                    continue

            if action == "goto" and i > 0:
                first_goto = next((s for s in cleaned if s.get("action") == "goto"), None)
                if first_goto and first_goto.get("value") == value:
                    continue

            if action == "click" and cleaned:
                prev = cleaned[-1]
                if prev.get("action") == "click" and prev.get("selector") == selector:
                    continue

            if action in ("click", "type", "wait", "assert_text", "assert_visible",
                          "hover", "wait_visible", "wait_hidden") and not selector:
                continue
            if action in ("goto", "wait_url", "assert_url", "assert_title", "press") and not value:
                continue

            # Пропустити hover на елемент, який і так dropdown-toggle, але не потрібен для наступного click
            if action == "hover" and selector in dropdown_map.values():
                next_idx = i + 1
                if next_idx < len(steps):
                    next_step = steps[next_idx]
                    if next_step.get("action") != "click" or next_step.get("selector", "") not in dropdown_map:
                        continue

            if action.startswith("assert_") and sig in seen_signatures:
                continue

            cleaned.append(step)
            seen_signatures.add(sig)

        return cleaned

    @staticmethod
    def _clean_json_text(text: str) -> str:
        """Прибирає типові проблеми: коментарі, trailing commas, неповні ключі."""
        text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
        text = re.sub(r"/\*[\s\S]*?\*/", "", text)
        text = re.sub(r",\s*\"[^\"]*\"\s*[}\]]", lambda m: m.group()[-1], text)
        text = re.sub(r",\s*([}\]])", r"\1", text)
        return text.strip()

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """Видаляє блоки <think>...</think> та інші спецтокени моделей."""
        text = re.sub(r"<think>[\s\S]*?</think>", "", text)
        text = re.sub(r"<\|channel\|>[^\{]*", "", text)
        return text.strip()

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

        # Знайти JSON-об'єкт за допомогою балансу дужок
        result = cls._extract_balanced_json(cls._clean_json_text(text))
        if result is not None:
            return result

        result = cls._extract_balanced_json(text)
        if result is not None:
            return result

        # Останній шанс — спробувати відновити обрізаний JSON
        start = text.find("{")
        if start >= 0:
            repaired = cls._repair_truncated_json(text[start:])
            if repaired is not None:
                return repaired

        raise ValueError(
            f"Не вдалося розпарсити JSON з відповіді AI.\n"
            f"Сира відповідь моделі:\n---\n{text[:1000]}\n---"
        )

    @staticmethod
    def _extract_balanced_json(text: str) -> dict | None:
        """Знаходить збалансований JSON-об'єкт у тексті."""
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape = False

        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        cleaned = AITestGenerator._clean_json_text(candidate)
                        try:
                            return json.loads(cleaned)
                        except json.JSONDecodeError:
                            start = text.find("{", i + 1)
                            if start == -1:
                                return None
                            depth = 0

        # JSON обрізаний — спроба відновити
        if depth > 0 and start >= 0:
            return AITestGenerator._repair_truncated_json(text[start:])

        return None

    @staticmethod
    def _repair_truncated_json(text: str) -> dict | None:
        """Відновлює обрізаний JSON, закриваючи незавершені структури."""
        text = text.rstrip()

        # Видалити останній незакінчений елемент (обрізаний об'єкт в масиві)
        text = re.sub(r',\s*\{[^}]*$', '', text)
        # Видалити обрізане значення після останньої коми
        text = re.sub(r',\s*"[^"]*$', '', text)

        # Закрити відкриті дужки
        opens = 0
        opens_sq = 0
        in_str = False
        esc = False
        for ch in text:
            if esc:
                esc = False
                continue
            if ch == '\\':
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == '{':
                opens += 1
            elif ch == '}':
                opens -= 1
            elif ch == '[':
                opens_sq += 1
            elif ch == ']':
                opens_sq -= 1

        text += ']' * max(0, opens_sq) + '}' * max(0, opens)

        cleaned = AITestGenerator._clean_json_text(text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None
