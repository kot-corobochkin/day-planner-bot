from datetime import date
from pathlib import Path


class AgentMemory:
    def __init__(self, path: Path = Path("data/agent_memory.md")) -> None:
        self._path = path

    def read(self) -> str:
        try:
            return self._path.read_text(encoding="utf-8")[-6_000:]
        except OSError:
            return ""

    def append_feedback(self, *, plan_date: date, text: str) -> None:
        entry = f"\n## Обратная связь {plan_date}\n- {text.strip()}\n"
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as memory:
                memory.write(entry)
        except OSError:
            pass
