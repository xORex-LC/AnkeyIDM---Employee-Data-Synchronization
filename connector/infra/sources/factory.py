"""Реестр адаптеров источников для выбора extract-источника.

Назначение:
    Хранит явные регистрации сборщиков `RowSource` по декларативному ключу
    `(source.type, source.format.kind)`.

Граница ответственности:
    Не читает данные источника и не знает о DI-контейнере. Владение
    регистрацией находится в composition root.
"""

from __future__ import annotations

from collections.abc import Callable

from connector.domain.ports.transform.sources import RowSource
from connector.domain.transform_dsl.specs import SourceSpec

SourceBuilder = Callable[[SourceSpec], RowSource]


class SourceAdapterRegistry:
    """Реестр сборщиков источников по типу и формату.

    Назначение:
        Даёт единую точку выбора runtime `RowSource` по `SourceSpec`.

    Контракт:
        - один ключ `(type, format.kind)` может иметь только один сборщик;
        - неизвестный ключ считается ошибкой конфигурации и падает fail-fast;
        - сборщик остаётся узким: `SourceSpec -> RowSource`.
    """

    def __init__(self) -> None:
        self._builders: dict[tuple[str, str | None], SourceBuilder] = {}

    def register(
        self,
        *,
        type: str,
        format: str | None,
        builder: SourceBuilder,
    ) -> None:
        """Зарегистрировать сборщик для одного ключа `(type, format.kind)`."""
        key = self._key(type=type, format=format)
        if key in self._builders:
            raise ValueError(
                f"Source adapter already registered for type={key[0]!r}, format={key[1]!r}"
            )
        self._builders[key] = builder

    def create(self, spec: SourceSpec) -> RowSource:
        """Создать `RowSource` по декларации источника."""
        key = self._key(type=spec.source.type, format=spec.source.format.kind)
        builder = self._builders.get(key)
        if builder is None:
            registered = ", ".join(
                f"{registered_type}/{registered_format}"
                for registered_type, registered_format in sorted(self._builders)
            )
            registered_message = registered or "<none>"
            raise ValueError(
                f"Unsupported source adapter: type={key[0]!r}, format={key[1]!r}. "
                f"Registered: {registered_message}"
            )
        return builder(spec)

    @staticmethod
    def _key(*, type: str, format: str | None) -> tuple[str, str | None]:
        normalized_type = type.strip().lower()
        normalized_format = format.strip().lower() if format is not None else None
        return normalized_type, normalized_format
