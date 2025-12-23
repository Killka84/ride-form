# Ride Form (FastAPI + MongoDB)

Автономная форма (index.html) + API, сохраняет заявки в MongoDB.

## Быстрый старт
Требуется Python 3.10+.

### Windows (PowerShell)
```powershell
cd ride-form
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

Copy-Item .env.example .env
# поправь MONGO_URI при необходимости

uvicorn app:app --host 127.0.0.1 --port 8000
```

Если нужен доступ с телефона/другого ПК в локальной сети - используй `--host 0.0.0.0`, но тогда в логах могут появляться `Invalid HTTP request received` из-за сканеров/HTTPS-запросов на HTTP-порт.

### Linux/macOS
```bash
cd ride-form
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
uvicorn app:app --host 127.0.0.1 --port 8000
```

## HTTPS (TLS)
Uvicorn умеет работать по HTTPS, если указать сертификат и ключ в формате PEM.
Создай папку `certs/` и положи туда `localhost.pem` и `localhost-key.pem`.

### Let's Encrypt (standalone)
Условия: домен `blackpearl.site` (и/или `www.blackpearl.site`) должен указывать на IP сервера, порт 80 должен быть открыт снаружи и не занят другим сервисом на время выпуска/обновления.

Пример для Ubuntu/Debian:
```bash
sudo apt update
sudo apt install -y certbot
sudo certbot certonly --standalone -d blackpearl.site -d www.blackpearl.site
```
Файлы сертификата появятся в `/etc/letsencrypt/live/blackpearl.site/` (`fullchain.pem` и `privkey.pem`).

### Apache (reverse proxy + HTTPS)
Обычно TLS удобнее завершать на Apache, а Uvicorn оставить на `http://127.0.0.1:8000`.
Если используешь `certbot --standalone`, то на время `renew` Apache нужно останавливать (порт 80 должен быть свободен). Альтернатива: `sudo certbot --apache ...`.

Включи модули (Ubuntu/Debian):
```bash
sudo a2enmod ssl proxy proxy_http headers rewrite
sudo systemctl reload apache2
```

Пример конфига `/etc/apache2/sites-available/blackpearl.site.conf`:
```apacheconf
<VirtualHost *:80>
  ServerName blackpearl.site
  ServerAlias www.blackpearl.site

  RewriteEngine On
  RewriteRule ^ https://%{HTTP_HOST}%{REQUEST_URI} [L,R=301]
</VirtualHost>

<IfModule mod_ssl.c>
<VirtualHost *:443>
  ServerName blackpearl.site
  ServerAlias www.blackpearl.site

  SSLEngine on
  SSLCertificateFile /etc/letsencrypt/live/blackpearl.site/fullchain.pem
  SSLCertificateKeyFile /etc/letsencrypt/live/blackpearl.site/privkey.pem

  ProxyPreserveHost On
  RequestHeader set X-Forwarded-Proto "https"
  RequestHeader set X-Forwarded-Port "443"

  ProxyPass / http://127.0.0.1:8000/
  ProxyPassReverse / http://127.0.0.1:8000/
</VirtualHost>
</IfModule>
```

Включи сайт:
```bash
sudo a2ensite blackpearl.site.conf
sudo systemctl reload apache2
```

Вариант 1 (через флаги Uvicorn):
```bash
uvicorn app:app --host 0.0.0.0 --port 8443 --ssl-certfile certs/localhost.pem --ssl-keyfile certs/localhost-key.pem
```

Вариант 2 (через `run.py` + переменные в `.env`):
```env
UVICORN_PORT=8443
UVICORN_SSL_CERTFILE=certs/localhost.pem
UVICORN_SSL_KEYFILE=certs/localhost-key.pem
```
```bash
python run.py
```

Для локальной разработки удобно сделать сертификат через `mkcert` (или любой другой способ). Для продакшна обычно ставят TLS на Nginx/Caddy и проксируют на Uvicorn по HTTP.

Открой:
- http://SERVER:8000/ - форма
- http://SERVER:8000/api/health - health

## Что сохраняется в Mongo
Коллекция: `requests` (по умолчанию)

Поля:
- phone, tg, day, earliest_time
- start_point: { address, lat, lon, geo(Point) }
- created_at (UTC ISO)

## Примечание
Карта: OpenStreetMap (Leaflet) + поиск адреса Nominatim (без ключей).
