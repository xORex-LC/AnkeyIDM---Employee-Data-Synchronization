# ARCH-DEC-001: Модульный монолит на uv workspace (shared kernel + package-per-stage, bottom-up)

> **Статус**: Принято
> **Дата принятия**: 2026-06-16
> **Решает проблему**: [ARCH-PROBLEM-001](./ARCH-PROBLEM-001-monolith-modularity-and-navigability.md)
> **Участники решения**: @xORex-LC

---

## 📋 Контекст

Монолит `connector` организован горизонтально по слоям; стадии «размазаны» по слоям, не изолированы
структурно, нет единицы независимой разработки/навигации
([ARCH-PROBLEM-001](./ARCH-PROBLEM-001-monolith-modularity-and-navigability.md)). Драйвер — навигируемость
и агностичные стадии. Полная карта, таксономия и разбор —
[MODULARIZATION_VISION_WORKNOTE](../../notes/modularization/MODULARIZATION_VISION_WORKNOTE.md).

**Объём этого ADR:** зафиксировать **архитектуру и конвенции** модульного монолита + **bootstrap** uv
workspace, с `nexus-common` как первым вынесенным членом (proof). Состав `nexus-kernel` (ОВ-M1) и
последующие пакеты — отдельные шаги под этим решением.

---

## 🎯 Решение

Перейти к **модульному монолиту**: набор пакетов в **uv workspace**, организованных
**package-by-feature** (вертикальный срез), с общим низом (shared kernel + сквозные концерны).

Принципы (нормативные):

1. **Гранулярность — fine-grained: пакет на стадию** (`extract/map/normalize/enrich/match/resolve/topology`)
   + сквозные shared-пакеты (`kernel/diagnostics/dsl/dsl-specs/logging/reporting/config/common/sqlite/
   cache/target/vault/dictionaries/datasets`) + `connector` как app/composition root. ~24 пакета (цель).
2. **Правило зависимостей: только ВНИЗ по tier'ам, никогда ВБОК.** Стадия зависит от shared-tier, но
   **не** от другой стадии. DAG обязателен (workspace не допускает циклов). Соединяет стадии в пайплайн
   только `connector` (`PipelineComposer`).
3. **Вертикальный гексагон внутри пакета-стадии**: `src/<pkg>/{domain, adapters, __init__}`; адаптеры
   стадии живут внутри её пакета (кроме переиспользуемых несколькими стадиями — те отдельный shared-пакет).
4. **Только ось A (код-модульность)**. Ось B (процессы+очереди, RMQ-стиль) — вне объёма; `StageContract`
   держим транспорт-агностичным, чтобы будущий split был no-op.
5. **Bottom-up порядок** раскатки: `common` → `kernel` → остаток Tier 0 → Tier 1 → стадии (extract первой)
   → plan/apply → connector. Пакет выносится только когда его зависимости уже пакеты.
6. **Стратегия путей — re-export-шимы**: канон переезжает в новый пакет, на старых путях `connector.*`
   остаются тонкие реэкспорты → call-sites не переписываются разом (инкрементальный churn).

Конвенции (нормативные):

- **Раскладка**: `connector` — корневой член на месте; библиотеки — в `packages/<name>/` со `src/`-layout.
- **Имена**: дистрибутив `nexus-<name>` (kebab), импорт-пакет `nexus_<name>` (snake), плоско (без namespace-пакета).
- **Build backend члена-библиотеки**: `uv_build`. `connector` на первом этапе остаётся на setuptools
  (uv workspace это допускает); глобальная миграция backend — отдельно при необходимости.
- **Tooling**: uv становится менеджером окружения/зависимостей репо (`uv.lock`, `uv sync`), вытесняя
  `python -m venv`+`pip install -e`. CLAUDE.md/Makefile/CI обновляются.

---

## 🏗️ Архитектурное решение

### Таксономия (tier'ы DAG)

