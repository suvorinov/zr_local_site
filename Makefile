SHELL := /bin/bash

PY := .venv/bin/python
PIP := .venv/bin/pip
COM := docker compose

# UID/GID текущего пользователя — процесс в образе получает те же права,
# что и владелец каталогов data/ и app/static/greetings на хосте.
build-uid := $(shell id -u)
build-gid := $(shell id -g)

.PHONY: help install test prepare run db-import seed build up down stop restart logs ps smoke

help: ## Показать список команд
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## Создать виртуальное окружение и установить зависимости
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PIP) install -r requirements-dev.txt

test: ## Запустить тесты (pytest)
	$(PY) -m pytest -q

prepare: ## Создать рабочие каталоги и .env из примера (если его нет)
	mkdir -p data app/static/greetings/samples
	@test -f .env || { echo "Создаю .env из .env.example — задайте пароли и ключи!"; cp .env.example .env; }

run: prepare ## Локальный запуск для разработки (порт 8800, автоперезагрузка)
	$(PY) -m uvicorn app.main:app --host 0.0.0.0 --port 8800 --reload \
		--reload-dir app --reload-exclude 'app/static/greetings/*'

db-import: ## Импорт актуального персонала из data/staff.txt (БД пересобирается)
	$(PY) import_staff.py --reset

seed: prepare ## ВНИМАНИЕ: пересоздать БД с тестовыми данными (50 сотрудников, 50 объявлений)
	$(PY) reset_and_seed.py

build: ## Собрать Docker-образ под UID/GID текущего пользователя
	env UID=$(build-uid) GID=$(build-gid) $(COM) build

up: ## Собрать образ и поднять сервис в Docker (хост-порт: APP_PORT, по умолчанию 8822)
	env UID=$(build-uid) GID=$(build-gid) $(COM) up -d --build

down: ## Остановить контейнер и удалить его
	$(COM) down

stop: ## Остановить контейнер (не удаляя)
	$(COM) stop

restart: ## Перезапустить контейнер
	$(COM) restart

logs: ## Логи контейнера (Ctrl+C для выхода)
	$(COM) logs -f

ps: ## Статус контейнеров
	$(COM) ps

smoke: ## Проверка доступности сервиса (порт APP_PORT, по умолчанию 8822)
	curl -fsS -o /dev/null -w "HTTP %{http_code}\n" "http://127.0.0.1:$${APP_PORT:-8822}/"