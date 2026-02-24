# AI Testing Framework

Простий фреймворк для автоматизованого тестування веб-сайтів з AI-підтримкою.
Використовує **Playwright** для керування браузером та **LM Studio** для генерації тестових сценаріїв.

## Встановлення

```bash
pip install -r requirements.txt
playwright install chromium
```

## Налаштування

1. Запустіть **LM Studio** та увімкніть Local Server.
2. Перевірте `config.yaml` — вкажіть URL сервера та назву моделі:

```yaml
lm_studio:
  url: "http://localhost:1234/v1"
  model: "zai-org/glm-4.6v-flash"

browser:
  headless: false
  timeout: 30000
```

## Використання

### Генерація тесту через AI

```bash
python -m ai_testing generate "Перевірити форму логіну" --url "https://example.com" --name "login_test"
```

### Запуск тесту

```bash
python -m ai_testing run login_test
```

Запуск без вікна браузера:

```bash
python -m ai_testing run login_test --headless
```

### Перегляд доступних тестів

```bash
python -m ai_testing list
```

### Створення власного тесту вручну

Створіть JSON файл у папці `scenarios/`:

```json
{
  "name": "My Test",
  "url": "https://example.com",
  "steps": [
    { "action": "type", "selector": "#email", "value": "test@example.com" },
    { "action": "click", "selector": "button[type='submit']" },
    { "action": "wait", "selector": ".success-message" }
  ]
}
```

### Доступні дії

| Дія     | Опис                    | Поля                       |
|---------|-------------------------|----------------------------|
| `goto`  | Відкрити URL            | `action`, `value` (URL)    |
| `click` | Клікнути на елемент     | `action`, `selector`       |
| `type`  | Ввести текст            | `action`, `selector`, `value` |
| `wait`  | Дочекатися елемента     | `action`, `selector`       |

## Структура проєкту

```
ai_testing/
  ai_client.py     — генерація тестів через LM Studio
  browser.py       — виконання дій у Playwright
  test_runner.py   — координація запуску тестів
  cli.py           — CLI інтерфейс
scenarios/         — JSON файли зі сценаріями
results/           — JSON результати тестів
config.yaml        — налаштування
```
