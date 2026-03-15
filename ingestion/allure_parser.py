"""
Парсер Allure-результатов.
Читает папку allure-results/ (JSON-файлы *-result.json) и возвращает
нормализованный список тест-кейсов с нужными полями.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class TestStep:
    name: str
    status: str  # passed / failed / broken / skipped


@dataclass
class TestResult:
    uid: str
    name: str
    full_name: str
    status: str          # passed / failed / broken / skipped / unknown
    duration_ms: int
    error_message: Optional[str]
    stack_trace: Optional[str]
    steps: list[TestStep]
    labels: dict[str, str]   # suite, feature, story, etc.
    attachments: list[str]   # file names


def parse_allure_results(results_dir: str | Path) -> list[TestResult]:
    """
    Читает все *-result.json из указанной папки.
    Возвращает только упавшие тесты (failed / broken).
    Чтобы получить все тесты — убери фильтр в конце.
    """
    results_dir = Path(results_dir)
    if not results_dir.exists():
        raise FileNotFoundError(f"Папка не найдена: {results_dir}")

    results: list[TestResult] = []

    for file in sorted(results_dir.glob("*-result.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"[WARN] Не удалось прочитать {file.name}: {e}")
            continue

        status_details = data.get("statusDetails") or {}
        steps = [
            TestStep(name=s.get("name", ""), status=s.get("status", ""))
            for s in data.get("steps", [])
        ]

        labels: dict[str, str] = {}
        for lbl in data.get("labels", []):
            labels[lbl.get("name", "")] = lbl.get("value", "")

        attachments = [a.get("source", "") for a in data.get("attachments", [])]

        result = TestResult(
            uid=data.get("uuid", file.stem),
            name=data.get("name", ""),
            full_name=data.get("fullName", ""),
            status=data.get("status", "unknown"),
            duration_ms=data.get("stop", 0) - data.get("start", 0),
            error_message=status_details.get("message"),
            stack_trace=status_details.get("trace"),
            steps=steps,
            labels=labels,
            attachments=attachments,
        )
        results.append(result)

    # Возвращаем только упавшие — можно убрать фильтр для полной статистики
    failed = [r for r in results if r.status in ("failed", "broken")]
    print(f"[INFO] Найдено {len(results)} тестов, из них упавших: {len(failed)}")
    return failed
