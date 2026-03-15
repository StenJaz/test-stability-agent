"""
LLM-анализатор падений.
Принимает список упавших тестов + историю из БД,
отправляет в OpenAI и возвращает структурированный JSON.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from openai import OpenAI

from ingestion.allure_parser import TestResult
from storage.db import get_test_history

SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "system_prompt.md"
DEFAULT_MODEL = "gpt-4o"


def _load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def _build_user_message(
    run_id: str,
    failures: list[TestResult],
    codebase_context: Optional[str] = None,
) -> str:
    """
    Строит user-сообщение с данными о падениях + историей.
    codebase_context — фрагменты кода, найденные по именам тестов (опционально).
    """
    parts = [f"## Прогон: {run_id}\n"]
    parts.append(f"Упавших тестов: {len(failures)}\n")

    for i, t in enumerate(failures, 1):
        history = get_test_history(t.full_name, limit=10)
        fail_count = sum(1 for h in history if h["status"] in ("failed", "broken"))
        history_summary = (
            f"Падал {fail_count}/{len(history)} последних прогонов"
            if history
            else "Первый прогон в истории"
        )

        parts.append(f"""
---
### Тест {i}: {t.name}
- **Полное имя**: `{t.full_name}`
- **Статус**: {t.status}
- **История**: {history_summary}
- **Длительность**: {t.duration_ms} мс

**Ошибка**:
```
{t.error_message or '(нет сообщения)'}
```

**Стек трейс**:
```
{t.stack_trace or '(нет стека)'}
```

**Шаги**:
{chr(10).join(f"  - [{s.status}] {s.name}" for s in t.steps) or '  (шаги не записаны)'}
""")

    if codebase_context:
        parts.append(f"\n---\n## Фрагменты кода проекта\n\n{codebase_context}")

    parts.append("""
---
Верни результат строго в JSON-формате, описанном в system prompt.
Не добавляй пояснений вне JSON.
""")

    return "\n".join(parts)


def analyze_failures(
    run_id: str,
    failures: list[TestResult],
    codebase_context: Optional[str] = None,
    model: str = DEFAULT_MODEL,
) -> dict:
    """
    Анализирует падения через LLM.
    Возвращает распарсенный dict с ключом 'failures'.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "Переменная OPENAI_API_KEY не задана. "
            "Создайте файл .env и добавьте: OPENAI_API_KEY=sk-..."
        )

    client = OpenAI(api_key=api_key)

    system_prompt = _load_system_prompt()
    user_message = _build_user_message(run_id, failures, codebase_context)

    print(f"[LLM] Отправляю {len(failures)} падений на анализ (модель: {model})...")

    response = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
        temperature=0.1,  # детерминированный анализ
    )

    raw = response.choices[0].message.content
    result = json.loads(raw)
    print(f"[LLM] Анализ завершён. Категорий: "
          f"APP_BUG={result.get('summary', {}).get('application_bugs', '?')}, "
          f"TEST={result.get('summary', {}).get('test_issues', '?')}")
    return result
