# Спецификация методов netschoolapi-plus

Класс `NetSchoolAPI`, файл `netschoolapi_plus/netschoolapi.py`.

## Конструктор

```python
NetSchoolAPI(url: str, default_requests_timeout: int = None)
```

Создаёт HTTP-клиент с базовым адресом `{url}/webapi`. Используется как async:
`async with NetSchoolAPI(url) as ns:` — при выходе из контекста автоматически вызывается `logout()`.

## Публичные методы

### `login(user_name, password, school_name_or_id, requests_timeout=None)`

Авторизация в Сетевом городе.

- `user_name` — логин; `password` — пароль.
- `school_name_or_id` — id школы (`int`) либо название (`str`). При строке школа ищется по `schools/search?name=`, при совпадении `shortName` сохраняется `_school_id` и `_school_name`.
- Протокол: `logindata` (кука `NSSESSIONID`) → `auth/getdata` (получение `salt`) → `login` с md5-хешем пароля в `windows-1251`.
- При успехе сохраняет `at`-токен, `_student_id`, `_year_id` и справочник типов заданий (`grade/assignment/types`), который используется для распаковки поля `Assignment.type`.

Исключения: `AuthError` (неверные учётные данные или 409 с сообщением), `SchoolNotFoundError` (школа не найдена).

### `logout(requests_timeout=None)`

Завершение сессии. POST `auth/logout`. Ответ 401 игнорируется (сессия уже мертва), остальные ошибки пробрасываются.

### `full_logout(requests_timeout=None)`

`logout()` + закрытие HTTP-клиента (`aclose()`). Используется при полном завершении работы.

### `diary(start=None, end=None, requests_timeout=None) -> schemas.Diary`

Дневник за период.

- По умолчанию: текущая неделя (понедельник → +5 дней).
- GET `student/diary` с параметрами `studentId`, `yearId`, `weekStart`, `weekEnd`.
- Возвращает `Diary` с полем `schedule: List[Day]`. В каждом дне `lessons: List[Lesson]`, у уроков `assignments` (оценки, домашние задания). Тип задания (`Assignment.type`) — строка, например «Домашнее задание», «Ответ на уроке».

### `overdue(start=None, end=None, requests_timeout=None) -> List[schemas.Assignment]`

Просроченные задания (заданные, но без отметки к сроку).

- По умолчанию: текущая неделя (+5 дней).
- GET `student/diary/pastMandatory`, те же параметры, что у `diary()`.
- Возвращает список `Assignment`.

### `attachments(assignment_id, requests_timeout=None) -> List[schemas.Attachment]`

Вложения к заданию.

- POST `student/diary/get-attachments` с телом `{"assignId": [assignment_id]}`.
- Возвращает `Attachment(id, name, description)`. `name` — имя файла (`originalFileName`), по нему можно определять тип файла без скачивания.
- Примечание: поле `id` в форке сделано необязательным (commit `d1caaed`) — сервер может присылать `attachmentGuid` вместо `id`.

### `download_attachment(attachment_id, buffer, requests_timeout=None)`

Скачивание файла вложения.

- GET `attachments/{attachment_id}`; байты записываются в переданный `BytesIO`.

### `announcements(take=-1, requests_timeout=None) -> List[schemas.Announcement]`

Объявления. GET `announcements`, `take` — сколько взять (по умолчанию все).

### `school(requests_timeout=None) -> schemas.School`

Карточка школы. GET `schools/{id}/card`.

### `schools(requests_timeout=None) -> List[schemas.ShortSchool]`

Поиск школ. GET `schools/search?name=У` — имя захардкожено оригиналом; для поиска по названию предпочтителен `_get_school_id`.

### `report_file(start=None, end=None, requests_timeout=None) -> str`

Отчёт «Студент» в виде сырого HTML.

- Цепочка запросов:
  1. GET `reports/studenttotal` — получение списка фильтров.
  2. POST `reports/studenttotal/queue` — создание задачи.
  3. WebSocket `signalr/queueHub?at=...` — ожидание `fileId` (target `startTask`).
  4. GET `files/{fileId}` — результат.
- Если `start`/`end` не заданы (или частично), период берётся из серверного `defaultValue` фильтра `period` — то есть используются границы текущего триместра (изменение форка, commit `8c75c63`).

### `report_studenttotal(start=None, end=None, requests_timeout=None) -> schemas.StudentTotalReport`

HTML от `report_file`, распарсенный в структуру:

- `StudentTotalReport` — `school`, `student`, `year`, `period_start`, `period_end`, `term`, `subjects`.
- `SubjectReport` — `subject`, `marks: Dict[date, str]`, `average: float | None`, `final: str | None`.

Интерпретация преобразуется из стороннего HTML (добавлено в форке, commit `b840413`; проброс `None` дат — commit `b376595`).

### `download_profile_picture(user_id, buffer, requests_timeout=None)`

Аватар пользователя. GET `users/photo?at=...&userId=...`; байты записываются в переданный `BytesIO`.

## Внутренние методы

### `_request_with_optional_relogin(requests_timeout, request, follow_redirects=False)`

Выполняет HTTP-запрос через клиент. При `401 Unauthorized` повторно выполняет `login()` (если сохранены `_login_data`) и retry. Без авторизации выбрасывает `AuthError`.

### `_get_school_id(school_name, requester)`

Поиск id школы по точному `shortName` через `schools/search?name=...`. Заполняет `_school_id` и `_school_name`. Если школа не найдена — `SchoolNotFoundError`.

## Служебные поля

- `_student_id`, `_year_id`, `_school_id`, `_school_name` — контекст текущего аккаунта.
- `_access_token` — токен `at`, проставляется в заголовки клиента.
- `_assignment_types: Dict[int, str]` — справочник «id типа → название».
- `_login_data` — сохранённые креды для автоматического релогина.

## Исключения (`netschoolapi_plus/errors`)

- `AuthError` — неверный логин/пароль/школа либо истёкшая сессия.
- `SchoolNotFoundError` — школа не найдена при поиске по названию.

Остальные ошибки пробрасываются как `httpx`-исключения.