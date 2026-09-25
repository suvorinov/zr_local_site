"""Pydantic модели данных форм.

Определяет структуру данных, принимаемых из форм админки.
"""

from datetime import date

from pydantic import BaseModel, Field


class EmployeeCreate(BaseModel):
    """Модель для создания сотрудника."""

    name: str = Field(..., min_length=1, description="ФИО сотрудника")
    birthday: date = Field(..., description="Дата рождения")
    gender: str = Field(..., pattern=r"^(male|female)$", description="Пол сотрудника")