import time
from pathlib import Path
from playwright.sync_api import sync_playwright


class PageAnalyzer:
    """Збирає структуру інтерактивних елементів зі сторінки."""

    JS_EXTRACT = """
    () => {
        const result = {
            title: document.title,
            url: location.href,
            headings: [],
            interactive: [],
            images: [],
            navigation: [],
        };

        // Заголовки
        for (const h of document.querySelectorAll('h1, h2, h3')) {
            const text = h.innerText?.trim().slice(0, 80);
            if (!text) continue;
            const id = h.id ? `#${h.id}` : null;
            const cls = h.className
                ? '.' + h.className.trim().split(/\\s+/).slice(0, 2).join('.')
                : null;
            result.headings.push({
                tag: h.tagName.toLowerCase(),
                selector: id || (cls && cls !== '.' ? `${h.tagName.toLowerCase()}${cls}` : h.tagName.toLowerCase()),
                text,
            });
        }

        // Навігація (nav > a) — з контекстом видимості та dropdown
        for (const nav of document.querySelectorAll('nav')) {
            for (const a of nav.querySelectorAll('a')) {
                const text = a.innerText?.trim().slice(0, 40);
                if (!text) continue;
                const id = a.id ? `#${a.id}` : null;
                const textSel = `a:has-text("${text.slice(0, 30)}")`;
                const isVisible = a.offsetParent !== null && getComputedStyle(a).display !== 'none';
                const dropdownMenu = a.closest('.dropdown-menu, .dropdown-wrapper, .submenu, [class*=dropdown]:not(nav):not(li)');
                const inDropdown = !!dropdownMenu && a.classList.contains('dropdown-item');
                let toggleSel = null;
                if (inDropdown) {
                    let wrapper = dropdownMenu.parentElement;
                    for (let up = 0; up < 3 && wrapper; up++) {
                        const toggle = Array.from(wrapper.children).find(
                            ch => (ch.tagName === 'A' || ch.tagName === 'BUTTON')
                                  && ch !== dropdownMenu
                                  && !dropdownMenu.contains(ch)
                                  && ch.offsetParent !== null
                        );
                        if (toggle) {
                            const tText = toggle.innerText?.trim().slice(0, 25);
                            toggleSel = toggle.id
                                ? `#${toggle.id}`
                                : (tText ? `a:has-text("${tText}")` : null);
                            break;
                        }
                        wrapper = wrapper.parentElement;
                    }
                }
                const isExternal = a.href && !a.href.startsWith(location.origin);
                result.navigation.push({
                    selector: id || textSel,
                    text,
                    href: a.href || null,
                    visible: isVisible,
                    dropdown: inDropdown,
                    hoverFirst: toggleSel,
                    external: isExternal,
                });
            }
        }

        // Всі внутрішні маршрути (унікальні path з лінків)
        const origin = location.origin;
        const routeSet = new Set();
        result.routes = [];
        for (const a of document.querySelectorAll('a[href]')) {
            const href = a.href;
            if (!href || !href.startsWith(origin)) continue;
            const path = new URL(href).pathname;
            if (routeSet.has(path)) continue;
            routeSet.add(path);
            const text = a.innerText?.trim().slice(0, 50) || null;
            const id = a.id ? `#${a.id}` : null;
            const cls = a.className && typeof a.className === 'string'
                ? '.' + a.className.trim().split(/\\s+/).slice(0, 3).join('.')
                : null;
            result.routes.push({
                path,
                full_url: href,
                link_text: text,
                selector: id
                    || (cls && cls !== '.' ? `a${cls}` : null)
                    || (text ? `a:has-text("${text.slice(0, 30)}")` : null)
                    || 'a',
            });
        }
        result.routes.sort((a, b) => a.path.localeCompare(b.path));

        // Інтерактивні елементи
        const tags = ['button', 'input', 'select', 'textarea', 'a[href]'];
        const seen = new Set();

        for (const sel of tags) {
            for (const el of document.querySelectorAll(sel)) {
                const tag = el.tagName.toLowerCase();
                const id = el.id ? `#${el.id}` : null;
                const name = el.name ? `[name="${el.name}"]` : null;
                const type = el.type || null;
                const text = el.innerText?.trim().slice(0, 60) || null;
                const href = el.href || null;
                const placeholder = el.placeholder || null;
                const ariaLabel = el.getAttribute('aria-label') || null;
                const required = el.required || false;
                const disabled = el.disabled || false;
                const classes = el.className && typeof el.className === 'string'
                    ? '.' + el.className.trim().split(/\\s+/).slice(0, 3).join('.')
                    : null;

                let bestSelector = id
                    || (el.name ? `${tag}${name}` : null)
                    || (classes && classes !== '.' ? `${tag}${classes}` : null)
                    || tag;

                const key = `${tag}|${bestSelector}`;
                if (seen.has(key)) continue;
                seen.add(key);

                result.interactive.push({
                    tag,
                    selector: bestSelector,
                    type,
                    text: text || null,
                    placeholder,
                    ariaLabel,
                    href,
                    required,
                    disabled,
                });
            }
        }

        // Зображення (перші 10)
        let imgCount = 0;
        for (const img of document.querySelectorAll('img')) {
            if (imgCount >= 10) break;
            const alt = img.alt || null;
            const src = img.src || null;
            if (!src) continue;
            const id = img.id ? `#${img.id}` : null;
            const cls = img.className
                ? '.' + img.className.trim().split(/\\s+/).slice(0, 2).join('.')
                : null;
            result.images.push({
                selector: id || (cls && cls !== '.' ? `img${cls}` : 'img'),
                alt,
                src: src.slice(0, 120),
            });
            imgCount++;
        }

        return result;
    }
    """

    def __init__(self, headless: bool = True, timeout: int = 15_000):
        self.headless = headless
        self.timeout = timeout

    def analyze(self, url: str) -> dict:
        """Відкриває сторінку та повертає структурований аналіз."""
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.headless)
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.set_default_timeout(self.timeout)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            data = page.evaluate(self.JS_EXTRACT)
            browser.close()
        return data

    @staticmethod
    def format_for_ai(data: dict, max_interactive: int = 15) -> str:
        """Форматує аналіз сторінки у компактний текст для AI."""
        lines = [f"URL: {data.get('url', '?')}"]

        nav = data.get("navigation", [])
        internal_nav = [n for n in nav if not n.get("external")]
        if internal_nav:
            lines.append("\nNav:")
            for n in internal_nav[:10]:
                href = n.get("href", "")
                path = href.replace(data.get("url", "").rstrip("/"), "") or "/"
                line = f"  {n['selector']} -> {path}"
                if n.get("dropdown") and n.get("hoverFirst"):
                    line += f" [hover {n['hoverFirst']} first]"
                lines.append(line)

        headings = data.get("headings", [])
        if headings:
            lines.append("\nH:")
            for h in headings[:4]:
                lines.append(f"  {h['selector']} \"{h['text'][:30]}\"")

        interactive = data.get("interactive", [])
        non_links = [el for el in interactive if el["tag"] != "a"]
        if non_links:
            lines.append("\nEl:")
            for el in non_links[:max_interactive]:
                parts = [f"  {el['tag']} {el['selector']}"]
                if el.get("type") and el["type"] != "submit":
                    parts.append(f"type={el['type']}")
                if el.get("text"):
                    parts.append(f"\"{el['text'][:20]}\"")
                elif el.get("placeholder"):
                    parts.append(f"ph=\"{el['placeholder'][:20]}\"")
                lines.append(" ".join(parts))

        return "\n".join(lines)

    @staticmethod
    def element_count(data: dict) -> int:
        return len(data.get("interactive", []))


