import json
import sys
from pathlib import Path

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich import box

from .ai_client import AITestGenerator
from .browser import PageAnalyzer
from .test_runner import TestRunner

console = Console()


def _load_config() -> dict:
    config_path = Path("config.yaml")
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _get_runner(cfg: dict) -> TestRunner:
    browser_cfg = cfg.get("browser", {})
    return TestRunner(
        headless=browser_cfg.get("headless", False),
        timeout=browser_cfg.get("timeout", 30_000),
    )


def _get_ai(cfg: dict) -> AITestGenerator:
    lm = cfg.get("lm_studio", {})
    return AITestGenerator(
        base_url=lm.get("url", "http://localhost:1234/v1"),
        model=lm.get("model", "local-model"),
    )


def show_banner():
    banner = Text()
    banner.append("AI Testing Framework\n", style="bold cyan")
    banner.append("Тестування сайтів з AI-підтримкою", style="dim")
    console.print(Panel(banner, box=box.DOUBLE, border_style="cyan", padding=(1, 2)))


def show_menu():
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold yellow", width=4)
    table.add_column()
    table.add_row("1.", "Згенерувати тест через AI")
    table.add_row("2.", "Запустити тест")
    table.add_row("3.", "Запустити всі тести")
    table.add_row("4.", "Переглянути сценарії")
    table.add_row("5.", "Переглянути результати")
    table.add_row("6.", "Переглянути деталі сценарію")
    table.add_row("0.", "Вихід")
    console.print()
    console.print(Panel(table, title="Меню", border_style="blue", box=box.ROUNDED))


def action_generate(cfg: dict):
    console.print("\n[bold cyan]--- Генерація тесту ---[/]")
    url = Prompt.ask("[yellow]URL сайту[/]")
    description = Prompt.ask("[yellow]Опис тесту[/]")
    name = Prompt.ask("[yellow]Назва сценарію[/]")
    scan = Confirm.ask("[yellow]Сканувати сторінку для точних селекторів?[/]", default=True)

    ai = _get_ai(cfg)
    page_structure = None

    if scan:
        with console.status("Сканування сторінки..."):
            try:
                analyzer = PageAnalyzer(headless=True)
                elements = analyzer.analyze(url)
                page_structure = analyzer.format_for_ai(elements)
                console.print(f"  Знайдено [green]{len(elements)}[/] інтерактивних елементів")
            except Exception as exc:
                console.print(f"  [red]Не вдалося просканувати:[/] {exc}")
                console.print("  Генерація без даних сторінки...")

    with console.status("Очікую відповідь від AI..."):
        try:
            test_data = ai.generate_test(description, url, page_structure)
        except Exception as exc:
            console.print(f"[red]Помилка AI:[/] {exc}")
            return

    if "url" not in test_data:
        test_data["url"] = url
    if "name" not in test_data:
        test_data["name"] = name

    scenarios_dir = Path("scenarios")
    scenarios_dir.mkdir(exist_ok=True)
    output_path = scenarios_dir / f"{name}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(test_data, f, indent=2, ensure_ascii=False)

    console.print(f"\n[green]Тест збережено:[/] {output_path}")
    console.print(f"Кроків: [cyan]{len(test_data.get('steps', []))}[/]")

    _print_steps_table(test_data.get("steps", []))


def action_run(cfg: dict):
    runner = _get_runner(cfg)
    scenarios = runner.list_scenarios()

    if not scenarios:
        console.print("[yellow]Сценаріїв не знайдено.[/]")
        return

    console.print("\n[bold cyan]--- Запуск тесту ---[/]")
    _print_scenarios_list(runner, scenarios)

    name = _pick_scenario(scenarios)
    headless = Confirm.ask("[yellow]Запуск у фоновому режимі (headless)?[/]", default=False)

    if headless:
        runner.headless = True

    with console.status(f"Запуск: {name}..."):
        try:
            result = runner.run_scenario(name)
        except FileNotFoundError as exc:
            console.print(f"[red]Помилка:[/] {exc}")
            return

    _print_result(name, result)


def action_run_all(cfg: dict):
    runner = _get_runner(cfg)
    scenarios = runner.list_scenarios()

    if not scenarios:
        console.print("[yellow]Сценаріїв не знайдено.[/]")
        return

    console.print(f"\n[bold cyan]--- Запуск усіх тестів ({len(scenarios)}) ---[/]")
    headless = Confirm.ask("[yellow]Запуск у фоновому режимі (headless)?[/]", default=True)

    if headless:
        runner.headless = True

    passed = 0
    failed = 0

    for name in scenarios:
        with console.status(f"Запуск: {name}..."):
            try:
                result = runner.run_scenario(name)
            except Exception as exc:
                console.print(f"  [red]ПОМИЛКА[/] {name}: {exc}")
                failed += 1
                continue

        status = result["status"]
        duration = result["duration_seconds"]
        steps_count = len(result["steps"])

        if status == "success":
            console.print(f"  [green]PASSED[/] {name} ({duration}s, {steps_count} кроків)")
            passed += 1
        else:
            console.print(f"  [red]FAILED[/] {name} ({duration}s)")
            for s in result["steps"]:
                if s["status"] == "error":
                    console.print(f"         Крок {s['step']}: {s['error'][:80]}")
            failed += 1

    console.print()
    summary = Table(show_header=False, box=box.SIMPLE)
    summary.add_column(style="bold")
    summary.add_column()
    summary.add_row("Всього:", str(passed + failed))
    summary.add_row("Пройшло:", f"[green]{passed}[/]")
    summary.add_row("Впало:", f"[red]{failed}[/]")
    console.print(Panel(summary, title="Результат", border_style="cyan"))


