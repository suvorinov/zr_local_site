"""Сбрасывает БД и создаёт 50 тестовых сотрудников + 50 объявлений."""
import logging
from random import randint, choice
from datetime import date, datetime, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# удалить старую БД
db_path = Path("data") / "corp_site.db"
db_path.unlink(missing_ok=True)
logger.info("БД удалена")

from app.db import get_connection, init_db
init_db()
logger.info("БД инициализирована")

conn = get_connection()

# 50 сотрудников
last_names = [
    "Иванов", "Петров", "Сидоров", "Кузнецов", "Смирнов",
    "Васильев", "Зайцев", "Попов", "Волков", "Козлов",
    "Морозов", "Новиков", "Тимофеев", "Фролов", "Федоров",
    "Алексеев", "Григорьев", "Степанов", "Михайлов", "Николаев",
    "Орлов", "Соколов", "Семенов", "Егоров", "Белов",
    "Дмитриев", "Крылов", "Гусев", "Киселев", "Тарасов",
]
first_names_m = ["Алексей", "Дмитрий", "Максим", "Сергей", "Андрей", "Павел", "Владимир", "Игорь", "Николай", "Роман"]
first_names_f = ["Анна", "Елена", "Ольга", "Наталья", "Мария", "Татьяна", "Ирина", "Светлана", "Екатерина", "Юлия"]
patronymics = ["Иванович", "Петрович", "Сергеевич", "Алексеевич", "Дмитриевич", "Андреевич", "Владимирович", "Николаевич", "Павлович", "Викторович"]
patronymics_f = ["Ивановна", "Петровна", "Сергеевна", "Алексеевна", "Дмитриевна", "Андреевна", "Владимировна", "Николаевна", "Павловна", "Викторовна"]

for i in range(50):
    gender = choice(["male", "female"])
    last = choice(last_names)
    first = choice(first_names_m if gender == "male" else first_names_f)
    patron = choice(patronymics if gender == "male" else patronymics_f)
    name = f"{last} {first} {patron}"
    birthday = date(1960 + randint(0, 40), randint(1, 12), randint(1, 28))
    conn.execute("INSERT INTO employees (name, birthday, gender) VALUES (?, ?, ?)",
                 (name, birthday.isoformat(), gender))
logger.info("50 сотрудников добавлено")

# 50 объявлений
topics = [
    "Корпоратив в честь Дня рождения компании", "График работы в праздничные дни",
    "Результаты опроса удовлетворённости", "Новый корпоративный портал",
    "Набор в команду волонтёров", "Изменение процедуры согласования отпусков",
    "Запуск новой системы документооборота", "Приглашение на стратегическую сессию",
    "Окончание квартала — сдача отчётов", "Обновление политики безопасности",
    "Открытие нового офиса", "Вводные тренинги для новых сотрудников",
    "Конкурс профессионального мастерства", "Благотворительная акция",
    "Обновление ДМС", "Переход на новую версию 1С",
    "Спортивный турнир между отделами", "День открытых дверей",
    "Изменение регламента командировок", "Новогодний корпоратив",
    "Подведение итогов года", "Запуск программы наставничества",
    "Оптимизация рабочих процессов", "Обновление оргструктуры",
    "Реорганизация отдела продаж",
]
verbs = ["Уважаемые коллеги, информируем вас о", "Внимание!", "Доводим до вашего сведения,", "Обратите внимание:", "Сообщаем, что", "Напоминаем, что"]

for i in range(50):
    topic = choice(topics)
    verb = choice(verbs)
    days_ago = randint(0, 60)
    created = datetime.now() - timedelta(days=days_ago)
    text = f"{verb} {topic}. Подробности по телефону внутренний {randint(100, 999)}."
    # даём date_from/date_to некоторым объявлениям
    df = None
    dt = None
    if i < 10:
        df = (date.today() - timedelta(days=randint(0, 30))).isoformat()
        dt = (date.today() + timedelta(days=randint(1, 30))).isoformat()
    conn.execute(
        "INSERT INTO announcements (text, created_at, is_active, date_from, date_to) VALUES (?, ?, ?, ?, ?)",
        (text, created.isoformat(), randint(0, 1), df, dt),
    )
logger.info("50 объявлений добавлено")

conn.commit()
conn.close()
logger.info("Готово")
