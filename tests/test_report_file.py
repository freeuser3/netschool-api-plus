import asyncio
import datetime
import json
from unittest.mock import patch

from httpx import AsyncClient

from netschoolapi_plus import NetSchoolAPI


class FakeSocket:
    def __init__(self, chunks):
        self._chunks = chunks
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        return self._chunks.pop(0)


class FakeResponse:
    is_redirect = False

    def __init__(self, json_data=None, text=""):
        self._json = json_data
        self.text = text

    def json(self):
        return self._json

    def raise_for_status(self):
        pass


class FakeClient:
    def __init__(self, url, responses):
        self._base = AsyncClient(base_url=f"{url}/webapi")
        self._responses = responses
        self.requests = []

    @property
    def cookies(self):
        return self._base.cookies

    def build_request(self, method, url, **kwargs):
        return self._base.build_request(method, url, **kwargs)

    async def send(self, request, follow_redirects=False):
        self.requests.append(request)
        return self._responses[request.url.path]


def test_report_file_generates_official_report_via_websocket():
    filter_sources = [
        {"filterId": "SID", "defaultValue": "562093"},
        {"filterId": "PCLID", "defaultValue": "92540"},
        {"filterId": "TERMID", "defaultValue": "24816"},
        {
            "filterId": "period",
            "defaultValue": "2026-09-01T00:00:00.0000000 - "
                             "2026-09-30T00:00:00.0000000",
        },
    ]
    responses = {
        "/webapi/reports/studenttotal": FakeResponse(
            json_data={"filterSources": filter_sources}
        ),
        "/webapi/reports/studenttotal/queue": FakeResponse(json_data={
            "taskId": 10276200,
            "queueKey": "report-v2",
        }),
        "/webapi/files/file123": FakeResponse(text="<html>official report</html>"),
    }
    fake = FakeClient("https://sgo.example", responses)

    socket = FakeSocket([
        "{}\x1e",
        '{"type":3,"invocationId":"0","result":{"success":true}}\x1e',
        '{"type":1,"target":"progress","arguments":[{"taskId":10276200,'
        '"status":"forming"}]}\x1e',
        '{"type":1,"target":"complete","arguments":[{"taskId":10276200,'
        '"data":"file123","componentId":"xyz"}]}\x1e',
        '{"type":6}\x1e',
        '{"type":6}\x1e',
    ])

    def fake_connect(url, **kwargs):
        fake.url = url
        fake.additional_headers = kwargs.get("additional_headers")
        fake.open_timeout = kwargs.get("open_timeout")
        return socket

    ns = NetSchoolAPI("https://sgo.example")
    ns._wrapped_client.client = fake
    ns._ver = "999"
    ns._school_name = "МОУ Лицей №4"
    ns._year_id = 7207
    ns._access_token = "at123"

    with patch("netschoolapi_plus.netschoolapi.connect", fake_connect):
        html = asyncio.run(ns.report_file(
            datetime.date(2026, 9, 1), datetime.date(2026, 9, 30)
        ))

    assert html == "<html>official report</html>"

    paths = [request.url.path for request in fake.requests]
    assert paths == [
        "/webapi/reports/studenttotal",
        "/webapi/reports/studenttotal/queue",
        "/webapi/files/file123",
    ]

    assert fake.url == (
        "wss://sgo.example/signalr/queueHub?at=at123"
    )
    assert fake.open_timeout == 15

    payload = json.loads(fake.requests[1].content)
    assert payload["selectedData"] == [
        {"filterId": "SID", "filterValue": "562093"},
        {"filterId": "PCLID", "filterValue": "92540"},
        {"filterId": "TERMID", "filterValue": "24816"},
        {"filterId": "period",
         "filterValue": "2026-09-01T00:00:00.000Z - "
                        "2026-09-30T00:00:00.000Z"},
    ]
    assert payload["params"] == [
        {"name": "SCHOOLYEARID", "value": "7207"},
        {"name": "SERVERTIMEZONE", "value": 3},
        {"name": "FULLSCHOOLNAME", "value": "МОУ Лицей №4"},
        {"name": "DATEFORMAT", "value": "d\x01mm\x01yyyy\x01."},
    ]

    assert socket.sent[0] == '{"protocol":"json","version":1}\x1e'
    start_task = json.loads(socket.sent[1].rstrip("\x1e"))
    assert start_task == {
        "arguments": [10276200, "report-v2"],
        "invocationId": "0",
        "target": "startTask",
        "type": 1,
    }


