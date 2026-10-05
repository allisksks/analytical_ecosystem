# Как мы работаем с кодом

## Ветки
- `main` — всегда зелёная, в неё ничего не пушится напрямую.
- Работа ведётся в ветках `feat/<этап>-<кратко>`, `fix/<кратко>`, `chore/<кратко>`.
- Каждая ветка вливается через merge request / pull request после зелёного CI и ревью.
- Размер MR — до ~400 изменённых строк логики (без сгенерированных файлов); большие задачи делятся.

## Коммиты
[Conventional Commits](https://www.conventionalcommits.org/ru/): `feat(bi): конструктор блоков`, `fix(query): …`, `chore(ci): …`, `docs: …`, `test: …`.

## Перед пушем
```bash
make lint   # ruff, mypy --strict, oxlint, tsc, prettier
make test   # pytest (нужен Postgres из deploy/docker-compose.dev.yml) + vitest
```
Если поменялись схемы API — `make openapi` и закоммитить `frontend/src/shared/api/{openapi.json,schema.d.ts}`
(CI проверяет, что они актуальны).

## Миграции
Только через Alembic: `cd backend && uv run alembic revision --autogenerate -m "..."`.
Миграции с удалением колонок или таблиц делает человек (см. ТЗ, раздел 9).

## Лицензии зависимостей
Разрешены MIT, Apache-2.0, BSD, ISC, OFL (шрифты). AGPL и BSL не добавляем.
