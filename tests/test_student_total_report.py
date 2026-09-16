import datetime
from pathlib import Path

import pytest

from netschoolapi_plus import schemas
from netschoolapi_plus.report_parser import parse_student_total_report

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_student_total_report_full():
    html = load_fixture("report_studenttotal.html")

    report = parse_student_total_report(html)

    assert isinstance(report, schemas.StudentTotalReport)
    assert report.school == 'МОУ "Лицей № 4"'
    assert report.student == "Пронюшкин Егор Николаевич"
    assert report.year == "2026/2027"
    assert report.period_start == datetime.date(2026, 9, 1)
    assert report.period_end == datetime.date(2026, 11, 30)
    assert report.term == "1 триместр"

    assert len(report.subjects) == 18
    subjects = {s.subject: s for s in report.subjects}

    english = subjects["Ин.яз./Английский язык"]
    assert english.average == pytest.approx(4.33)
    assert english.final is None
    assert english.marks == {
        datetime.date(2026, 9, 4): "4",
        datetime.date(2026, 9, 8): "4",
        datetime.date(2026, 9, 11): "5",
    }

    literature = subjects["Литература"]
    assert literature.average == pytest.approx(2.5)
    assert literature.marks == {
        datetime.date(2026, 9, 2): "3",
        datetime.date(2026, 9, 16): "2",
    }

    algebra = subjects["Алгебра"]
    assert algebra.average == 4.0
    assert algebra.marks == {
        datetime.date(2026, 9, 4): "5",
        datetime.date(2026, 9, 11): "3",
    }

    biology = subjects["Биология"]
    assert biology.average == 5.0
    assert biology.marks == {datetime.date(2026, 9, 16): "5"}

    physics = subjects["Физика"]
    assert physics.marks == {datetime.date(2026, 9, 9): "5"}

    geometry = subjects["Геометрия"]
    assert geometry.marks == {datetime.date(2026, 9, 10): "5"}

    history = subjects["История"]
    assert history.marks == {datetime.date(2026, 9, 16): "3"}

    pe = subjects["Физкультура"]
    assert pe.marks == {datetime.date(2026, 9, 9): "4"}

    for name in ("Вероятность и статистика", "Русский язык", "Химия",
                 "Информатика", "Обществознание", "География"):
        assert subjects[name].marks == {}
        assert subjects[name].average is None
        assert subjects[name].final is None


def test_parse_student_total_report_absent_codes_and_multi_month():
    html = """<div>
        <h5 class="report-title-school">Школа</h5>
        <h2 class="main-report-title">Отчет об успеваемости и посещаемости ученика</h2>
    </div>
    <table cellspacing="10px">
        <tr>
            <td class="no-border"><span class="select"><b>Учебный год:</b>
                2026/2027</span></td>
        </tr>
        <tr>
            <td class="no-border"><span class="select"><b>Период:</b>
                с 1.09.2026 по 31.10.2026</span></td>
        </tr>
        <tr>
            <td class="no-border"><span class="select" data-sheet-name="Ученик Тестович">
                <b>Ученик:</b> Ученик Тестович</span></td>
        </tr>
    </table>
    <table class="table-print">
        <tr>
            <th rowspan="2">Предмет</th>
            <th colspan="2">Сентябрь</th>
            <th colspan="2">Октябрь</th>
            <th rowspan="2">Средн.<br/>оценка <br/> 1 триместр</th>
            <th rowspan="2">Итог.оценка <br/> 1 триместр</th>
        </tr>
        <tr>
            <th>2</th><th>15</th><th>2</th><th>16</th>
        </tr>
        <tr>
            <td class="cell-text">Математика</td>
            <td>УП</td><td>4</td><td>Б</td><td>5</td>
            <td class="cell-num-2">4,5</td>
            <td class="cell-num-2">5</td>
        </tr>
    </table>"""

    report = parse_student_total_report(html)

    assert report.school == "Школа"
    assert report.student == "Ученик Тестович"
    assert report.term == "1 триместр"

    subject = report.subjects[0]
    assert subject.marks == {
        datetime.date(2026, 9, 2): "УП",
        datetime.date(2026, 9, 15): "4",
        datetime.date(2026, 10, 2): "Б",
        datetime.date(2026, 10, 16): "5",
    }
    assert subject.average == pytest.approx(4.5)
    assert subject.final == "5"


def test_parse_student_total_report_minimal():
    html = """<div>
        <h5 class="report-title-school">Школа</h5>
    </div>
    <table class="table-print">
        <tr>
            <th rowspan="2">Предмет</th>
            <th colspan="1">Сентябрь</th>
            <th rowspan="2">Средн.оценка</th>
            <th rowspan="2">Итог.оценка</th>
        </tr>
        <tr><th>1</th></tr>
        <tr>
            <td class="cell-text">Предмет</td>
            <td></td>
            <td class="cell-num-2"></td>
            <td class="cell-num-2"></td>
        </tr>
    </table>"""

    report = parse_student_total_report(html)

    assert report.school == "Школа"
    assert len(report.subjects) == 1
    assert report.subjects[0].marks == {}
    assert report.subjects[0].average is None
    assert report.subjects[0].final is None