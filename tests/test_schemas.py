import datetime

from netschoolapi_plus import schemas


def test_diary_schema_loads_week():
    schema = schemas.DiarySchema()
    schema.context["assignment_types"] = {2: "Контрольная работа"}
    diary = schema.load({
        "weekStart": "2026-09-15T00:00:00",
        "weekEnd": "2026-09-20T00:00:00",
        "weekDays": [
            {
                "date": "2026-09-15T00:00:00",
                "lessons": [
                    {
                        "day": "2026-09-15T00:00:00",
                        "startTime": "09:00:00",
                        "endTime": "09:45:00",
                        "number": 1,
                        "subjectName": "Математика",
                        "assignments": [
                            {
                                "id": 1,
                                "assignmentName": "Контрольная №1",
                                "typeId": 2,
                                "dueDate": "2026-09-15T00:00:00",
                                "mark": {
                                    "mark": 5,
                                    "dutyMark": False,
                                },
                            }
                        ],
                    }
                ],
            }
        ],
    })

    assert isinstance(diary, schemas.Diary)
    days = diary.schedule
    assert len(days) == 1
    assert days[0].day == datetime.date(2026, 9, 15)
    lesson = days[0].lessons[0]
    assert lesson.subject == "Математика"
    assert lesson.assignments[0].mark == 5
    assert lesson.assignments[0].type == "Контрольная работа"


def test_assignment_unwraps_mark_comment():
    data = {
        "id": 2,
        "assignmentName": "Домашняя работа",
        "typeId": 1,
        "dueDate": "2026-09-15T00:00:00",
        "mark": {"mark": 4, "dutyMark": False},
        "markComment": {"name": "Хорошо"},
    }
    schema = schemas.AssignmentSchema()
    schema.context["assignment_types"] = {1: "Домашняя работа"}
    a = schema.load(data)
    assert a.mark == 4
    assert a.comment == "Хорошо"


def test_schema_metadata_mapping():
    assert schemas.Lesson.__dataclass_fields__["subject"].metadata["data_key"] == "subjectName"
    assert schemas.Day.__dataclass_fields__["day"].metadata["data_key"] == "date"
    assert schemas.Diary.__dataclass_fields__["schedule"].metadata["data_key"] == "weekDays"