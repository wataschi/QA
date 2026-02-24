import json
from pathlib import Path
from datetime import datetime

from .browser import TestBrowser


class TestRunner:
    """Координатор: завантажує сценарії, запускає тести, зберігає результати."""

    def __init__(
        self,
        scenarios_dir: str = "scenarios",
        results_dir: str = "results",
        headless: bool = False,
        timeout: int = 30_000,
    ):
        self.scenarios_dir = Path(scenarios_dir)
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.timeout = timeout

    def list_scenarios(self) -> list[str]:
        """Повертає список імен доступних сценаріїв."""
        return sorted(p.stem for p in self.scenarios_dir.glob("*.json"))

    def load_scenario(self, name: str) -> dict:
        """Завантажує сценарій з файлу."""
        path = self.scenarios_dir / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Сценарій не знайдено: {path}")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def run_scenario(self, name: str) -> dict:
        """Запускає тест за іменем сценарію і зберігає результат."""
        test_data = self.load_scenario(name)

        browser = TestBrowser(headless=self.headless, timeout=self.timeout)
        result = browser.run_test(test_data)

        result["scenario"] = name
        result["timestamp"] = datetime.now().isoformat()

        self._save_result(name, result)
        return result

    def _save_result(self, name: str, result: dict):
        """Зберігає результат тесту у JSON файл."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.results_dir / f"{name}_{timestamp}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
