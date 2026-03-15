# Roadmap — Test Stability Agent

---

## Общая идея

Агент наблюдает за каждым прогоном автотестов, накапливает историю,
классифицирует каждое падение на **баг приложения** или **проблему теста**
и предлагает конкретный фикс в стиле существующего кода проекта.

---

## MVP-1 — Ручная загрузка и анализ

**Цель**: рабочий инструмент, который можно использовать сегодня.  
**Срок**: 1–2 недели.

### Что входит

| Компонент | Описание |
|---|---|
| `allure_parser.py` | Читает `*-result.json` из любой папки `allure-results` |
| `db.py` (SQLite) | Хранит историю прогонов, тест-результатов и анализов |
| `llm_analyzer.py` | Отправляет данные о падениях в OpenAI, получает структурированный JSON |
| `system_prompt.md` | Промт агента с классификацией и правилами фиксов |
| `cli/main.py` | 4 команды: `ingest`, `analyze`, `report`, `history` |

### Workflow

```
1. Прогон завершился в TeamCity / локально
2. Скопировал папку allure-results на машину (или скачал артефакт вручную)
3. python -m cli.main ingest --path ./allure-results --run-id build_XXX
4. python -m cli.main analyze --run-id build_XXX
5. Открыл analysis_build_XXX.json — читаешь классификацию и фиксы
```

### Критерии готовности

- [x] `ingest` корректно парсит папку и сохраняет в SQLite
- [x] `analyze` отправляет данные в LLM и сохраняет JSON-ответ
- [x] JSON-ответ содержит: категорию, описание, предложение фикса (code_before / code_after)
- [x] `report` показывает таблицу с историей прогонов
- [x] `history` показывает тренд конкретного теста

---

## MVP-2 — Автоматизация + Контекст кода

**Цель**: агент работает сам после каждого прогона, знает кодовую базу.  
**Срок**: +2–3 недели после MVP-1.

### Что добавляем

#### 2.1 TeamCity API — автосбор артефактов

```python
# teamcity/collector.py
# GET /app/rest/builds/{buildId}/artifacts/children/allure-results
# Скачиваем ZIP, распаковываем, вызываем ingest автоматически
```

- Добавить команду `python -m cli.main fetch --build-id %teamcity.build.id%`
- Настроить TeamCity Build Step: вызов этой команды после прогона
- Переменные окружения: `TEAMCITY_URL`, `TEAMCITY_TOKEN`, `TEAMCITY_BUILD_TYPE_ID`

#### 2.2 RAG по кодовой базе

```python
# codebase/indexer.py
# Индексирует *.cs файлы из CODEBASE_PATH
# Ищет по full_name теста → возвращает исходный код теста + связанные PageObject
```

- Используем `chromadb` или простой keyword-поиск по имени класса/метода
- При анализе автоматически подкладываем код теста в user-сообщение
- Это резко повышает точность: агент видит реальный код и предлагает фикс с нужными именами переменных

#### 2.3 Telegram/Slack уведомления

```python
# notifications/telegram.py
# После analyze отправляет summary: N падений, M багов, K тест-проблем
# Для каждого APPLICATION_BUG — отдельное сообщение с описанием
```

- Webhook-интеграция (Telegram Bot API или Slack Incoming Webhook)
- Добавить флаг `--notify` к команде `analyze`

### Критерии готовности MVP-2

- [ ] `fetch --build-id` скачивает артефакты из TeamCity без ручного копирования
- [ ] Код теста автоматически подставляется в контекст LLM
- [ ] Качество фиксов: агент использует реальные имена методов из кода
- [ ] Telegram/Slack получает summary после каждого прогона

---

## MVP-3 — Веб-интерфейс + Интеграции

**Цель**: полноценный продукт для всей команды.  
**Срок**: +3–4 недели после MVP-2.

### Что добавляем

#### 3.1 Streamlit Dashboard

```
Страницы:
- Overview: тренды по времени (графики failed/passed по прогонам)
- Run Detail: все падения конкретного прогона с классификацией
- Test Card: полная история теста + все прогоны с фильтрами
- Bugs: список APPLICATION_BUG для передачи разработчикам
```

#### 3.2 Feedback Loop

- Кнопка "Неверная классификация" → сохраняет поправку в БД
- Накопленные поправки → дообучение промта (few-shot примеры)
- Через 50–100 поправок — точность классификации растёт

#### 3.3 Экспорт в YouTrack / Jira

```python
# integrations/youtrack.py
# Для каждого APPLICATION_BUG создаёт задачу с:
# - title из bug_report.title
# - description из steps_to_reproduce + expected/actual
# - priority из severity
```

- Флаг `--create-bugs` к команде `analyze`
- Дедупликация: не создаём задачу, если такой баг уже есть в трекере

### Критерии готовности MVP-3

- [ ] Dashboard отображает историю 30+ прогонов без тормозов
- [ ] Feedback сохраняется и влияет на следующие анализы
- [ ] YouTrack/Jira задачи создаются без дублей

---

## Техстек по версиям

| Компонент | MVP-1 | MVP-2 | MVP-3 |
|---|---|---|---|
| Парсинг отчётов | `allure_parser.py` (JSON) | + TeamCity API | без изменений |
| Хранилище | SQLite | SQLite | SQLite или PostgreSQL |
| LLM | OpenAI gpt-4o | OpenAI gpt-4o | + few-shot из feedback |
| Индексация кода | нет | keyword search по .cs | chromadb (векторный) |
| Интерфейс | CLI | CLI + Telegram | CLI + Web (Streamlit) |
| Деплой | локально | локально / Docker | Docker Compose |

---

## С чего начать прямо сейчас

```bash
# 1. Найди любой прогон с allure-results
#    (папка на твоей машине или скачай артефакт из TeamCity вручную)

# 2. Установи агент
git clone https://github.com/StenJaz/test-stability-agent.git
cd test-stability-agent
pip install -r requirements.txt
cp .env.example .env
# → добавь OPENAI_API_KEY в .env

# 3. Загрузи и проанализируй
python -m cli.main ingest --path /path/to/allure-results --run-id first_run
python -m cli.main analyze --run-id first_run

# 4. Смотри результат
cat analysis_first_run.json
```

Первый рабочий результат — через 15 минут после клонирования.
