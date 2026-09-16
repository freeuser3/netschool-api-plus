import asyncio
import datetime
import json

from httpx import AsyncClient

from netschoolapi_plus import NetSchoolAPI


class FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def aiter_text(self):
        for chunk in self._chunks:
            yield chunk


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
    def __init__(self, url, responses, stream):
        self._base = AsyncClient(base_url=f"{url}/webapi")
        self._responses = responses
        self._stream = stream
        self.requests = []

    def build_request(self, method, url, **kwargs):
        return self._base.build_request(method, url, **kwargs)

    async def send(self, request, follow_redirects=False):
        self.requests.append(request)
        return self._responses[request.url.path]

    def stream(self, method, url, **kwargs):
        return self._stream


def test_report_file_generates_official_report():
    complete_chunk = (
        'data: {"H":"queuehub","M":[{"M":"complete","A":[{"Data":"file123"}]}],'
        '"I":0,"T":0,"G":0}\r\n'
    )
    responses = {
        "/WebApi/signalr/negotiate": FakeResponse(
            json_data={"ConnectionToken": "tok1"}
        ),
        "/WebApi/signalr/start": FakeResponse(),
        "/webapi/reports/studenttotal": FakeResponse(json_data={
            "filterSources": [
                {"filterId": "SID", "defaultValue": 111},
                {"filterId": "PCLID", "defaultValue": 222},
                {"filterId": "period",
                 "defaultValue": "2026-09-01T00:00:00.0000000 - "
                                  "2026-09-30T00:00:00.0000000"},
            ]
        }),
        "/webapi/reports/studenttotal/queue": FakeResponse(),
        "/WebApi/signalr/send": FakeResponse(),
        "/WebApi/signalr/abort": FakeResponse(),
        "/webapi/files/file123": FakeResponse(text="<html>official report</html>"),
    }
    fake = FakeClient(
        "https://sgo.example",
        responses,
        FakeStream(["initialized\r\n", complete_chunk]),
    )

    ns = NetSchoolAPI("https://sgo.example")
    ns._wrapped_client.client = fake
    ns._ver = "999"
    ns._school_name = "МОУ Лицей №4"
    ns._year_id = 2026

    html = asyncio.run(ns.report_file(
        datetime.date(2026, 9, 1), datetime.date(2026, 9, 30)
    ))

    assert html == "<html>official report</html>"

    paths = [request.url.path for request in fake.requests]
    assert paths == [
        "/WebApi/signalr/negotiate",
        "/WebApi/signalr/start",
        "/webapi/reports/studenttotal",
        "/webapi/reports/studenttotal/queue",
        "/WebApi/signalr/send",
        "/WebApi/signalr/abort",
        "/webapi/files/file123",
    ]

    connect_token = fake.requests[4].url.params["connectionToken"]
    assert fake.requests[0].url.params["transport"] == "webSockets"
    assert fake.requests[1].url.params["transport"] == "serverSentEvents"
    assert fake.requests[4].url.params["connectionToken"] == "tok1"
    assert fake.requests[5].url.params["connectionToken"] == "tok1"

    payload = json.loads(fake.requests[3].content)
    assert payload["selectedData"] == [
        {"filterId": "SID", "filterValue": 111},
        {"filterId": "PCLID", "filterValue": 222},
        {"filterId": "period",
         "filterValue": "2026-09-01T00:00:00 - 2026-09-30T00:00:00"},
    ]
    assert payload["params"] == [
        {"name": "SCHOOLYEARID", "value": 2026},
        {"name": "SERVERTIMEZONE", "value": 0},
        {"name": "FULLSCHOOLNAME", "value": "МОУ Лицей №4"},
        {"name": "DATEFORMAT", "value": "d\x01mm\x01yy\x01."},
    ]