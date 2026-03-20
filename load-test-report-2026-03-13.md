# Звіт навантажувального тестування — 2026-03-13

**Дата тестування:** 2026-03-13, 08:30 — 09:30  
**Середовище:** Stage (Kubernetes), база `opendata_stg_ckan`  
**Інструменти моніторингу:** Grafana (PostgreSQL dashboards)

---

## 1. Загальний стан під час тестування

### 1.1 З'єднання з PostgreSQL (Connections Overview)

| Метрика | Фонове значення (08:30) | Пікове значення (08:45—09:00) | Після піку (09:30) |
|---|---|---|---|
| **Total** | ~20 | **133** | ~75 |
| **idle** | ~15 | **73** | ~70 |
| **idle in transaction** | ~2 | **64** | ~0 |
| **active** | ~2 | **7** | ~2 |
| **disabled** | 0 | 0 | 0 |

Знімок стану з'єднань на **08:51:30** (момент найбільшого навантаження):

| Стан | Кількість |
|---|---|
| Total | 95 |
| idle in transaction | 63 |
| idle | 28 |
| active | 4 |

**Висновок:** 66% усіх з'єднань перебували у стані "idle in transaction" — транзакції були відкриті, але не виконували жодних запитів і не звільняли блокування.

---

### 1.2 Блокування (Number of Locks)

| Тип блокування | База | Пікове значення |
|---|---|---|
| accesssharelock | opendata_stg_ckan | ~3 000 |
| accesssharelock | postgres | ~200 |
| rowexclusivelock | opendata_stg_ckan | ~500 |
| accesssharelock | opendata_stg_datastore | ~100 |
| accesssharelock | opendata_stg_keycloak | ~50 |
| accessexclusivelock | opendata_stg_ckan | ~10 |

**Хронологія:**
- 08:30 — блокувань практично немає
- 08:45 — різке зростання до ~3 000 блокувань
- 09:00 — спад до ~0
- 09:00—09:30 — блокування відсутні

**Висновок:** Пік блокувань точно корелює з піком "idle in transaction" з'єднань. Транзакції, що перебувають у стані idle in transaction, утримують AccessShareLock та RowExclusiveLock, не дозволяючи їх звільнити до завершення транзакції.

---

### 1.3 Найповільніші запити (Top Queries by Query Time)

| # | Запит (скорочено) | Час виконання | QPS | Аналіз |
|---|---|---|---|---|
| 1 | `SELECT CASE WHEN r.extras IS NULL OR r.extras = '' THEN 'approved' ELSE COALE...` | **465.15 ms** | <0.01 | Запит модерації ресурсів (res_has_*) |
| 2 | `SELECT package_extra.value AS category_code, resource.extras AS extras FROM pa...` | **373.26 ms** | <0.01 | Диктизація пакетів з extras |
| 3 | `SELECT package.id AS package_id, package.name AS package_name, package.title...` | **118.34 ms** | 0.01 | Основний запит пакетів |
| 4 | `SELECT package_extra.value AS category_code, resource.extras AS extras FROM pa...` | **84.08 ms** | <0.01 | Варіант запиту #2 |
| 5 | `SELECT package.id, package.metadata_modified, resource.extras FROM package J...` | **58.42 ms** | <0.01 | Запит метаданих пакетів |
| 6 | `SELECT COUNT(DISTINCT p.id) FROM package p JOIN package_extra pe ON p.id = ...` | **41.90 ms** | <0.01 | Підрахунок пакетів з фільтрацією |
| 7 | `SELECT p.id, p.title, p.name FROM package p WHERE p.type = $1 AND p.state = $2...` | **31.24 ms** | <0.01 | Вибірка пакетів за типом/станом |
| 8 | `SELECT categories.id, categories.code, categories.name, categories.created_at, cat...` | **29.27 ms** | <0.01 | Запит категорій |
| 9 | `SELECT /* agent='pgstatstatements' */ "pg_stat_statements"."userid"...` | **25.28 ms** | 0.02 | Моніторинг (pgstatstatements) |

**Висновок:** Запити #1 та #2 — найповільніші, обидва пов'язані з обробкою поля `resource.extras` (JSON/текстове поле без індексу). Запит #1 безпосередньо стосується логіки визначення статусу модерації ресурсів.

---

### 1.4 Найчастіші запити (Top Queries by Query Count)

