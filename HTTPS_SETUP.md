# Настройка HTTPS через nginx + certbot

Приложение слушает порт 8800 (см. `Makefile`, `docker-compose.yml`). Перед
публикацией его нужно поставить за nginx с TLS, иначе Basic Auth админки и
весь трафик ходят открытым текстом.

Готовый минимальный конфиг лежит в `nginx.conf`. Ниже — как его накатить.

## 1. Установка nginx и certbot (Debian/Ubuntu)

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx
```

## 2. Доменное имя

Замените в `nginx.conf` значения `server_name`:

- для **публичного домена** (например `informer.example.com`) — укажите его
  и выпустите сертификат Let's Encrypt;
- для **внутренней сети** с самоподписанным сертификатом подойдёт любое
  имя хоста (например `informer.corp.local`) — главное, чтобы оно совпадало
  с `server_name` и сертификатом.

## 3. Вариант А — Let's Encrypt (публичный домен)

```bash
# Скопировать конфиг и включить
sudo cp nginx.conf /etc/nginx/sites-available/informer
sudo ln -s /etc/nginx/sites-available/informer /etc/nginx/sites-enabled/

# Предварительно конфиг сработает на HTTP (nginx перезапустится без TLS)
sudo nginx -t && sudo systemctl reload nginx

# Выпустить сертификат и встроить его в конфиг
sudo certbot --nginx -d informer.example.com

# Проверить автопродление (два раза в год)
sudo certbot renew --dry-run
```

`certbot --nginx` сам пропишет пути к сертификатам — закомментированные
в `nginx.conf` строки `ssl_certificate` станут лишними.

## 4. Вариант Б — самоподписанный сертификат (внутренняя сеть)

```bash
sudo openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout /etc/ssl/private/informer.key \
    -out /etc/ssl/certs/informer.crt \
    -subj "/CN=informer.corp.local"

sudo chmod 600 /etc/ssl/private/informer.key
```

Далее скопировать `nginx.conf`, поправить имя и перезапустить:

```bash
sudo cp nginx.conf /etc/nginx/sites-available/informer
sudo ln -s /etc/nginx/sites-available/informer /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Самоподписанный сертификат вызовет предупреждение браузера — это нормально
для внутреннего сервиса (можно прописать исключение или распространить CRT
по домену).

## 5. Проверка

- `curl -I https://informer.example.com` — ответ 200;
- HTTP-запрос (`http://...`) редиректится на HTTPS (код 301);
- `/admin` имеет заголовок `Strict-Transport-Security` и rate-limit nginx
  (5 r/s) дополнительно к лимиту приложения (`slowapi`, 20/min);
- сервис на 8800 продолжает работать: nginx проксирует его.

## 6. Привязка к сервису

Приложение должно слушать локально (не 0.0.0.0) — достаточно
`make run` (порт 8800). Держите сервис под systemd или Docker
(см. `docker-compose.yml`), чтобы он переживал ребуты.