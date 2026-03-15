# Test Stability Agent

AI-агент для анализа падений автотестов на основе Allure-отчётов.  
Стек: Python + OpenAI API + SQLite. Проект автотестов: C# / Selenium / NUnit.

---

## Возможности

| Что умеет | MVP-1 | MVP-2 | MVP-3 |
|---|:---:|:---:|:---:|
| Ручная загрузка allure-results | ✅ | ✅ | ✅ |
| Хранение истории в SQLite | ✅ | ✅ | ✅ |
| LLM-анализ fallen/broken тестов | ✅ | ✅ | ✅ |
| Классификация: APPLICATION_BUG / TEST_ISSUE | ✅ | ✅ | ✅ |
| Предложение фиксов в стилистике проекта | ✅ | ✅ | ✅ |
| Автосбор из TeamCity API | | ✅ | ✅ |
| RAG по кодовой базе автотестов | | ✅ | ✅ |
| Telegram/Slack уведомления | | ✅ | ✅ |
| Веб-интерфейс (Streamlit) | | | ✅ |
| Экспорт багов в YouTrack/Jira | | | ✅ |

---

## Быстрый старт (MVP-1)

### 1. Клонируй репозиторий

```bash
git clone https://github.com/StenJaz/test-stability-agent.git
cd test-stability-agent
```

### 2. Установи зависимости

```bash
pip install -r requirements.txt
```

### 3. Настрой `.env`

```bash
cp .env.example .env
# Отредактируй .env — добавь OPENAI_API_KEY
```

### 4. Скопируй allure-results

Скопируй папку `allure-results` из любого прогона в корень проекта или укажи путь явно.

### 5. Загрузи прогон в БД

```bash
python -m cli.main ingest --path ./allure-results --run-id build_001
```

### 6. Запусти анализ

```bash
python -m cli.main analyze --run-id build_001
```

Результат выведется в консоль и сохранится в `analysis_build_001.json`.

### 7. Посмотри историю прогонов

```bash
python -m cli.main report
```

### 8. История конкретного теста

```bash
python -m cli.main history --test "PravoRu.QA.CasePro.Tests.SomeClass.SomeMethod"
```

---

## Структура проекта

```
test-stability-agent/
├── ingestion/
│   └── allure_parser.py      # Парсинг *-result.json файлов
├── analysis/
│   └── llm_analyzer.py       # LLM-анализ через OpenAI
├── storage/
│   └── db.py                 # SQLite: runs, test_results, analyses
├── cli/
│   └── main.py               # CLI: ingest / analyze / report / history
├── prompts/
│   └── system_prompt.md      # System prompt агента
├── docs/
│   └── ROADMAP.md            # План разработки по MVP
├── allure_samples/           # Примеры allure-results для тестирования
├── data/                     # SQLite файл (создаётся автоматически, в .gitignore)
├── .env.example
├── requirements.txt
└── README.md
```

---

## Классификация падений

| Категория | Значение |
|---|---|
| `APPLICATION_BUG` | Регрессия или новый баг в приложении |
| `TEST_FLAKY` | Нестабильный тест (гонки, таймауги) |
| `TEST_LOCATOR` | Устаревший или изменившийся локатор |
| `TEST_LOGIC` | Неверная логика проверки или ассерт |
| `TEST_DATA` | Проблемы с тестовыми данными |
| `TEST_ENV` | CI-специфичная проблема |
| `UNKNOWN` | Требует дополнительного контекста |

---

## Roadmap

Подробный план по MVP — см. [docs/ROADMAP.md](docs/ROADMAP.md).
