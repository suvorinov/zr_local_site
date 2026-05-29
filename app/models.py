"""Pydantic модели данных.

Определяет структуру данных для сотрудников и объявлений.
"""

from datetime import date, datetime

from pydantic import BaseModel, Field


class Employee(BaseModel):
    """Модель сотрудника.

    Attributes:
        id: Уникальный идентификатор.
        name: ФИО сотрудника.
        birthday: Дата рождения.
        gender: Пол (male/female).
    """

    id: int | None = None
    name: str = Field(..., min_length=1, description="ФИО сотрудника")
    birthday: date = Field(..., description="Дата рождения")
    gender: str = Field(..., pattern=r"^(male|female)$", description="Пол сотрудника")


class EmployeeCreate(BaseModel):
    """Модель для создания сотрудника."""

    name: str = Field(..., min_length=1, description="ФИО сотрудника")
    birthday: date = Field(..., description="Дата рождения")
    gender: str = Field(..., pattern=r"^(male|female)$", description="Пол сотрудника")


class Announcement(BaseModel):
    """Модель корпоративного объявления.

    Attributes:
        id: Уникальный идентификатор.
        text: Текст объявления.
        created_at: Дата и время создания.
        is_active: Флаг активности.
        date_from: Дата начала показа (включительно).
        date_to: Дата окончания показа (включительно).
    """

    id: int | None = None
    text: str = Field(..., min_length=1, description="Текст объявления")
    created_at: datetime | None = None
    is_active: bool = True
    date_from: date | None = Field(None, description="Дата начала показа")
    date_to: date | None = Field(None, description="Дата окончания показа")


class AnnouncementCreate(BaseModel):
    """Модель для создания объявления."""

    text: str = Field(..., min_length=1, description="Текст объявления")
    date_from: date | None = Field(None, description="Дата начала показа")
    date_to: date | None = Field(None, description="Дата окончания показа")


class Greeting(BaseModel):
    """Модель поздравления или объявления для отображения.

    Attributes:
        id: Уникальный идентификатор.
        type: Тип (birthday/announcement).
        text: Текст поздравления.
        image_path: Путь к изображению (для дня рождения).
        employee_name: Имя сотрудника (для дня рождения).
    """

    id: int
    type: str  # birthday / announcement
    text: str
    image_path: str | None = None
    employee_name: str | None = None
