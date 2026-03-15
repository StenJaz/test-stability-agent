"""
LLM-анализатор падений.
Принимает список упавших тестов + историю из БД,
отправляет в OpenAI/OpenRouter и возвращает структурированный JSON.

Поддерживает батчинг: большие прогоны разбиваются на порции,
чтобы не превышать контекстное окно и не делать дорогой запрос.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from openai import OpenAI

from ingestion.allure_parser import TestResult
from storage.db import get_test_history

SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "system_prompt.md"
DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct:free"
DEFAULT_BATCH_SIZE = 25  # тестов за один LLM-запрос
BATCH_DELAY_SEC = 2       # пауза между батчами (rate limit)


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


def _call_llm(client: OpenAI, model: str, system_prompt: str, user_message: str) -> dict:
    """
    Один LLM-запрос. Возвращает распарсенный dict.
    Для моделей с суффиксом :free не передаём response_format (не все поддерживают).
    """
    is_free_tier = ":free" in model

    kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
        temperature=0.1,
    )
    if not is_free_tier:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    raw = response.choices[0].message.content

    # Вырезаем JSON из markdown-блока, если модель завернула его в ```json ... ```
    if "```" in raw:
        import re
        m = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
        if m:
            raw = m.group(1).strip()

    return json.loads(raw)


def _merge_batches(batches: list[dict], run_id: str) -> dict:
    """Объединяет результаты нескольких батчей в один итоговый dict."""
    all_failures = []
    summary = {"total_failed": 0, "application_bugs": 0,
               "test_issues": 0, "flaky": 0, "unknown": 0}

    for b in batches:
        all_failures.extend(b.get("failures", []))
        s = b.get("summary", {})
        for key in summary:
            summary[key] += s.get(key, 0)

    return {
        "run_id": run_id,
        "analyzed_at": batches[0].get("analyzed_at", "") if batches else "",
        "summary": summary,
        "failures": all_failures,
    }


def analyze_failures(
    run_id: str,
    failures: list[TestResult],
    codebase_context: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict:
    """
    Анализирует падения через LLM с батчингом.
    Большие прогоны разбиваются на порции по batch_size тестов.
    Возвращает объединённый dict со всеми результатами.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "Переменная OPENAI_API_KEY не задана. "
            "Создайте файл .env и добавьте: OPENAI_API_KEY=sk-..."
        )

    base_url = os.getenv("OPENAI_BASE_URL")
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,  # None → стандартный OpenAI endpoint
    )

    system_prompt = _load_system_prompt()

    # Разбиваем на батчи
    batches_input = [
        failures[i:i + batch_size]
        for i in range(0, len(failures), batch_size)
    ]
    total_batches = len(batches_input)

    print(f"[LLM] Всего упавших: {len(failures)}, "
          f"батчей: {total_batches} по {batch_size} тестов (модель: {model})")

    batch_results = []
    for idx, batch in enumerate(batches_input, 1):
        print(f"[LLM] Батч {idx}/{total_batches} ({len(batch)} тестов)...")
        user_message = _build_user_message(
            f"{run_id}_batch{idx}", batch, codebase_context
        )
        try:
            result = _call_llm(client, model, system_prompt, user_message)
            batch_results.append(result)
            bugs = result.get('summary', {}).get('application_bugs', '?')
            tests = result.get('summary', {}).get('test_issues', '?')
            print(f"[LLM] Батч {idx} готов: APP_BUG={bugs}, TEST={tests}")
        except Exception as e:
            print(f"[ERROR] Батч {idx} упал: {e}")
            print(f"        Пропускаем и продолжаем...")

        # Пауза между батчами чтобы не словить rate limit
        if idx < total_batches:
            time.sleep(BATCH_DELAY_SEC)

    if not batch_results:
        raise RuntimeError("Все батчи завершились с ошибкой. Проверь ключ и баланс.")

    merged = _merge_batches(batch_results, run_id)
    s = merged["summary"]
    print(f"\n[LLM] Итого: {len(merged['failures'])} проанализировано, "
          f"APP_BUG={s['application_bugs']}, TEST={s['test_issues']}, "
          f"FLAKY={s['flaky']}, UNKNOWN={s['unknown']}")
    return merged
