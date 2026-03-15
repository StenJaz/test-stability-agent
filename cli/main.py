#!/usr/bin/env python3
"""
CLI для Test Stability Agent.

Команды:
  ingest   — загрузить allure-results из папки в БД
  analyze  — проанализировать упавшие тесты прогона через LLM
  report   — вывести последние прогоны из истории
  history  — показать историю конкретного теста

Использование:
  python -m cli.main ingest --path ./allure-results --run-id build_001
  python -m cli.main analyze --run-id build_001
  python -m cli.main report
  python -m cli.main history --test "Namespace.Class.Method"
"""

import argparse
import json
import sys
from pathlib import Path

# Загружаем .env если есть
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Добавляем корень проекта в sys.path при запуске как скрипт
sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.allure_parser import parse_allure_results
from storage.db import init_db, save_run, save_analysis, list_runs, get_test_history
from analysis.llm_analyzer import analyze_failures


def cmd_ingest(args):
    """Загружает allure-results в SQLite."""
    init_db()
    results = parse_allure_results(args.path)

    # При ingest сохраняем ВСЕ тесты (не только упавшие) — нужна полная статистика
    from ingestion.allure_parser import parse_allure_results as _parse
    import json as _json
    from pathlib import Path as _Path

    # Повторный парсинг без фильтра для полного сохранения
    all_results = []
    for file in sorted(_Path(args.path).glob("*-result.json")):
        try:
            data = _json.loads(file.read_text(encoding="utf-8"))
            from ingestion.allure_parser import TestResult, TestStep
            sd = data.get("statusDetails") or {}
            labels = {l.get("name", ""): l.get("value", "") for l in data.get("labels", [])}
            steps = [TestStep(name=s.get("name",""), status=s.get("status",""))
                     for s in data.get("steps", [])]
            all_results.append(TestResult(
                uid=data.get("uuid", file.stem),
                name=data.get("name", ""),
                full_name=data.get("fullName", ""),
                status=data.get("status", "unknown"),
                duration_ms=data.get("stop", 0) - data.get("start", 0),
                error_message=sd.get("message"),
                stack_trace=sd.get("trace"),
                steps=steps, labels=labels, attachments=[],
            ))
        except Exception:
            pass

    save_run(args.run_id, all_results, source="manual")
    print(f"[OK] Прогон '{args.run_id}' сохранён. Всего тестов: {len(all_results)}")


def cmd_analyze(args):
    """Запускает LLM-анализ для прогона."""
    init_db()

    # Загружаем упавшие тесты из БД (не перечитываем папку)
    from storage.db import get_conn
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT uid, name, full_name, status, duration_ms,
                      error_message, stack_trace, labels_json, steps_json
               FROM test_results
               WHERE run_id = ? AND status IN ('failed', 'broken')""",
            (args.run_id,),
        ).fetchall()

    if not rows:
        print(f"[WARN] Упавших тестов для прогона '{args.run_id}' не найдено в БД.")
        print("       Сначала выполните: python -m cli.main ingest --run-id ...")
        return

    from ingestion.allure_parser import TestResult, TestStep
    failures = []
    for r in rows:
        steps_raw = json.loads(r["steps_json"] or "[]")
        steps = [TestStep(name=s["name"], status=s["status"]) for s in steps_raw]
        failures.append(TestResult(
            uid=r["uid"], name=r["name"], full_name=r["full_name"],
            status=r["status"], duration_ms=r["duration_ms"] or 0,
            error_message=r["error_message"], stack_trace=r["stack_trace"],
            steps=steps,
            labels=json.loads(r["labels_json"] or "{}"),
            attachments=[],
        ))

    print(f"[INFO] Анализирую {len(failures)} упавших тестов для прогона '{args.run_id}'")

    result = analyze_failures(
        run_id=args.run_id,
        failures=failures,
        model=args.model,
    )

    result_json = json.dumps(result, ensure_ascii=False, indent=2)
    save_analysis(args.run_id, result_json)

    # Вывод в консоль
    print("\n" + "="*60)
    print(result_json)

    # Сохранение в файл
    out_file = Path(f"analysis_{args.run_id}.json")
    out_file.write_text(result_json, encoding="utf-8")
    print(f"\n[OK] Результат сохранён в {out_file}")


def cmd_report(args):
    """Выводит последние прогоны из истории."""
    init_db()
    runs = list_runs(limit=args.limit)
    if not runs:
        print("История пуста. Загрузите первый прогон: python -m cli.main ingest ...")
        return

    print(f"\n{'Run ID':<30} {'Source':<10} {'Ingested':<22} {'Total':>6} {'Failed':>7} {'Broken':>7} {'Passed':>7}")
    print("-" * 95)
    for r in runs:
        print(f"{r['run_id']:<30} {r['source']:<10} {r['ingested_at'][:19]:<22} "
              f"{r['total']:>6} {r['failed']:>7} {r['broken']:>7} {r['passed']:>7}")


def cmd_history(args):
    """Показывает историю конкретного теста."""
    init_db()
    history = get_test_history(args.test, limit=args.limit)
    if not history:
        print(f"Тест '{args.test}' не найден в истории.")
        return

    print(f"\nИстория теста: {args.test}")
    print(f"{'Дата':<22} {'Статус':<10} {'Ошибка (кратко)'}")
    print("-" * 80)
    for h in history:
        msg = (h["error_message"] or "")[:60].replace("\n", " ")
        print(f"{h['ingested_at'][:19]:<22} {h['status']:<10} {msg}")


def main():
    parser = argparse.ArgumentParser(
        description="Test Stability Agent CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ingest
    p_ingest = sub.add_parser("ingest", help="Загрузить allure-results в БД")
    p_ingest.add_argument("--path", required=True, help="Путь к папке allure-results")
    p_ingest.add_argument("--run-id", required=True, help="Уникальный ID прогона (например, build_001)")
    p_ingest.set_defaults(func=cmd_ingest)

    # analyze
    p_analyze = sub.add_parser("analyze", help="Запустить LLM-анализ для прогона")
    p_analyze.add_argument("--run-id", required=True, help="ID прогона для анализа")
    p_analyze.add_argument("--model", default="gpt-4o", help="OpenAI модель (по умолчанию gpt-4o)")
    p_analyze.set_defaults(func=cmd_analyze)

    # report
    p_report = sub.add_parser("report", help="История прогонов")
    p_report.add_argument("--limit", type=int, default=10)
    p_report.set_defaults(func=cmd_report)

    # history
    p_history = sub.add_parser("history", help="История конкретного теста")
    p_history.add_argument("--test", required=True, help="Полное имя теста (full_name)")
    p_history.add_argument("--limit", type=int, default=20)
    p_history.set_defaults(func=cmd_history)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