```
Tier 0 (foundation):  common · kernel · diagnostics · dsl · config · sqlite · logging
Tier 1 (shared):      dsl-specs · cache · target · vault · dictionaries · reporting · datasets
Tier 2 (stages):      extract · map · normalize · enrich · match · resolve · topology   (НЕ зависят друг от друга)
Tier 3 (plan/apply):  plan · apply
Tier 4 (app):         connector   (composition root — соединяет стадии, вяжет DI)
```
Полная карта «целевой пакет → текущий код → роль → зависимости» — worknote §4.

### Bootstrap (этот ADR) — `nexus-common` как первый член

- `common/` — проверенный лист (только stdlib, ноль импортов `connector.*`), fan-in 70 → идеален для
  tooling-пилота с шимами.
- Создаётся корневой `[tool.uv.workspace] members=["packages/*"]`; `connector` — корневой член;
  `packages/nexus-common/` — первый библиотечный член (`uv_build`).
- Код `common/*` переезжает в `nexus_common`; в `connector/common/*` остаются re-export-шимы → 70
  call-sites работают без правок.

### Интерфейсы (форма, не код)

```toml
# pyproject.toml (root)
[tool.uv.workspace]
members = ["packages/*"]

[tool.uv.sources]
nexus-common = { workspace = true }

# packages/nexus-common/pyproject.toml
[project]
name = "nexus-common"
requires-python = ">=3.11"
[build-system]
requires = ["uv_build>=0.11,<0.12"]
build-backend = "uv_build"
```
```python
# connector/common/runtime_paths.py  (re-export shim, путь стабилен)
from nexus_common.runtime_paths import *  # noqa: F401,F403
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ Навигируемость: каждый concern — одна директория со своим `pyproject` и явной границей.
- ✅ Структурная изоляция стадий: sibling-импорт физически невозможен (нет в зависимостях члена).
- ✅ Независимая разработка/тест; путь к будущему per-stage split (ось B) как no-op.
- ✅ Консистентность: вертикальный гексагон сохраняет «domain не импортит infra» внутри пакета.
- ✅ Инкрементальность: bottom-up + шимы → нет big-bang, каждый шаг обратим.

**Недостатки (компромиссы)**:
- ⚠️ ~24 пакета — нагрузка на одиночного maintainer'а (сборка/lock/ceremony). Митигация: bottom-up,
  оценка после `kernel` и после `extract`; допустимо укрупнить tier'ы, если fine окажется тяжёлым.
- ⚠️ Churn общих типов (`TransformResult`/`SourceRecord`) — митигация re-export-шимами.
- ⚠️ Смена тулчейна на uv — разовая стоимость (доки/CI).

**Альтернативы, которые отклонили**:
- ❌ **Coarse-grained** (несколько крупных пакетов): меньше ceremony, но не даёт per-stage изоляции,
  которую хочет драйвер; и хуже под будущую ось B. Выбран fine (решение пользователя).
- ❌ **Оставить горизонтальные слои + только доки/линтер**: нет физической границы (Вариант 2 в PROBLEM-001).
- ❌ **Namespace-пакет `nexus.<stage>`**: сложнее (PEP420-нюансы), не нужен — берём плоские `nexus_*`.
- ❌ **entry-points discovery вместо явной DI-регистрации**: возвращает plugin-discovery против ОВ-1.2.
- ❌ **Top-down раскатка / extract первым пакетом**: цикл (стадия тащит зависимость на `connector`),
  пока нет kernel; «минимальный kernel под extract» иллюзорен (его типы универсальны).
- ❌ **Ось B (процессы+очереди) сейчас**: пользователь не ориентируется на это; огромная стоимость.

---

## 🛠️ Реализация

> Bootstrap-шаги и change-set'ы — в отдельном implementation-плане (оформляется перед кодом). Здесь — состав/инварианты.

### Ключевые артефакты bootstrap

| Артефакт | Изменение |
|------|-----------|
| `pyproject.toml` (root) | `[tool.uv.workspace] members`; `connector` — корневой член; `[tool.uv.sources]` |
| `packages/nexus-common/` | Новый член: `pyproject.toml` (`uv_build`), `src/nexus_common/*` (перенос `common/*`), `tests/` |
| `connector/common/*` | Заменяются на re-export-шимы на `nexus_common.*` |
| `uv.lock` | Появляется (резолв всего workspace) |
| `CLAUDE.md`, `Makefile`, CI | uv-команды (`uv sync`/`uv run`) вместо `pip install -e` |
| `docs/dev/INDEX.md` | Ссылка на модульную карту |

### Инварианты

1. **DAG**: зависимости только вниз по tier'ам; циклов нет (страхует workspace + import-linter).
2. **Стабильность путей**: старые `connector.*` импорты работают через шимы (поведение тождественно).
3. **Изоляция стадий**: член-стадия не имеет в зависимостях другой стадии.
4. **Вертикальный гексагон**: `<pkg>/domain` не импортит `<pkg>/adapters`.
5. **Зелёный CI**: pytest/mypy/lint-imports проходят после bootstrap (шимы + новый член).

---

## 🧪 Валидация решения

- ✅ `uv sync` поднимает workspace; `uv run pytest` зелёный.
- ✅ `nexus_common` импортируется и как пакет, и через старые `connector.common.*` (шимы).
- ✅ `lint-imports` без новых нарушений; добавить контракт «стадии не зависят друг от друга» по мере роста.
- ✅ Полный тест-сьют без регресса (поведение common неизменно — только перемещение).

**Метрики успеха**:
- Добавление будущей стадии-пакета не требует правок других стадий.
- «Где живёт X» отвечается по карте (worknote §4) за секунды.

---

## ⚠️ Риски и ограничения

- ⚠️ uv не установлен — bootstrap требует установки uv (системное действие, согласуется отдельно).
- ⚠️ Единый `requires-python` на весь workspace (у нас `>=3.11` — ок; ограничение uv).
- ⚠️ Over-fragmentation (~24 пакета) — оценка после `kernel`/`extract`; укрупнение допустимо.
- ⚠️ Шимы как долг — снимаются инкрементально; зафиксировать в плане раскатки.
- **Вне объёма**: состав `nexus-kernel` (ОВ-M1, шаг kernel); ось B; глобальная миграция backend.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `pyproject.toml`/toolchain | Прямое | workspace + uv как менеджер |
| `connector.common.*` потребители (70) | Косвенное | работают через шимы, правок нет |
| CLAUDE.md / Makefile / CI | Прямое | uv-команды |
| Остальные стадии/слои | Нет (пока) | раскатываются последующими шагами bottom-up |

---

## 📚 Документация

- ⏳ `CLAUDE.md` / `Makefile` — uv-workflow (при bootstrap).
- ⏳ `packages/nexus-common/README.md` — назначение пакета.
- ✅ [MODULARIZATION_VISION_WORKNOTE](../../notes/modularization/MODULARIZATION_VISION_WORKNOTE.md) — карта/таксономия/порядок.

---

## 🔗 Связанные документы

- [ARCH-PROBLEM-001](./ARCH-PROBLEM-001-monolith-modularity-and-navigability.md) — решаемая проблема
- [MODULARIZATION_VISION_WORKNOTE](../../notes/modularization/MODULARIZATION_VISION_WORKNOTE.md) — полная карта, ОВ-M1…M6
- [EXTRACT_REFACTOR_WORKNOTE](../../notes/extract/EXTRACT_REFACTOR_WORKNOTE.md) — extract как первая стадия (Tier 2)
- [OBSERVABILITY-DEC-002](../observability/OBSERVABILITY-DEC-002-per-component-prod-observability-layout.md) — наблюдаемость спроектирована под будущий per-stage split

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-06-16 | Проблема ([ARCH-PROBLEM-001](./ARCH-PROBLEM-001-monolith-modularity-and-navigability.md)) и видение (worknote) зафиксированы |
| 2026-06-16 | Решение принято: fine-grained модульный монолит на uv workspace, bottom-up, шимы; `nexus-common` — первый член |
| — | Implementation plan + bootstrap (ожидается) |
