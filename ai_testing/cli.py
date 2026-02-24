import json
from pathlib import Path

import click
import yaml

from .ai_client import AITestGenerator
from .browser import PageAnalyzer
from .test_runner import TestRunner


def _load_config() -> dict:
    config_path = Path("config.yaml")
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


@click.group()
def cli():
    """AI Testing Framework — тестування сайтів з AI-підтримкою."""


@cli.command()
@click.argument("description")
@click.option("--url", required=True, help="URL сайту для тестування.")
@click.option("--name", required=True, help="Ім'я сценарію (без .json).")
@click.option("--no-scan", is_flag=True, default=False, help="Не сканувати сторінку (генерувати наосліп).")
def generate(description: str, url: str, name: str, no_scan: bool):
    """Генерує тестовий сценарій через AI (LM Studio)."""
    cfg = _load_config()
    lm = cfg.get("lm_studio", {})

    ai = AITestGenerator(
        base_url=lm.get("url", "http://localhost:1234/v1"),
        model=lm.get("model", "local-model"),
    )

    page_structure = None
    if not no_scan:
        click.echo(f"Сканування сторінки: {url}")
        try:
            analyzer = PageAnalyzer(headless=True)
            elements = analyzer.analyze(url)
            page_structure = analyzer.format_for_ai(elements)
            click.echo(f"Знайдено {len(elements)} інтерактивних елементів")
        except Exception as exc:
            click.echo(f"Не вдалося просканувати сторінку: {exc}", err=True)
            click.echo("Генерація без даних сторінки...")

    click.echo(f"Генерація тесту: {description}")
    click.echo("Очікую відповідь від AI...")

    try:
        test_data = ai.generate_test(description, url, page_structure)
    except Exception as exc:
        click.echo(f"Помилка AI: {exc}", err=True)
        raise SystemExit(1)

    if "url" not in test_data:
        test_data["url"] = url
    if "name" not in test_data:
        test_data["name"] = name

    scenarios_dir = Path("scenarios")
    scenarios_dir.mkdir(exist_ok=True)

    output_path = scenarios_dir / f"{name}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(test_data, f, indent=2, ensure_ascii=False)

    click.echo(f"Тест збережено: {output_path}")
    click.echo(f"Кроків: {len(test_data.get('steps', []))}")


@cli.command("run")
@click.argument("scenario_name")
@click.option("--headless", is_flag=True, default=False, help="Запуск без вікна браузера.")
def run_test(scenario_name: str, headless: bool):
    """Запускає тестовий сценарій."""
    cfg = _load_config()
    browser_cfg = cfg.get("browser", {})

    runner = TestRunner(
        headless=headless or browser_cfg.get("headless", False),
        timeout=browser_cfg.get("timeout", 30_000),
    )

    click.echo(f"Запуск сценарію: {scenario_name}")

    try:
        result = runner.run_scenario(scenario_name)
    except FileNotFoundError as exc:
        click.echo(f"Помилка: {exc}", err=True)
        raise SystemExit(1)

    status = result["status"]
    duration = result["duration_seconds"]
    steps = result["steps"]

    if status == "success":
        click.echo(click.style(f"PASSED", fg="green") + f" ({duration}s, {len(steps)} кроків)")
    else:
        click.echo(click.style(f"FAILED", fg="red") + f" ({duration}s)")
        for s in steps:
            if s["status"] == "error":
                click.echo(f"  Крок {s['step']}: {s['error']}")


@cli.command("list")
def list_scenarios():
    """Показує всі доступні тестові сценарії."""
    runner = TestRunner()
    scenarios = runner.list_scenarios()

    if not scenarios:
        click.echo("Сценаріїв не знайдено. Створіть їх командою 'generate' або додайте JSON у папку scenarios/.")
        return

    click.echo(f"Знайдено {len(scenarios)} сценаріїв:\n")
    for name in scenarios:
        data = runner.load_scenario(name)
        steps_count = len(data.get("steps", []))
        url = data.get("url", "—")
        click.echo(f"  {name}  ({steps_count} кроків, {url})")


if __name__ == "__main__":
    cli()
