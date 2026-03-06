# Звіт з оптимізації продуктивності CKAN Open Data Portal

**Дата:** 2026-03-05  
**Версія CKAN:** 2.11.3  
**Середовище тестування:** Docker (dev), 1 Gunicorn worker, Flask devserver

---

## 1. Проблема

При навантажувальному тестуванні (JMeter, 100 concurrent users, 3s delay):
- **Прод-сервер**: повний таймаут → перманентні 504 помилки
- **Stage (Kubernetes)**: запити до 200 секунд, але без crash

Найслабкіші сторінки:
- `/dataset/` — список наборів даних (НД)
- `/organization/` — список організацій (ДБ НБ)
- `/group/` — список категорій (ДБ орг)

### Кореневі причини
1. **N+1 SQL-запити** — для кожного елементу списку виконувались окремі запити до БД
2. **Відсутність кешування** на рівні Nginx та CKAN
3. **Неоптимальна конфігурація Gunicorn** — 4 sync workers = max 4 одночасні запити
4. **Відсутній пул з'єднань SQLAlchemy** — нові з'єднання на кожен запит
5. **Webassets в debug-режимі** на проді — нестиснуті CSS/JS

---

## 2. Перелік внесених змін

### Фаза 1 — Інфраструктура

| # | Файл | Зміна | До | Після |
|---|---|---|---|---|
| 1 | `.env_for_prod` | Gunicorn concurrency | `--workers=4 --timeout=120` | `--workers=4 --threads=4 --worker-class=gthread --timeout=120 --graceful-timeout=90 --keep-alive=5 --max-requests=1000 --max-requests-jitter=50` |
| 2 | `nginx/setup/default.conf` | Proxy timeouts | Відсутні | `proxy_connect_timeout 10; proxy_send_timeout 130; proxy_read_timeout 130; send_timeout 130` |
| 3 | `nginx/setup/default.conf` | Proxy cache | Закоментовано | `proxy_cache cache; proxy_cache_valid 200 5m; proxy_cache_valid 404 1m` |
| 4 | `nginx/setup/default.conf` | Cache bypass auth | `$cookie_auth_tkt` | `$cookie_auth_tkt $cookie_ckan` (додано Flask-Login cookie) |
| 5 | `nginx/setup/default.conf` | Proxy buffering | Вимкнено | `proxy_buffering on; proxy_buffer_size 16k; proxy_buffers 8 32k` |
| 6 | `src/ckan_prod.ini` | CKAN cache | `expires=0, enabled=false` | `expires=300, enabled=true` |
| 7 | `src/ckan_prod.ini` | Webassets | `debug=true, cache=false, munge=false` | `debug=false, cache=true, munge=true` |
| 8 | `src/ckan_prod.ini` | SQLAlchemy pool | Дефолт (без пулу) | `pool_size=10, max_overflow=20, pool_recycle=3600, pool_timeout=30` |
| 9 | `src/ckan_test_server.ini` | SQLAlchemy pool | Дефолт (без пулу) | `pool_size=10, max_overflow=20, pool_recycle=3600, pool_timeout=30` |
| 10 | `ckan/Dockerfile.production` | INI файл | `COPY src/ckan.ini` (dev!) | `COPY src/ckan_prod.ini` (prod) |

### Фаза 2 — Код (N+1 → Bulk)

