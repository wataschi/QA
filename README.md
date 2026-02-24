# AI Testing Framework

Фреймворк для автоматизованого тестування веб-сайтів з AI-підтримкою.
Використовує **Playwright** для керування браузером та **LM Studio** для генерації тестових сценаріїв
за стандартами якості ISTQB.

## Встановлення

```bash
pip install -r requirements.txt
playwright install chromium
```

## Налаштування

1. Запустіть **LM Studio** та увімкніть Local Server.
2. Перевірте `config.yaml`:

```yaml
lm_studio:
  url: "http://localhost:1234/v1"
  model: "zai-org/glm-4.6v-flash"

browser:
  headless: false
  timeout: 30000
```

## Використання

### Інтерактивний режим

```bash
python -m ai_testing
```

### Генерація тесту через AI

```bash
python -m ai_testing generate "Test navigation links" --url "https://example.com" --name "nav_test"
```

### Генерація тестів за специфікацією (ТЗ)

Створіть файл специфікації (`specs/login.md`) з описом вимог, потім:

```bash
python -m ai_testing from-spec --spec specs/login.md --url "https://example.com"
```

AI згенерує набір тест-кейсів з пріоритетами, покриваючи:
- Позитивні сценарії (happy path)
- Негативні сценарії (невалідні дані)
- Граничні значення (boundary values)
- Валідацію полів
- Навігацію

### Запуск тесту

```bash
python -m ai_testing run nav_test
python -m ai_testing run nav_test --headless
```

### Перегляд тестів

```bash
python -m ai_testing list
```

### Створення тесту вручну

Створіть JSON файл у `scenarios/`:

```json
{
  "name": "My Test",
  "url": "https://example.com",
  "steps": [
    { "action": "goto", "value": "https://example.com/login" },
    { "action": "type", "selector": "#email", "value": "test@example.com" },
    { "action": "type", "selector": "#password", "value": "secret123" },
    { "action": "click", "selector": "button[type='submit']" },
    { "action": "assert_url", "value": "/dashboard" },
    { "action": "assert_visible", "selector": ".welcome-message" }
  ]
}
```

### Доступні дії

| Дія | Опис | Поля |
|-----|------|------|
| `goto` | Відкрити URL | `value` (URL) |
| `click` | Клікнути | `selector` |
| `type` | Ввести текст | `selector`, `value` |
| `clear` | Очистити поле | `selector` |
| `hover` | Навести курсор | `selector` |
| `select` | Вибрати опцію | `selector`, `value` |
| `press` | Натиснути клавішу | `value` (key) |
| `scroll` | Прокрутити | `selector` або `value` (px) |
| `pause` | Пауза | `value` (ms) |
| `wait` | Чекати елемент | `selector` |
| `wait_visible` | Чекати видимість | `selector` |
| `wait_hidden` | Чекати зникнення | `selector` |
| `wait_url` | Чекати URL | `value` (підрядок) |
| `assert_text` | Перевірити текст | `selector`, `value` |
| `assert_visible` | Перевірити видимість | `selector` |
| `assert_not_visible` | Перевірити невидимість | `selector` |
| `assert_url` | Перевірити URL | `value` (підрядок) |
| `assert_title` | Перевірити заголовок | `value` (підрядок) |
| `assert_count` | Перевірити кількість | `selector`, `value` (N) |
| `assert_attribute` | Перевірити атрибут | `selector`, `value`, `attribute` |
| `screenshot` | Зробити скріншот | `value` (filename) |

## Структура проєкту

```
ai_testing/
  ai_client.py     — генерація тестів через LM Studio (QA prompts)
  browser.py       — PageAnalyzer + TestBrowser (Playwright)
  test_runner.py   — координація запуску тестів
  cli.py           — CLI інтерфейс (generate, from-spec, run, list)
  interactive.py   — інтерактивне консольне меню (rich)
scenarios/         — JSON файли зі сценаріями
results/           — JSON результати тестів
specs/             — специфікації/ТЗ для генерації тестів
config.yaml        — налаштування
```
