# netschoolapi-plus

Форк библиотеки [netschoolapi](https://github.com/nm17/netschoolapi) (автор — nm17, лицензия MIT).

NetSchoolAPI — это асинхронный клиент для «Сетевого города», который может получить дневник с домашними заданиями и оценками, объявления и просроченные задания.

> Отдельная разработка на базе оригинала: исходный код расширяется новыми возможностями (скорректированы импорты под пакет `netschoolapi_plus`).

## Установка (dev, editable)

```bash
uv venv .venv --python 3.11
uv pip install -e .
```

## Использование

```python
from netschoolapi_plus import NetSchoolAPI

ns = NetSchoolAPI("https://sgo.e-mordovia.ru")
await ns.login("user", "pass", "school")
diary = await ns.diary(start, end)
```

## Отличие от оригинала

- пакет переименован в `netschoolapi_plus` → не конфликтует при параллельной установке оригинала;
- upstream: https://github.com/nm17/netschoolapi

## Лицензия

MIT ([LICENSE](LICENSE)).