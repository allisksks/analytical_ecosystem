# Платформа аналитических сервисов

Продукт, который разворачивается во внутреннем контуре заказчика, подключается к его хранилищам
(ClickHouse, PostgreSQL, MySQL, файлы, S3…) и закрывает сценарии аналитиков, продактов и руководителей:
реестр событий (EMS), A/B-эксперименты, BI с витринами и база знаний с локальным ИИ-ассистентом.
Данные остаются у клиента — платформа хранит только метаданные, кэш и собственные сущности.

## Быстрый старт (один сервер, Docker Compose)

```bash
cp .env.example .env            # заполнить SECRET_KEY, ENCRYPTION_KEY, BOOTSTRAP_ADMIN_PASSWORD
make up                         # демо-данные + сборка + запуск
open http://localhost:8080
```

## Разработка

```bash
make setup                      # uv sync + npm ci
make dev-db                     # Postgres(+pgvector), Valkey, ClickHouse в Docker
make demo-data                  # Parquet-файлы мобильной игры в backend/demo-data
make dev-api                    # FastAPI на :8000 (Swagger: /api/v1/docs)
make dev-web                    # Vite на :5173 (проксирует /api на :8000)
make lint test
```

## Структура

```
backend/            Python 3.12, FastAPI, SQLAlchemy 2 + Alembic — модульный монолит
  app/core/         конфиг, БД, ошибки, логирование, middleware
  app/modules/      модули: iam, audit, connectors, query, semantic, bi, kb, ems, experiments, ai
  migrations/       Alembic
  scripts/          генератор демо-данных, экспорт OpenAPI
frontend/           React + TypeScript + Vite, CSS Modules, TanStack Query, ECharts
  src/shared/ui     UI-кит (кнопки, таблицы, модалки, тосты…) на CSS-токенах, светлая/тёмная тема
  src/shared/api    типизированный клиент, сгенерированный из OpenAPI 3.1
  src/features      экраны модулей
deploy/             compose для разработки, Helm-чарт
starter-kit/        стартовый набор: метрики, витрины, шаблоны дашбордов и KB, голден-сет
docs/               архитектура, руководства, настройка ИИ
```

## Этапы

| Этап | Содержание | Статус |
|---|---|---|
| 0. Подготовка | монорепо, CI, дизайн-система, генератор демо-данных, Docker Compose | ✅ |
| 1. Ядро и BI | роли и доступ, RLS, коннекторы, каталог, семантический слой, дашборды, SQL-редактор, KB без ИИ | ✅ |
| 2. Модули ВКР | реестр событий с валидацией и алертами, эксперименты (байес, SRM, сегменты) | ✅ |
| 3. Локальный ИИ | AI-шлюз (OpenAI-совместимый API), поиск и ответы по KB, генерация SQL, голден-сет | ✅ код готов; нужен ключ модели — [docs/ai-setup.md](docs/ai-setup.md) |

## ИИ-ассистент

Выключен по умолчанию. Чтобы включить — укажите модель и ключ в `.env` и перезапустите стек:
пошагово для Yandex AI Studio (Qwen3 235B) и локального Ollama — в [docs/ai-setup.md](docs/ai-setup.md).
Проверка качества: `make ai-exam` (экзамен по голден-сету, порог 70%).

Подробности — в [docs/architecture.md](docs/architecture.md) и [CONTRIBUTING.md](CONTRIBUTING.md).