| # | Файл | Зміна | Кількість SQL до | Кількість SQL після |
|---|---|---|---|---|
| 11 | `ckanext/tracking/model.py` | Додано `get_for_packages()` — bulk-fetch tracking по пакетах | N запитів | 1 запит |
| 12 | `ckanext/tracking/model.py` | Додано `get_for_resources()` — bulk-fetch tracking по ресурсах | N запитів | 1 запит |
| 13 | `ckanext/tracking/plugin.py` | `after_dataset_search` переписано на bulk-виклики | ~32 запити (16 pkg + 16×res) | 2 запити |
| 14 | `ckan/views/group.py` | `organization_show` × N замінено на `dictize_light` + batch SQL | ~75-125 запитів | 2 запити |
| 15 | `ua_portal_design/plugin.py` | Batch-fetch org names/images для пошуку | N × `organization_show` | 1 SQL |
| 16 | `ua_portal_design/plugin.py` | Batch-fetch dashboard counts | N SQL | 1 SQL |
| 17 | `ua_portal_design/plugin.py` | Batch-fetch API resource flags | N SQL | 1 SQL |
| 18 | `ua_portal_design/plugin.py` | Inject `_precomputed_*` в пакети | — | — |
| 19 | `ua_portal_design/templates/snippets/package_item.html` | Використання `_precomputed_*` з fallback | N helper calls | 0 (precomputed) |
| 20 | `ua_portal_design/templates/snippets/package_item.html` | Видалено невикористаний `subscriptions` query | 1 зайвий SQL per item | 0 |
| 21 | `ua_portal_design/helpers/ui.py` | `get_organization_image` — пряме ORM + кеш | `organization_show` call | `model.Group.get()` + dict cache |

### Фаза 2.1 — Session Rollback Safety

| # | Файл | Зміна |
|---|---|---|
| 22 | `tracking/model.py` | `try/except` + `meta.Session.rollback()` в bulk-методах |
| 23 | `tracking/plugin.py` | `try/except` навколо bulk-логіки в `after_dataset_search` |
| 24 | `ckan/views/group.py` | `Session.rollback()` в except для batch `_package_counts` |
| 25 | `ua_portal_design/plugin.py` | `Session.rollback()` в 5 except-блоках batch-запитів |

### Виправлені баги (знайдені при тестуванні)

| # | Файл | Баг | Виправлення |
|---|---|---|---|
| 26 | `nginx/setup/default.conf` | Cache bypass не враховував Flask-Login cookie `ckan` | Додано `$cookie_ckan` |
| 27 | `ckan/Dockerfile.production` | Prod-образ використовував `ckan.ini` (dev) замість `ckan_prod.ini` | Змінено COPY |
| 28 | `ua_portal_design/plugin.py` | SQL: `p.state` не існує в `ckanext_pages` | Видалено невалідну умову |

---

## 3. Порівняльна таблиця метрик

### 3.1 SQL-запити на одну сторінку

Виміряно на реальній базі даних (dev), усереднено по 5 запусків.

| Операція | Елементів | До (N+1) | Після (Bulk) | Прискорення |
|---|---|---|---|---|
| Tracking: перегляди пакетів | 16 | 5.40 ms (16 SQL) | 0.37 ms (1 SQL) | **14.8×** |
| Tracking: перегляди ресурсів | 48 | 14.78 ms (48 SQL) | 0.51 ms (1 SQL) | **28.9×** |
| Список організацій | 25 | 374.71 ms (25 action calls) | 12.03 ms (2 SQL) | **31.1×** |
| Template precompute (org + dash + api) | 16 | 286.82 ms (48+ SQL) | 1.29 ms (3 SQL) | **222.7×** |

### 3.2 Сумарний SQL overhead на сторінку `/dataset/`

| Метрика | До | Після | Різниця |
|---|---|---|---|
| Кількість SQL-запитів | ~130+ | ~8 | **-94%** |
| Загальний SQL overhead | ~680 ms | ~2.5 ms | **-99.6%** |
| DB з'єднань (concurrent) | Без пулу | 10 base + 20 overflow | Контрольований |

### 3.3 HTTP відповіді (dev, single worker)

| Сторінка | Час (avg 3 запити) | HTTP код |
|---|---|---|
| `/` (головна) | 261 ms | 200 |
| `/dataset/` (НД, 16 пакетів) | 503 ms | 200 |
| `/organization/` (25 організацій) | 240 ms | 200 |
| `/group/` (категорії) | 187 ms | 200 |
| `/api/3/action/package_search` | 22 ms | 200 |

### 3.4 Інфраструктурні зміни

