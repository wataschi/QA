import json
import time
from playwright.sync_api import sync_playwright


class PageAnalyzer:
    """Збирає структуру інтерактивних елементів зі сторінки."""

    JS_EXTRACT = """
    () => {
        const selectors = [];
        const tags = ['a', 'button', 'input', 'select', 'textarea', 'form'];
        const seen = new Set();

        for (const tag of tags) {
            for (const el of document.querySelectorAll(tag)) {
                const id = el.id ? `#${el.id}` : null;
                const name = el.name ? `[name="${el.name}"]` : null;
                const type = el.type || null;
                const text = el.innerText?.trim().slice(0, 60) || null;
                const href = el.href || null;
                const placeholder = el.placeholder || null;
                const classes = el.className
                    ? '.' + el.className.trim().split(/\\s+/).slice(0, 3).join('.')
                    : null;

                let bestSelector = id
                    || (el.name ? `${tag}${name}` : null)
                    || (classes && classes !== '.' ? `${tag}${classes}` : null)
                    || tag;

                const key = `${tag}|${bestSelector}`;
                if (seen.has(key)) continue;
                seen.add(key);

                selectors.push({
                    tag,
                    selector: bestSelector,
                    type: type,
                    text: text || null,
                    placeholder: placeholder,
                    href: href,
                });
            }
        }
        return selectors;
    }
    """

    def __init__(self, headless: bool = True, timeout: int = 15_000):
        self.headless = headless
        self.timeout = timeout

    def analyze(self, url: str) -> list[dict]:
        """Відкриває сторінку та повертає список інтерактивних елементів."""
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.headless)
            page = browser.new_page()
            page.set_default_timeout(self.timeout)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            elements = page.evaluate(self.JS_EXTRACT)
            browser.close()
        return elements

    @staticmethod
    def format_for_ai(elements: list[dict]) -> str:
        """Форматує елементи у читабельний текст для AI."""
        if not elements:
            return "No interactive elements found."

        lines = []
        for el in elements:
            parts = [f"{el['tag']} selector=\"{el['selector']}\""]
            if el.get("type"):
                parts.append(f"type={el['type']}")
            if el.get("text"):
                parts.append(f"text=\"{el['text']}\"")
            if el.get("placeholder"):
                parts.append(f"placeholder=\"{el['placeholder']}\"")
            if el.get("href"):
                parts.append(f"href=\"{el['href']}\"")
            lines.append("  " + " | ".join(parts))

        return "\n".join(lines)


class TestBrowser:
    """Виконавець тестових кроків через Playwright."""

    SUPPORTED_ACTIONS = ("goto", "click", "type", "wait")

    def __init__(self, headless: bool = False, timeout: int = 30_000):
        self.headless = headless
        self.timeout = timeout

    def run_test(self, test_data: dict) -> dict:
        """Виконує весь тестовий сценарій і повертає результат."""
        steps_results = []
        overall_status = "success"
        start = time.time()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.headless)
            page = browser.new_page()
            page.set_default_timeout(self.timeout)

            url = test_data.get("url")
            if url:
                page.goto(url)

            for idx, step in enumerate(test_data.get("steps", []), start=1):
                step_start = time.time()
                try:
                    self._execute_step(page, step)
                    steps_results.append({
                        "step": idx,
                        "action": step.get("action"),
                        "status": "ok",
                        "time": round(time.time() - step_start, 3),
                    })
                except Exception as exc:
                    overall_status = "failed"
                    steps_results.append({
                        "step": idx,
                        "action": step.get("action"),
                        "status": "error",
                        "error": str(exc),
                        "time": round(time.time() - step_start, 3),
                    })
                    break

            browser.close()

        return {
            "status": overall_status,
            "duration_seconds": round(time.time() - start, 3),
            "steps": steps_results,
        }

    def _execute_step(self, page, step: dict):
        """Виконує один крок тесту."""
        action = step.get("action", "")
        selector = step.get("selector", "")
        value = step.get("value", "")

        if action == "goto":
            page.goto(value)
        elif action == "click":
            page.click(selector)
        elif action == "type":
            page.fill(selector, value)
        elif action == "wait":
            page.wait_for_selector(selector)
        else:
            raise ValueError(f"Невідома дія: {action}")
