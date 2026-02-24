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


def echo(msg: str = ""):
    print(msg, flush=True)


@click.group()
def cli():
    """AI Testing Framework"""


def _scan_page(url: str):
    """Сканує сторінку та повертає (page_structure, page_data) або (None, None)."""
    echo(f"Сканування сторiнки: {url}")
    try:
        analyzer = PageAnalyzer(headless=True)
        page_data = analyzer.analyze(url)
        page_structure = analyzer.format_for_ai(page_data)
        echo(f"Знайдено {analyzer.element_count(page_data)} iнтерактивних елементiв")
        return page_structure, page_data
    except Exception as exc:
        echo(f"Не вдалося просканувати сторiнку: {exc}")
        echo("Генерацiя без даних сторiнки...")
        return None, None


def _save_scenario(test_data: dict, name: str, url: str) -> Path:
    """Зберігає сценарій у файл, додаючи goto якщо потрібно."""
    if "url" not in test_data:
        test_data["url"] = url
    if "name" not in test_data:
        test_data["name"] = name

    steps = test_data.get("steps", [])
    if steps and steps[0].get("action") != "goto":
        steps.insert(0, {"action": "goto", "value": url})
        test_data["steps"] = steps

    scenarios_dir = Path("scenarios")
    scenarios_dir.mkdir(exist_ok=True)
    output_path = scenarios_dir / f"{name}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(test_data, f, indent=2, ensure_ascii=False)
    return output_path


def _get_ai(cfg: dict = None) -> AITestGenerator:
    if cfg is None:
        cfg = _load_config()
    lm = cfg.get("lm_studio", {})
    return AITestGenerator(
        base_url=lm.get("url", "http://localhost:1234/v1"),
        model=lm.get("model", "local-model"),
    )


@cli.command()
@click.argument("description")
@click.option("--url", required=True, help="URL")
@click.option("--name", required=True, help="Scenario name")
@click.option("--no-scan", is_flag=True, default=False, help="Skip page scan")
def generate(description: str, url: str, name: str, no_scan: bool):
    """Generate test scenario via AI (LM Studio)."""
    ai = _get_ai()

    page_structure, page_data = (None, None) if no_scan else _scan_page(url)

    echo(f"Генерацiя тесту: {description}")
    echo("Очiкую вiдповiдь вiд AI...")

    try:
        test_data = ai.generate_test(description, url, page_structure,
                                     page_data=page_data if page_structure else None)
    except Exception as exc:
        echo(f"Помилка AI: {exc}")
        raise SystemExit(1)

    output_path = _save_scenario(test_data, name, url)
    echo(f"Тест збережено: {output_path}")
    echo(f"Крокiв: {len(test_data.get('steps', []))}")


@cli.command("from-spec")
@click.option("--spec", required=True, type=click.Path(exists=True), help="Path to spec file")
@click.option("--url", required=True, help="URL")
@click.option("--no-scan", is_flag=True, default=False, help="Skip page scan")
def generate_from_spec(spec: str, url: str, no_scan: bool):
    """Generate test scenarios from a specification document."""
    spec_path = Path(spec)
    spec_text = spec_path.read_text(encoding="utf-8")
    echo(f"Специфiкацiя: {spec_path.name} ({len(spec_text)} символiв)")

    ai = _get_ai()
    page_structure, page_data = (None, None) if no_scan else _scan_page(url)

    echo("Генерацiя тест-кейсiв за специфiкацiєю...")
    echo("Очiкую вiдповiдь вiд AI...")

    try:
        scenarios = ai.generate_from_spec(
            spec_text, url, page_structure,
            page_data=page_data if page_structure else None,
        )
    except Exception as exc:
        echo(f"Помилка AI: {exc}")
        raise SystemExit(1)

    if not scenarios:
        echo("AI не згенерував жодного сценарiю.")
        raise SystemExit(1)

    echo(f"\nЗгенеровано {len(scenarios)} сценарiїв:")
    for sc in scenarios:
        name = sc.get("name", "unnamed")
        desc = sc.get("description", "")
        priority = sc.get("priority", "medium")
        output_path = _save_scenario(sc, name, url)
        steps_count = len(sc.get("steps", []))
        echo(f"  [{priority}] {name} — {desc} ({steps_count} крокiв) -> {output_path}")


@cli.command("run")
@click.argument("scenario_name")
@click.option("--headless", is_flag=True, default=False, help="Run headless")
def run_test(scenario_name: str, headless: bool):
    """Run test scenario."""
    cfg = _load_config()
    browser_cfg = cfg.get("browser", {})

    runner = TestRunner(
        headless=headless or browser_cfg.get("headless", False),
        timeout=browser_cfg.get("timeout", 30_000),
    )

    echo(f"Запуск сценарiю: {scenario_name}")

    try:
        result = runner.run_scenario(scenario_name)
    except FileNotFoundError as exc:
        echo(f"Помилка: {exc}")
        raise SystemExit(1)

    status = result["status"]
    duration = result["duration_seconds"]
    steps = result["steps"]

    if status == "success":
        echo(f"PASSED ({duration}s, {len(steps)} крокiв)")
    else:
        echo(f"FAILED ({duration}s)")
        for s in steps:
            if s["status"] == "error":
                echo(f"  Крок {s['step']}: {s['error']}")


@cli.command("list")
def list_scenarios():
    """List all test scenarios."""
    runner = TestRunner()
    scenarios = runner.list_scenarios()

    if not scenarios:
        echo("Сценарiїв не знайдено.")
        return

    echo(f"Знайдено {len(scenarios)} сценарiїв:\n")
    for name in scenarios:
        data = runner.load_scenario(name)
        steps_count = len(data.get("steps", []))
        url = data.get("url", "-")
        echo(f"  {name}  ({steps_count} крокiв, {url})")


if __name__ == "__main__":
    cli()