| Метрика | До | Після |
|---|---|---|
| Gunicorn concurrent capacity | 4 запити (4 sync workers) | 16 запитів (4 workers × 4 threads) |
| Nginx cache для анонімних | Вимкнено | 5 хв (200), 1 хв (404) |
| Nginx → CKAN timeout | Default 60s (< Gunicorn 120s) | 130s (> Gunicorn 120s) |
| Webassets (CSS/JS) | Debug, нестиснуті | Minified, cached, munged |
| CKAN response cache | Вимкнено | 300 секунд |

---

## 4. Рекомендації для продакшн INI

### 4.1 Поточні налаштування Gunicorn

```
GUNICORN_CMD_ARGS=--bind=0.0.0.0:5000 --workers=4 --threads=4 --worker-class=gthread --timeout=120 --graceful-timeout=90 --keep-alive=5 --max-requests=1000 --max-requests-jitter=50
```

### 4.2 Формула розрахунку workers та threads

```
workers = (CPU_CORES × 2) + 1
threads = 4 (для I/O-bound CKAN)
max_concurrent = workers × threads
```

### 4.3 Рекомендовані значення залежно від CPU

| CPU cores | Workers | Threads | Max concurrent | `GUNICORN_CMD_ARGS` (додаткова частина) |
|---|---|---|---|---|
| 0.5 (stage) | 2 | 4 | 8 | `--workers=2 --threads=4` |
| 3 (stage limits) | 4 | 4 | 16 | `--workers=4 --threads=4` (поточне) |
| 4 | 9 | 4 | 36 | `--workers=9 --threads=4` |
| 8 | 17 | 4 | 68 | `--workers=17 --threads=4` |

### 4.4 SQLAlchemy pool — відповідність Gunicorn workers

Кожен Gunicorn worker має свій Python-процес зі своїм connection pool. Загальна кількість з'єднань до PostgreSQL:

```
total_connections = workers × (pool_size + max_overflow)
```

| Workers | pool_size | max_overflow | Max DB connections | PostgreSQL `max_connections` мінімум |
|---|---|---|---|---|
| 4 | 10 | 20 | 120 | 150 |
| 9 | 8 | 15 | 207 | 250 |
| 17 | 5 | 10 | 255 | 300 |

**Рекомендація для `ckan_prod.ini`:**

Для 4 workers (поточне):
```ini
sqlalchemy.pool_size = 10
sqlalchemy.max_overflow = 20
```

Для 9+ workers (якщо збільшити CPU):
```ini
sqlalchemy.pool_size = 8
sqlalchemy.max_overflow = 15
```

### 4.5 Celery workers

Celery теж використовує з'єднання до БД. Врахуйте:
```
total = gunicorn_workers × (pool_size + max_overflow) + celery_concurrency × 2
```

Поточне: `CELERY_WORKER_CONCURRENCY=4`, що додає ~8 з'єднань.

---

## 5. Рекомендації щодо характеристик серверу

### 5.1 Поточний Stage-сервер (Kubernetes)

```
Requests: CPU 500m, Memory 2Gi
Limits:   CPU 3,   Memory 4Gi
```

**Проблеми:**
- CPU requests 500m (0.5 ядра) — недостатньо навіть для 2 Gunicorn workers
- При burst до 3 CPU — нестабільна продуктивність (throttling)
- Memory 2Gi requests — мінімум, але достатньо для CKAN

### 5.2 Рекомендації для Stage (Kubernetes pod)

| Ресурс | Requests | Limits | Коментар |
|---|---|---|---|
| **CKAN app** | 1 CPU / 2Gi RAM | 3 CPU / 4Gi RAM | 4 workers × 4 threads |
| **PostgreSQL** | 1 CPU / 2Gi RAM | 2 CPU / 4Gi RAM | Основне навантаження від SQL |
| **Solr** | 0.5 CPU / 1Gi RAM | 1 CPU / 2Gi RAM | Пошукові запити |
| **Redis** | 0.25 CPU / 256Mi RAM | 0.5 CPU / 512Mi RAM | Кеш + Celery broker |
| **Nginx** | 0.25 CPU / 256Mi RAM | 0.5 CPU / 512Mi RAM | Reverse proxy + cache |