| # | Запит (скорочено) | Час виконання | QPS | Аналіз |
|---|---|---|---|---|
| 1 | `SELECT pg_database.datname, pg_database_size(pg_database.datname) as bytes F...` | 1.02 ms | 0.30 | Моніторинг розміру БД |
| 2 | `SELECT pg_database_size($1)` | 2.83 ms | 0.80 | Моніторинг розміру БД |
| 3 | `SELECT package.id AS package_id, package.name AS package_name, package.title...` | **118.34 ms** | 0.01 | Запит пакетів (повільний) |
| 4 | `SELECT name, setting, COALESCE(unit, $1), short_desc, vartype FROM pg_settings...` | 3.54 ms | 0.20 | Моніторинг налаштувань |
| 5 | `SELECT /* agent='pgstatstatements' */...` | 25.28 ms | 0.02 | Моніторинг |
| 6 | `SELECT name, default_version, installed_version FROM pg_available_extensions` | 1.49 ms | — | Моніторинг |
| 7 | `SELECT blockinga.pid AS blocking_pid, count(*) as count FROM pg_catalog.pg_lock...` | 1.10 ms | — | Моніторинг блокувань |
| 8 | `SELECT count(*) AS count_1 FROM (SELECT package.id AS package_id, package_na...` | **18.49 ms** | 0.01 | Підрахунок пакетів |
| 9 | `SELECT pg_database.datname, tmp.state, tmp2.usename, tmp2.application_name, C...` | 964.06 us | 0.20 | Моніторинг з'єднань |

**Висновок:** Більшість частих запитів — це запити моніторингу Grafana/pg_stat_statements. Прикладні запити (пакети) мають низький QPS (<0.01—0.01), але високий час виконання, що свідчить про їх рідкісний, але важкий характер.

---

## 2. Кореляція з кодом

### 2.1 Функція `_do_reindex` — джерело проблеми idle in transaction

Файл: `ckanext/ua_portal_design/models/res_moderation_index_init.py`, рядки 139—196.

Функція `_do_reindex` виконує переіндексацію пакетів у фоновому потоці. Виявлені проблеми:

**Проблема 1 — Одна довга транзакція на весь цикл:**

Весь цикл `for pkg_id in package_ids` виконується всередині одного `app.test_request_context()`. SQLAlchemy `model.Session` відкриває транзакцію при першому запиті і тримає її до кінця контексту. Для сотень або тисяч пакетів це означає транзакцію тривалістю у хвилини.

```python
with app.test_request_context():
    package_index = PackageSearchIndex()
    for pkg_id in package_ids:        # <-- сотні ітерацій в одній транзакції
        pkg = model.Session.query(model.Package).filter_by(id=pkg_id).first()
        pkg_dict = model_dictize.package_dictize(pkg, context)
        package_index.index_package(pkg_dict)
```

**Проблема 2 — Відсутність очищення сесії:**

Між ітераціями немає `model.Session.remove()`, `model.Session.rollback()` або `model.Session.expire_all()`. Це призводить до:
- Зростання identity map сесії (усі завантажені об'єкти залишаються в пам'яті)
- Утримання блокувань PostgreSQL на всі прочитані рядки
- Стан "idle in transaction" для з'єднання під час пауз між ітераціями

**Проблема 3 — `test_request_context()` у фоновому потоці:**

Використання `app.test_request_context()` створює окремий Flask-контекст, але scoped session SQLAlchemy прив'язана до потоку. Це працює коректно для одного фонового потоку, але у поєднанні з тривалою транзакцією створює з'єднання, яке PostgreSQL бачить як "idle in transaction" протягом усього часу переіндексації.

### 2.2 Запит модерації ресурсів (465 мс)

Запит #1 з топу повільних:
```sql
SELECT CASE WHEN r.extras IS NULL OR r.extras = '' 
       THEN 'approved' 
       ELSE COALE...
```

Це запит, що визначає статус модерації ресурсу на основі поля `resource.extras`. Час 465 мс свідчить про:
- Відсутність індексу на полі `resource.extras`
- Повне сканування текстового/JSON поля для кожного ресурсу
- Можливе блокування через конкуренцію з переіндексацією (RowExclusiveLock)

### 2.3 Запити диктизації пакетів (373 мс, 84 мс)

Запити #2 та #4 (`package_extra.value AS category_code, resource.extras`) — це частина `model_dictize.package_dictize()`, що викликається для кожного пакету у `_do_reindex`. Повільність зумовлена:
- Lazy loading зв'язаних об'єктів (resources, extras) — окремий SQL для кожного зв'язку
- Відсутність eager loading (joinedload/subqueryload) при завантаженні пакету

---

## 3. Хронологія інциденту

```
08:30       Фоновий стан: ~20 з'єднань, ~0 locks, 2 active
08:40       Запуск ensure_res_moderation_indexed() при старті CKAN worker
08:40-08:45 _do_reindex починає ітерувати по package_ids
            Зростання: з'єднання idle in transaction -> 30, 40, 50...
08:45       Locks різко зростають до ~3 000 (accesssharelock + rowexclusivelock)
            idle in transaction досягає 63-64
            Total з'єднань: 95-133
08:51:30    Знімок: 95 total, 63 idle in transaction, 28 idle, 4 active
09:00       Переіндексація завершується, locks падають до ~0
            idle in transaction починає зменшуватись
09:00-09:30 З'єднання поступово повертаються у стан idle
            Total стабілізується на ~75
```

