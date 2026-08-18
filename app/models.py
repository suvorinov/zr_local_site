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
        title: Заголовок объявления.
        text: Текст объявления.
        created_at: Дата и время создания.
        is_active: Флаг активности.
        date_from: Дата начала показа (включительно).
        date_to: Дата окончания показа (включительно).
        priority: Приоритет (выше = важнее).
        category: Категория оформления (info/warning/success/danger).
        is_pinned: Закреплено вверху.
        image_path: Путь к изображению.
    """

    id: int | None = None
    title: str = Field(default="", description="Заголовок объявления")
    text: str = Field(..., min_length=1, description="Текст объявления")
    created_at: datetime | None = None
    is_active: bool = True
    date_from: date | None = Field(None, description="Дата начала показа")
    date_to: date | None = Field(None, description="Дата окончания показа")
    priority: int = Field(default=0, description="Приоритет (выше = важнее)")
    category: str = Field(default="info", pattern=r"^(info|warning|success|danger)$", description="Категория оформления")
    is_pinned: bool = Field(default=False, description="Закреплено вверху")
    image_path: str | None = Field(None, description="Путь к изображению")


class AnnouncementCreate(BaseModel):
    """Модель для создания объявления."""

    title: str = Field(default="", description="Заголовок объявления")
    text: str = Field(..., min_length=1, description="Текст объявления")
    date_from: date | None = Field(None, description="Дата начала показа")
    date_to: date | None = Field(None, description="Дата окончания показа")
    priority: int = Field(default=0, description="Приоритет")
    category: str = Field(default="info", description="Категория оформления")
    is_pinned: bool = Field(default=False, description="Закреплено")
    image_path: str | None = Field(None, description="Путь к изображению")


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
