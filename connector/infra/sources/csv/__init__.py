"""CSV-адаптер источника — Polars-реализация RowSource

Пакет содержит CSV/Polars-сотрудников, которые читают CSV,
классифицируют low-level ошибки и передают raw-row в формат-агностичное
source core. Внешний compatibility import пока сохраняет `csv_reader.py`.

Ответственность:
    - Читать CSV через `polars.scan_csv().collect_batches()`.
    - Классифицировать известные Polars/OS ошибки в доменные source exceptions.
    - Собирать `PolarsCsvRecordSource` через reader + assembler.

Вне зоны ответственности:
    - Маппинг source fields к доменным строкам.
    - Валидация source schema и типизация значений.
"""

from connector.infra.sources.csv.builder import build_csv_source
from connector.infra.sources.csv.errors import PolarsCsvErrorClassifier
from connector.infra.sources.csv.reader import PolarsCsvFrameReader
from connector.infra.sources.csv.record_source import PolarsCsvRecordSource

__all__ = [
    "PolarsCsvErrorClassifier",
    "PolarsCsvFrameReader",
    "PolarsCsvRecordSource",
    "build_csv_source",
]
