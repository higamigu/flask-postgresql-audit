from typing import Any, TypeVar

from sqlalchemy.orm import InstrumentedAttribute, Mapped

T = TypeVar("T")
OMap = Mapped[T | None]  # Optional Mapped / Nullable


AnyAttribute = InstrumentedAttribute[Any]
