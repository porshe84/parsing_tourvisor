# Инструкция по развертыванию Tourvisor Bot на VPS вместе с Flask проектом

У вас уже есть VPS с настроенным Nginx и проектом в `/var/lib/postgresql/my_flask_project`. Ваш Nginx слушает порты 80 (какой-то проект `site`) и 8080 (Flask приложение `nalog`).

Мы можем настроить Tourvisor Bot как **отдельный сервис**, который будет работать в фоне через Systemd (собирать туры и обновлять HTML-страницу), а раздавать эту HTML-страницу можно через Nginx на новом порту, например, **8081**.

Ниже приведена пошаговая инструкция для вашего сервера (на базе Ubuntu/Debian).

---

## 1. Копирование файлов Tourvisor Bot на сервер

1. Подключитесь к вашему серверу по SSH (например, через VS Code или терминал `ssh -p 47356 karandash@179.43.174.148`).
2. Создайте папку для бота, например `/var/lib/postgresql/tourvisor_bot`:
   ```bash
   sudo mkdir -p /var/lib/postgresql/tourvisor_bot
   sudo chown -R karandash:postgres /var/lib/postgresql/tourvisor_bot
   chmod -R 775 /var/lib/postgresql/tourvisor_bot
   ```
3. Положите в эту папку файлы нашего проекта бота (в частности файл `tourvisor_bot.py`).

## 2. Настройка виртуального окружения Python

Перейдите в папку бота и создайте виртуальное окружение:

```bash
cd /var/lib/postgresql/tourvisor_bot
python3 -m venv venv
source venv/bin/activate
pip install requests schedule
```
*(База данных `sqlite3` идет в комплекте со стандартной библиотекой Python).*

## 3. Настройка автоматического запуска (Systemd)

Мы создадим Systemd сервис, который будет запускать планировщик (`schedule`) и работать в фоне постоянно, дважды в день скачивая цены и генерируя файл `index.html`.

1. Создайте файл службы `/etc/systemd/system/tourvisor.service` (потребуются права root):

   ```ini
   [Unit]
   Description=Tourvisor Scraper Bot
   After=network.target

   [Service]
   User=karandash
   Group=postgres
   WorkingDirectory=/var/lib/postgresql/tourvisor_bot

   # Здесь обязательно укажите ваш Telegram токен, и, если нужно, TELEGRAM_CHAT_ID (если бот уже получил от вас сообщение - можно не указывать, он найдет его сам)
   Environment="TELEGRAM_BOT_TOKEN=ВАШ_ТОКЕН_ЗДЕСЬ"
   # Environment="TELEGRAM_CHAT_ID=ВАШ_ID"

   # Часовой пояс сервера может быть UTC. Тогда 04:00 и 15:00 UTC = 07:00 и 18:00 MSK.
   # Environment="SCHEDULE_TIME_1=04:00"
   # Environment="SCHEDULE_TIME_2=15:00"

   ExecStart=/var/lib/postgresql/tourvisor_bot/venv/bin/python3 tourvisor_bot.py
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```

2. Запустите сервис:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl start tourvisor
   sudo systemctl enable tourvisor
   ```

3. Проверьте статус: `sudo systemctl status tourvisor`. Если все хорошо, бот сразу выполнит первый запуск и создаст файл `index.html` в папке `/var/lib/postgresql/tourvisor_bot/`.

## 4. Настройка веб-доступа через Nginx (Порт 8081)

Теперь нам нужно просто "раздать" папку `/var/lib/postgresql/tourvisor_bot/` (в которой лежит `index.html`) через Nginx на порту `8081`.

1. Откройте порт 8081 в фаерволе:
   ```bash
   sudo ufw allow 8081/tcp
   ```

2. Создайте файл конфигурации Nginx `/etc/nginx/sites-available/tourvisor`:

   ```nginx
   server {
       listen 8081;
       server_name 179.43.174.148;

       root /var/lib/postgresql/tourvisor_bot;
       index index.html;

       location / {
           try_files $uri $uri/ =404;

           # Отключаем кэширование, чтобы всегда видеть свежую таблицу туров
           add_header Cache-Control 'no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0';
           if_modified_since off;
           expires off;
           etag off;

           # Если хотите защитить доступ паролем (как в проекте nalog), раскомментируйте:
           # auth_basic "Служебный вход";
           # auth_basic_user_file /etc/nginx/.htpasswd;
       }
   }
   ```

3. Активируйте сайт и перезапустите Nginx:

   ```bash
   sudo ln -s /etc/nginx/sites-available/tourvisor /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl reload nginx
   ```

## Готово!

Теперь вы можете зайти на `http://179.43.174.148:8081/` в браузере. Там будет отображаться статический файл `index.html`.

Сам бот (служба `tourvisor.service`) работает независимо в фоне, и два раза в день автоматически пересобирает этот `index.html` и пишет цены в базу `tours.db`. Страница в браузере при обновлении всегда будет отдавать актуальную версию отчета.
