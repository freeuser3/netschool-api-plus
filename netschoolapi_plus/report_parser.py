import datetime
import re
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

from netschoolapi_plus import schemas

__all__ = ['parse_student_total_report']

MONTHS = {
    'январь': 1, 'февраль': 2, 'март': 3, 'апрель': 4,
    'май': 5, 'июнь': 6, 'июль': 7, 'август': 8,
    'сентябрь': 9, 'октябрь': 10, 'ноябрь': 11, 'декабрь': 12,
}

_TERM_RE = re.compile(r'оценка\s*(.*)', re.IGNORECASE)
_PERIOD_RE = re.compile(
    r'с\s+(\d{1,2})\.(\d{1,2})\.(\d{4})\s+по\s+(\d{1,2})\.(\d{1,2})\.(\d{4})',
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r'(\d{4})/(\d{4})')


def _text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


def _parse_float(value: str) -> Optional[float]:
    value = value.strip()
    if not value:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _parse_date(day: str, month: str, year: int) -> Optional[datetime.date]:
    try:
        return datetime.date(year, MONTHS[month.lower()], int(day))
    except (KeyError, ValueError):
        return None


def _header_columns(table) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """Return (list of (day, month) column headers, term label)."""
    rows = table.select("tr")
    if len(rows) < 2:
        return [], None

    first_row_cells = rows[0].find_all("th")
    second_row_cells = rows[1].find_all("th")

    months: List[str] = []
    colspans: List[int] = []
    term = None
    for cell in first_row_cells:
        text = _text(cell)
        if cell.get("rowspan"):
            if "оценка" in text.lower():
                label_match = _TERM_RE.search(text)
                if label_match:
                    term = label_match.group(1).strip()
        else:
            months.append(text)
            colspans.append(int(cell.get("colspan") or 1))

    if not months:
        return [], term

    day_index = 0
    columns: List[Tuple[str, str]] = []
    for month, colspan in zip(months, colspans):
        for _ in range(colspan):
            day = _text(second_row_cells[day_index]) if day_index < len(second_row_cells) else ""
            columns.append((day, month))
            day_index += 1
    return columns, term


def _subject_rows(table, total_columns: int):
    """Yield parsed subject rows: name, day cells, average cell, final cell."""
    rows = table.select("tr")
    for row in rows[2:]:
        cells = row.find_all("td")
        if not cells:
            continue
        name_cell = cells[0]
        if not name_cell.get("class") or "cell-text" not in name_cell.get("class"):
            continue
        day_cells = cells[1 : 1 + total_columns]
        rest = cells[1 + total_columns :]
        avg = None
        final = None
        for cell in rest:
            if cell.get("class") and "cell-num-2" in cell.get("class"):
                if avg is None:
                    avg = cell
                else:
                    final = cell
        yield {
            "name": _text(name_cell),
            "day_cells": day_cells,
            "average": _text(avg) if avg else "",
            "final": _text(final) if final else "",
        }


def parse_student_total_report(html: str) -> schemas.StudentTotalReport:
    soup = BeautifulSoup(html, "html.parser")

    school = _text(soup.select_one(".report-title-school"))
    full_text = soup.get_text(" ", strip=True)

    student = ""
    student_span = soup.select_one("span[data-sheet-name]")
    if student_span:
        student = student_span.get("data-sheet-name")

    year = ""
    year_match = _YEAR_RE.search(full_text)
    if year_match:
        year = f"{year_match.group(1)}/{year_match.group(2)}"

    period_start = None
    period_end = None
    period_match = _PERIOD_RE.search(full_text)
    if period_match:
        period_start = datetime.date(
            int(period_match.group(3)), int(period_match.group(2)),
            int(period_match.group(1)),
        )
        period_end = datetime.date(
            int(period_match.group(6)), int(period_match.group(5)),
            int(period_match.group(4)),
        )

    table = None
    for candidate in soup.select("table.table-print"):
        table = candidate
        break
    if not table:
        return schemas.StudentTotalReport(
            school=school, student=student, year=year,
            period_start=period_start, period_end=period_end,
        )

    columns, term = _header_columns(table)
    year_from_period = (
        period_start.year
        if period_start is not None else
        (int(year_match.group(1)) if year_match else datetime.date.today().year)
    )

    subjects: List[schemas.SubjectReport] = []
    for row in _subject_rows(table, len(columns)):
        marks: Dict[datetime.date, str] = {}
        for (day, month), cell in zip(columns, row["day_cells"]):
            value = _text(cell)
            if not value:
                continue
            parsed_date = _parse_date(day, month, year_from_period)
            if parsed_date is not None:
                marks[parsed_date] = value
        subjects.append(schemas.SubjectReport(
            subject=row["name"],
            marks=marks,
            average=_parse_float(row["average"]),
            final=row["final"].strip() or None,
        ))

    return schemas.StudentTotalReport(
        school=school, student=student, year=year,
        period_start=period_start, period_end=period_end,
        term=term or "", subjects=subjects,
    )