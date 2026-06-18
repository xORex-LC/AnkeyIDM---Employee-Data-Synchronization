"""Константы ECS logging runtime.

Модуль хранит значения, которые должны быть единым источником для taxonomy
loader-а и ECS renderer-а. Здесь нет I/O, валидации YAML или structlog wiring.

Границы ответственности:
    - Определять версию ECS для runtime output и degraded registry.
    - Определять service identity, добавляемую ECS renderer-ом.

Вне ответственности:
    - Загрузка taxonomy.
    - Рендеринг event dictionaries.
"""

from __future__ import annotations


ECS_VERSION = "8.11"
SERVICE_NAME = "nexus-etl"


__all__ = ["ECS_VERSION", "SERVICE_NAME"]