def action_list(cfg: dict):
    runner = _get_runner(cfg)
    scenarios = runner.list_scenarios()

    if not scenarios:
        console.print("[yellow]Сценаріїв не знайдено.[/]")
        return

    console.print(f"\n[bold cyan]--- Сценарії ({len(scenarios)}) ---[/]")
    _print_scenarios_list(runner, scenarios)


def action_results(cfg: dict):
    results_dir = Path("results")
    if not results_dir.exists():
        console.print("[yellow]Результатів поки немає.[/]")
        return

    files = sorted(results_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        console.print("[yellow]Результатів поки немає.[/]")
        return

    console.print(f"\n[bold cyan]--- Останні результати ---[/]")
    table = Table(box=box.ROUNDED, border_style="blue")
    table.add_column("#", style="dim", width=3)
    table.add_column("Файл")
    table.add_column("Статус")
    table.add_column("Час")

    for i, f in enumerate(files[:15], start=1):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            status = data.get("status", "?")
            duration = data.get("duration_seconds", "?")
            style = "green" if status == "success" else "red"
            table.add_row(str(i), f.stem, f"[{style}]{status}[/]", f"{duration}s")
        except Exception:
            table.add_row(str(i), f.stem, "[dim]?[/]", "?")

    console.print(table)


def action_details(cfg: dict):
    runner = _get_runner(cfg)
    scenarios = runner.list_scenarios()

    if not scenarios:
        console.print("[yellow]Сценаріїв не знайдено.[/]")
        return

    console.print("\n[bold cyan]--- Деталі сценарію ---[/]")
    _print_scenarios_list(runner, scenarios)

    name = _pick_scenario(scenarios)
    data = runner.load_scenario(name)

    console.print(f"\n[bold]{data.get('name', name)}[/]")
    console.print(f"URL: [cyan]{data.get('url', '—')}[/]")
    _print_steps_table(data.get("steps", []))


def _pick_scenario(scenarios: list[str], prompt_text: str = "Оберіть сценарій") -> str:
    """Вибір сценарію за номером або назвою."""
    while True:
        answer = Prompt.ask(f"\n[yellow]{prompt_text} (номер або назва)[/]").strip()
        if not answer:
            continue
        if answer.isdigit():
            idx = int(answer) - 1
            if 0 <= idx < len(scenarios):
                return scenarios[idx]
            console.print(f"[red]Невірний номер. Введіть 1-{len(scenarios)}[/]")
        elif answer in scenarios:
            return answer
        else:
            console.print(f"[red]Сценарій '{answer}' не знайдено.[/]")


def _print_scenarios_list(runner: TestRunner, scenarios: list[str]):
    table = Table(box=box.ROUNDED, border_style="blue")
    table.add_column("#", style="dim", width=3)
    table.add_column("Назва")
    table.add_column("Кроків", justify="center")
    table.add_column("URL")

    for i, name in enumerate(scenarios, start=1):
        data = runner.load_scenario(name)
        steps = len(data.get("steps", []))
        url = data.get("url", "—")
        table.add_row(str(i), name, str(steps), url)

    console.print(table)


def _print_steps_table(steps: list[dict]):
    if not steps:
        return
    table = Table(box=box.SIMPLE, border_style="dim")
    table.add_column("#", style="dim", width=3)
    table.add_column("Дія", style="yellow")
    table.add_column("Селектор")
    table.add_column("Значення")

    for i, s in enumerate(steps, start=1):
        table.add_row(
            str(i),
            s.get("action", ""),
            s.get("selector", ""),
            s.get("value", ""),
        )
    console.print(table)


def _print_result(name: str, result: dict):
    status = result["status"]
    duration = result["duration_seconds"]
    steps = result["steps"]

    if status == "success":
        console.print(f"\n[bold green]PASSED[/] — {name} ({duration}s, {len(steps)} кроків)")
    else:
        console.print(f"\n[bold red]FAILED[/] — {name} ({duration}s)")

    table = Table(box=box.SIMPLE, border_style="dim")
    table.add_column("#", style="dim", width=3)
    table.add_column("Дія")
    table.add_column("Статус")
    table.add_column("Час")
    table.add_column("Помилка")

    for s in steps:
        st = s["status"]
        style = "green" if st == "ok" else "red"
        table.add_row(
            str(s["step"]),
            s.get("action", ""),
            f"[{style}]{st}[/]",
            f"{s.get('time', '?')}s",
            s.get("error", "")[:60] if s.get("error") else "",
        )
    console.print(table)


ACTIONS = {
    "1": action_generate,
    "2": action_run,
    "3": action_run_all,
    "4": action_list,
    "5": action_results,
    "6": action_details,
}


def main():
    cfg = _load_config()
    show_banner()

    while True:
        show_menu()
        try:
            choice = Prompt.ask("\n[bold]Оберіть дію[/]", choices=["0", "1", "2", "3", "4", "5", "6"], default="0")
        except (KeyboardInterrupt, EOFError):
            break

        if choice == "0":
            console.print("[dim]До побачення![/]")
            break

        action = ACTIONS.get(choice)
        if action:
            try:
                action(cfg)
            except KeyboardInterrupt:
                console.print("\n[yellow]Скасовано.[/]")
            except Exception as exc:
                console.print(f"\n[red]Помилка:[/] {exc}")

        console.print()