---

## 4. Ідентифіковані проблеми (за критичністю)

### Критичний рівень

| # | Проблема | Прояв | Причина |
|---|---|---|---|
| 1 | Масове накопичення idle in transaction з'єднань | 64 з'єднання у стані idle in transaction (66% від загальної кількості) | `_do_reindex` тримає одну транзакцію на весь цикл без `Session.remove()` між ітераціями |
| 2 | Пік блокувань ~3 000 | AccessShareLock та RowExclusiveLock утримуються idle-транзакціями | Транзакції не завершуються → locks не звільняються → каскадне блокування |
| 3 | Вичерпання пулу з'єднань | Total з'єднань = 133 (при pool_size=10, max_overflow=20 на worker) | Довготривалі транзакції займають з'єднання з пулу, нові запити вимушені створювати overflow-з'єднання |

### Високий рівень

| # | Проблема | Прояв | Причина |
|---|---|---|---|
| 4 | Запит модерації ресурсів — 465 мс | Найповільніший запит у системі | Парсинг текстового поля `resource.extras` без індексу |
| 5 | Диктизація пакетів — 373 мс | Другий за повільністю запит | Lazy loading зв'язаних об'єктів (N+1 на рівні ORM) |
| 6 | Відсутність батчевого очищення identity map | Зростання споживання пам'яті у фоновому потоці | Всі завантажені ORM-об'єкти залишаються в сесії до кінця циклу |

### Середній рівень

| # | Проблема | Прояв | Причина |
|---|---|---|---|
| 7 | Блокування автовакууму PostgreSQL | Потенційне зростання dead tuples та bloat таблиць | idle in transaction з'єднання блокують autovacuum |
| 8 | З'єднання не повертаються у пул вчасно | Після завершення піку, total залишається ~75 (замість ~20) | Overflow-з'єднання повільно закриваються через pool_recycle |

---

## 5. Рекомендації щодо виправлення

### 5.1 Батчевий Session.remove() у _do_reindex

Додати періодичне очищення сесії кожні N пакетів (рекомендовано: 20-50):

```python
for i, pkg_id in enumerate(package_ids):
    try:
        pkg = model.Session.query(model.Package).filter_by(id=pkg_id).first()
        # ... dictize + index ...
    except Exception as e:
        failed += 1

    if (i + 1) % 50 == 0:
        model.Session.remove()
```

Це забезпечить:
- Завершення поточної транзакції та звільнення блокувань
- Повернення з'єднання у пул
- Очищення identity map та звільнення пам'яті

### 5.2 Індекс на resource.extras для запиту модерації

Створити функціональний індекс для прискорення запиту статусу модерації:

```sql
CREATE INDEX idx_resource_extras_moderation 
ON resource USING btree (
    CASE WHEN extras IS NULL OR extras = '' THEN 'approved' 
         ELSE extras::text END
);
```

Або, якщо extras — це JSON:

```sql
CREATE INDEX idx_resource_extras_gin ON resource USING gin (extras::jsonb);
```

### 5.3 Eager loading для package_dictize

При завантаженні пакету для переіндексації використовувати joinedload:

```python
from sqlalchemy.orm import joinedload

pkg = (model.Session.query(model.Package)
       .options(joinedload(model.Package.resources))
       .options(joinedload(model.Package.extras))
       .filter_by(id=pkg_id)
       .first())
```

### 5.4 Обмеження швидкості переіндексації

Додати `time.sleep()` між батчами для зменшення навантаження на PostgreSQL під час переіндексації:

```python
if (i + 1) % 50 == 0:
    model.Session.remove()
    time.sleep(0.5)
```

---

## 6. Зв'язок з попередніми оптимізаціями

Цей звіт доповнює `performance-optimization-report.md` (2026-03-05), де було виправлено:
- N+1 запити на сторінках `/dataset/`, `/organization/`, `/group/`
- Конфігурацію Gunicorn (workers, threads)
- SQLAlchemy connection pool
- Nginx caching та proxy timeouts

Поточне тестування виявило нову проблему — фонова переіндексація `res_has_*` полів створює надмірне навантаження на PostgreSQL через утримання довготривалих транзакцій. Ця проблема не була помітна при попередньому тестуванні, оскільки проявляється лише при старті CKAN з неповним індексом Solr.

---

## 7. Метрики для перевірки після виправлення

| Метрика | Поточне значення (пік) | Цільове значення |
|---|---|---|
| idle in transaction з'єднань | 64 | 0—2 |
| Максимум блокувань | ~3 000 | <100 |
| Total з'єднань при переіндексації | 133 | <40 |
| Час запиту модерації ресурсів | 465 мс | <50 мс |
| Час диктизації пакету | 373 мс | <50 мс |