class TestBrowser:
    """Виконавець тестових кроків через Playwright."""

    def __init__(self, headless: bool = False, timeout: int = 30_000,
                 screenshots_dir: str = "screenshots"):
        self.headless = headless
        self.timeout = timeout
        self.screenshots_dir = Path(screenshots_dir)

    def run_test(self, test_data: dict) -> dict:
        """Виконує весь тестовий сценарій і повертає результат."""
        steps_results = []
        overall_status = "success"
        start = time.time()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.headless)
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.set_default_timeout(self.timeout)

            url = test_data.get("url")
            if url:
                page.goto(url)

            for idx, step in enumerate(test_data.get("steps", []), start=1):
                step_start = time.time()
                try:
                    info = self._execute_step(page, step)
                    entry = {
                        "step": idx,
                        "action": step.get("action"),
                        "status": "ok",
                        "time": round(time.time() - step_start, 3),
                    }
                    if info:
                        entry["info"] = info
                    steps_results.append(entry)
                except Exception as exc:
                    overall_status = "failed"
                    screenshot_path = self._take_error_screenshot(page, test_data.get("name", "test"), idx)
                    steps_results.append({
                        "step": idx,
                        "action": step.get("action"),
                        "status": "error",
                        "error": str(exc),
                        "screenshot": screenshot_path,
                        "time": round(time.time() - step_start, 3),
                    })
                    break

            browser.close()

        return {
            "status": overall_status,
            "duration_seconds": round(time.time() - start, 3),
            "steps": steps_results,
        }

    def _take_error_screenshot(self, page, test_name: str, step: int) -> str | None:
        try:
            self.screenshots_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            path = self.screenshots_dir / f"{test_name}_step{step}_{ts}.png"
            page.screenshot(path=str(path), full_page=False)
            return str(path)
        except Exception:
            return None

    def _execute_step(self, page, step: dict) -> str | None:
        """Виконує один крок тесту. Повертає додаткову інформацію або None."""
        action = step.get("action", "")
        selector = step.get("selector", "")
        value = step.get("value", "")
        timeout = step.get("timeout", None)

        if action == "goto":
            page.goto(value, wait_until="domcontentloaded")

        elif action == "click":
            page.click(selector, timeout=timeout)

        elif action == "type":
            page.fill(selector, value, timeout=timeout)

        elif action == "clear":
            page.fill(selector, "", timeout=timeout)

        elif action == "wait":
            page.wait_for_selector(selector, timeout=timeout or self.timeout)

        elif action == "wait_hidden":
            page.wait_for_selector(selector, state="hidden", timeout=timeout or self.timeout)

        elif action == "wait_visible":
            page.wait_for_selector(selector, state="visible", timeout=timeout or self.timeout)

        elif action == "wait_url":
            import re as _re
            check = value.rstrip("$")
            if check in page.url:
                return f"url already matches: '{check}'"
            pattern = value if "*" in value else f"**{check}*"
            page.wait_for_url(pattern, timeout=timeout or self.timeout)

        elif action == "hover":
            page.hover(selector, timeout=timeout)

        elif action == "select":
            page.select_option(selector, value, timeout=timeout)

        elif action == "scroll":
            if selector:
                page.locator(selector).scroll_into_view_if_needed()
            else:
                amount = int(value) if value else 500
                page.mouse.wheel(0, amount)

        elif action == "screenshot":
            self.screenshots_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            fname = value or f"screenshot_{ts}.png"
            path = self.screenshots_dir / fname
            page.screenshot(path=str(path), full_page=step.get("full_page", False))
            return f"saved: {path}"

        elif action == "assert_text":
            element = page.locator(selector)
            actual = element.inner_text(timeout=timeout or 5000)
            if value not in actual:
                raise AssertionError(
                    f"Очікувано текст '{value}' у '{selector}', "
                    f"отримано: '{actual[:120]}'"
                )
            return f"text ok: '{value}' found"

        elif action == "assert_visible":
            visible = page.locator(selector).is_visible(timeout=timeout or 5000)
            if not visible:
                raise AssertionError(f"Елемент '{selector}' не видимий")
            return "visible: ok"

        elif action == "assert_not_visible":
            visible = page.locator(selector).is_visible(timeout=timeout or 3000)
            if visible:
                raise AssertionError(f"Елемент '{selector}' видимий, але не мав бути")
            return "not visible: ok"

        elif action == "assert_url":
            current_url = page.url
            check = value.rstrip("$")
            if check not in current_url:
                raise AssertionError(
                    f"Очікувано URL що містить '{check}', "
                    f"поточний: '{current_url}'"
                )
            return f"url ok: '{check}' in '{current_url}'"

        elif action == "assert_title":
            title = page.title()
            if value not in title:
                raise AssertionError(
                    f"Очікувано title що містить '{value}', "
                    f"отримано: '{title}'"
                )
            return f"title ok: '{title}'"

        elif action == "assert_count":
            count = page.locator(selector).count()
            expected = int(value)
            if count != expected:
                raise AssertionError(
                    f"Очікувано {expected} елементів '{selector}', знайдено: {count}"
                )
            return f"count ok: {count}"

        elif action == "assert_attribute":
            attr_name = step.get("attribute", "")
            element = page.locator(selector)
            actual = element.get_attribute(attr_name, timeout=timeout or 5000)
            if value not in (actual or ""):
                raise AssertionError(
                    f"Атрибут '{attr_name}' елемента '{selector}': "
                    f"очікувано '{value}', отримано: '{actual}'"
                )
            return f"attr ok: {attr_name}='{actual}'"

        elif action == "press":
            page.keyboard.press(value)

        elif action == "pause":
            ms = int(value) if value else 1000
            page.wait_for_timeout(ms)

        else:
            raise ValueError(f"Невідома дія: {action}")

        return None