def test_report_file_uses_server_period_when_dates_omitted():
    filter_sources = [
        {"filterId": "SID", "defaultValue": "562093"},
        {"filterId": "PCLID", "defaultValue": "92540"},
        {"filterId": "TERMID", "defaultValue": "24816"},
        {
            "filterId": "period",
            "defaultValue": "2026-09-01T00:00:00.0000000 - "
                             "2026-11-30T00:00:00.0000000",
        },
    ]
    responses = {
        "/webapi/reports/studenttotal": FakeResponse(
            json_data={"filterSources": filter_sources}
        ),
        "/webapi/reports/studenttotal/queue": FakeResponse(json_data={
            "taskId": 10276201,
            "queueKey": "report-v2",
        }),
        "/webapi/files/file456": FakeResponse(text="<html>report</html>"),
    }
    fake = FakeClient("https://sgo.example", responses)

    socket = FakeSocket([
        '{"type":1,"target":"complete","arguments":[{'
        '"taskId":10276201,"data":"file456"}]}\x1e',
    ])

    def fake_connect(url, **kwargs):
        return socket

    ns = NetSchoolAPI("https://sgo.example")
    ns._wrapped_client.client = fake
    ns._ver = "999"
    ns._school_name = "МОУ Лицей №4"
    ns._year_id = 7207
    ns._access_token = "at123"

    with patch("netschoolapi_plus.netschoolapi.connect", fake_connect):
        html = asyncio.run(ns.report_file())

    assert html == "<html>report</html>"
    payload = json.loads(fake.requests[1].content)
    assert payload["selectedData"][3] == {
        "filterId": "period",
        "filterValue": "2026-09-01T00:00:00.000Z - "
                       "2026-11-30T00:00:00.000Z",
    }


def test_report_studenttotal_forwards_none_dates():
    """Без дат report_studenttotal не должен подставлять неделю сам —
    пусть report_file берёт серверный период триместра."""
    filter_sources = [
        {"filterId": "SID", "defaultValue": "562093"},
        {"filterId": "PCLID", "defaultValue": "92540"},
        {"filterId": "TERMID", "defaultValue": "24816"},
        {
            "filterId": "period",
            "defaultValue": "2026-09-01T00:00:00.0000000 - "
                             "2026-11-30T00:00:00.0000000",
        },
    ]
    responses = {
        "/webapi/reports/studenttotal": FakeResponse(
            json_data={"filterSources": filter_sources}
        ),
        "/webapi/reports/studenttotal/queue": FakeResponse(json_data={
            "taskId": 10276202,
            "queueKey": "report-v2",
        }),
        "/webapi/files/file789": FakeResponse(
            text="<html>official report HTML</html>"
        ),
    }
    fake = FakeClient("https://sgo.example", responses)

    socket = FakeSocket([
        '{"type":1,"target":"complete","arguments":[{"taskId":10276202,'
        '"data":"file789"}]}\x1e',
    ])

    def fake_connect(url, **kwargs):
        return socket

    ns = NetSchoolAPI("https://sgo.example")
    ns._wrapped_client.client = fake
    ns._ver = "999"
    ns._school_name = "МОУ Лицей №4"
    ns._year_id = 7207
    ns._access_token = "at123"

    with patch("netschoolapi_plus.netschoolapi.connect", fake_connect), \
         patch("netschoolapi_plus.netschoolapi.parse_student_total_report") as mock_parse:
        mock_parse.return_value = "parsed"
        result = asyncio.run(ns.report_studenttotal())

    assert result == "parsed"
    mock_parse.assert_called_once_with("<html>official report HTML</html>")
    payload = json.loads(fake.requests[1].content)
    assert payload["selectedData"][3]["filterValue"] == (
        "2026-09-01T00:00:00.000Z - 2026-11-30T00:00:00.000Z"
    )