**Разом (requests/limits):** 3 CPU / 5.5Gi RAM → 7 CPU / 11Gi RAM

### 5.3 Рекомендації для Production (виділений сервер або VM)

Для стабільного обслуговування **100+ concurrent users**:

| Компонент | Мінімум | Рекомендовано | Коментар |
|---|---|---|---|
| **CPU** | 4 vCPU | 8 vCPU | `workers = (CPU×2)+1`, більше = більше concurrent |
| **RAM** | 8 GB | 16 GB | CKAN ~2GB, PostgreSQL ~4GB, Solr ~2GB, запас |
| **Диск** | 50 GB SSD | 100 GB NVMe SSD | PostgreSQL потребує швидкого I/O |
| **Мережа** | 1 Gbps | 1 Gbps+ | Для роздачі файлів через MinIO/S3 |

### 5.4 Розподіл ресурсів на 8 vCPU / 16 GB RAM

| Сервіс | CPU | RAM | Gunicorn config |
|---|---|---|---|
| **CKAN (Gunicorn)** | 4 cores | 4 GB | `--workers=9 --threads=4` (36 concurrent) |
| **PostgreSQL** | 2 cores | 6 GB | `shared_buffers=1.5GB, effective_cache_size=4GB` |
| **Solr** | 1 core | 3 GB | `-Xms1g -Xmx2g` |
| **Redis** | 0.25 core | 512 MB | Default |
| **Nginx** | 0.25 core | 256 MB | `worker_processes auto` |
| **Celery** | 0.5 core | 1 GB | `concurrency=4` |
| **Datapusher** | 0.25 core | 512 MB | Default |
| **Резерв OS** | ~0.75 core | ~1 GB | — |

### 5.5 PostgreSQL tuning для продакшн

```ini
# postgresql.conf (для 8 vCPU / 16 GB RAM)
max_connections = 200
shared_buffers = 1536MB          # ~25% RAM
effective_cache_size = 4096MB    # ~50% RAM
work_mem = 16MB
maintenance_work_mem = 256MB
wal_buffers = 64MB
random_page_cost = 1.1           # SSD
effective_io_concurrency = 200   # SSD
```

### 5.6 Порівняльна оцінка пропускної здатності

| Конфігурація | Max concurrent | Очікувана пропускна здатність |
|---|---|---|
| Stage (0.5 CPU, 4w×4t) | 16 | ~30-50 req/s |
| Prod мінімум (4 CPU, 9w×4t) | 36 | ~80-120 req/s |
| Prod рекомендовано (8 CPU, 17w×4t) | 68 | ~150-250 req/s |

> **Примітка:** Throughput залежить від складності сторінок, кількості даних та ефективності кешування. Наведені оцінки — для типових list/detail сторінок після оптимізації.

---

## 6. Чеклист для деплою

- [ ] Перебілдити Docker-образ (`docker-compose -f docker-compose.prod.yml build`)
- [ ] Перевірити що `ckan_prod.ini` використовується (`Dockerfile.production` → `COPY src/ckan_prod.ini`)
- [ ] Перевірити Nginx конфіг (таймаути, кеш, cookie bypass)
- [ ] Перевірити Gunicorn workers/threads в `.env_for_prod`
- [ ] Підлаштувати `sqlalchemy.pool_size` під кількість workers
- [ ] Перевірити PostgreSQL `max_connections` >= workers × (pool_size + max_overflow) + celery + резерв
- [ ] Очистити Nginx cache після деплою: `docker exec ckan-nginx rm -rf /tmp/nginx_cache/*`
- [ ] Моніторити логи перші 30 хвилин після деплою на предмет `InFailedSqlTransaction` або `Session.rollback`
