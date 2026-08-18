# Руководство по HTTPS для корпоративного портал

## Зачем нужен HTTPS

Basic Auth передаёт логин/пароль в заголовке `Authorization: Basic base64(...)`.
**Без HTTPS это открытый текст** — любой в сети видит ваши учётные данные.

---

## Вариант 1: Самоподписанные сертификаты (закрытая сеть)

Для внутренней корпоративной сети, где TV-мониторы не выходят в интернет:

```bash
# 1. Создаём сертификат
sudo openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout /etc/ssl/private/informer.key \
    -out /etc/ssl/certs/informer.crt \
    -subj "/CN=informer.your-company.local"

# 2. Устанавливаем nginx
sudo apt install nginx

# 3. Копируем конфиг
sudo cp nginx.conf /etc/nginx/sites-available/informer.conf
sudo ln -sf /etc/nginx/sites-available/informer.conf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# 4. Проверяем и запускаем
sudo nginx -t && sudo systemctl reload nginx
```

**Для TV-мониторов:** установите самоподписанный корневой сертификат в доверенные
на каждом мониторе (Chrome: Settings → Privacy → Manage certificates).

---

## Вариант 2: Let's Encrypt (публичный домен)

Если портал доступен из интернета:

```bash
# 1. Устанавливаем certbot
sudo apt install certbot python3-certbot-nginx

# 2. Получаем сертификат
sudo certbot --nginx -d informer.your-company.local

# 3. Автопродление (уже настроено через cron)
sudo certbot renew --dry-run
```

---

## Вариант 3: Docker Compose с nginx

Добавьте в `docker-compose.yml`:

```yaml
services:
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - /etc/ssl/certs/informer.crt:/etc/ssl/certs/informer.crt:ro
      - /etc/ssl/private/informer.key:/etc/ssl/private/informer.key:ro
    depends_on:
      - corp-site

  corp-site:
    build: .
    expose:
      - "8800"    # Не port, а expose — только внутри сети
    volumes:
      - ./data:/app/data
      - ./app/static/greetings:/app/app/static/greetings
    env_file:
      - .env
    restart: unless-stopped
```

---

## Проверка

```bash
# Проверяем что HTTP редиректит на HTTPS
curl -I http://localhost

# Проверяем HTTPS
curl -k https://localhost  # -k для самоподписанных

# Проверяем заголовки безопасности
curl -Ik https://localhost | grep -E "(Strict|X-Frame|X-Content)"
```

---

## Порядок запуска

1. Создать сертификат (Вариант 1 или 2)
2. Настроить nginx
3. Запустить приложение: `docker compose up -d`
4. Проверить доступ: `https://informer.your-company.local`
