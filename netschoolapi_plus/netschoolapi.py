import asyncio
import json
from datetime import date, timedelta
from hashlib import md5
from io import BytesIO
from typing import Optional, Dict, List, Union

import httpx
from httpx import AsyncClient, Response

from websockets import connect

from netschoolapi_plus import errors, schemas
from netschoolapi_plus.report_parser import parse_student_total_report

__all__ = ['NetSchoolAPI']

from netschoolapi_plus.async_client_wrapper import AsyncClientWrapper, Requester


async def _die_on_bad_status(response: Response):
    if not response.is_redirect:
        response.raise_for_status()


class NetSchoolAPI:
    def __init__(self, url: str, default_requests_timeout: int = None):
        url = url.rstrip('/')
        self._url = url
        self._wrapped_client = AsyncClientWrapper(
            async_client=AsyncClient(
                base_url=f'{url}/webapi',
                headers={'user-agent': 'NetSchoolAPI/5.0.3', 'referer': url},
                event_hooks={'response': [_die_on_bad_status]},
            ),
            default_requests_timeout=default_requests_timeout,
        )

        self._student_id = -1
        self._year_id = -1
        self._school_id = -1
        self._school_name = ""
        self._ver = None

        self._assignment_types: Dict[int, str] = {}
        self._login_data = ()
        self._access_token = None

    async def __aenter__(self) -> 'NetSchoolAPI':
        return self

    async def __aexit__(self, _exc_type, _exc_val, _exc_tb):
        await self.logout()

    async def login(
            self, user_name: str, password: str,
            school_name_or_id: Union[int, str],
            requests_timeout: int = None):
        requester = self._wrapped_client.make_requester(requests_timeout)
        # Getting the `NSSESSIONID` cookie for `auth/getdata`
        await requester(self._wrapped_client.client.build_request(
            method="GET", url="logindata"
        ))

        # Getting the `NSSESSIONID` cookie for `login`
        response = await requester(self._wrapped_client.client.build_request(
            method="POST", url='auth/getdata'
        ))
        login_meta = response.json()
        salt = login_meta.pop('salt')
        self._ver = login_meta.get('ver')

        encoded_password = md5(
            password.encode('windows-1251')
        ).hexdigest().encode()
        pw2 = md5(salt.encode() + encoded_password).hexdigest()
        pw = pw2[: len(password)]

        try:
            response = await requester(
                self._wrapped_client.client.build_request(
                    method="POST",
                    url='login',
                    data={
                        'loginType': 1,
                        'scid': (
                            (await self._get_school_id(
                                school_name_or_id, requester,
                            ))
                            if isinstance(school_name_or_id, str) else
                            school_name_or_id
                        ),
                        'un': user_name,
                        'pw': pw,
                        'pw2': pw2,
                        **login_meta,
                    },
                )
            )
        except httpx.HTTPStatusError as http_status_error:
            if http_status_error.response.status_code == httpx.codes.CONFLICT:
                try:
                    response_json = http_status_error.response.json()
                except httpx.ResponseNotRead:
                    pass
                else:
                    if 'message' in response_json:
                        raise errors.AuthError(
                            http_status_error.response.json()['message']
                        )
                raise errors.AuthError()
            else:
                raise http_status_error
        auth_result = response.json()

        if 'at' not in auth_result:
            raise errors.AuthError(auth_result['message'])

        self._access_token = auth_result["at"]
        self._wrapped_client.client.headers['at'] = auth_result['at']

        response = await requester(self._wrapped_client.client.build_request(
            method="GET", url='student/diary/init',
        ))
        diary_info = response.json()
        student = diary_info['students'][diary_info['currentStudentId']]
        self._student_id = student['studentId']

        response = await requester(self._wrapped_client.client.build_request(
            method="GET", url='years/current'
        ))
        year_reference = response.json()
        self._year_id = year_reference['id']

        response = await requester(self._wrapped_client.client.build_request(
            method="GET", url="grade/assignment/types", params={"all": False},
        ))
        assignment_reference = response.json()
        self._assignment_types = {
            assignment['id']: assignment['name']
            for assignment in assignment_reference
        }
        self._login_data = (user_name, password, school_name_or_id)

    async def _request_with_optional_relogin(
            self, requests_timeout: Optional[int], request: httpx.Request,
            follow_redirects=False):
        try:
            response = await self._wrapped_client.request(
                requests_timeout, request, follow_redirects
            )
        except httpx.HTTPStatusError as http_status_error:
            if (
                http_status_error.response.status_code
                == httpx.codes.UNAUTHORIZED
            ):
                if self._login_data:
                    await self.login(*self._login_data)
                    return await self._request_with_optional_relogin(
                        requests_timeout, request, follow_redirects
                    )
                else:
                    raise errors.AuthError(
                        ".login() before making requests that need "
                        "authorization"
                    )
            else:
                raise http_status_error
        else:
            return response

    async def download_attachment(
            self, attachment_id: int, buffer: BytesIO,
            requests_timeout: int = None):
        buffer.write((
            await self._request_with_optional_relogin(
                requests_timeout,
                self._wrapped_client.client.build_request(
                    method="GET", url=f"attachments/{attachment_id}",
                )
            )
        ).content)

    async def diary(
        self,
        start: Optional[date] = None,
        end: Optional[date] = None,
        requests_timeout: int = None,
    ) -> schemas.Diary:
        if not start:
            monday = date.today() - timedelta(days=date.today().weekday())
            start = monday
        if not end:
            end = start + timedelta(days=5)

        response = await self._request_with_optional_relogin(
            requests_timeout,
            self._wrapped_client.client.build_request(
                method="GET",
                url="student/diary",
                params={
                    'studentId': self._student_id,
                    'yearId': self._year_id,
                    'weekStart': start.isoformat(),
                    'weekEnd': end.isoformat(),
                },
            )
        )
        diary_schema = schemas.DiarySchema()
        diary_schema.context['assignment_types'] = self._assignment_types
        diary = diary_schema.load(response.json())
        return diary  # type: ignore

    async def overdue(
        self,
        start: Optional[date] = None,
        end: Optional[date] = None,
        requests_timeout: int = None,
    ) -> List[schemas.Assignment]:
        if not start:
            monday = date.today() - timedelta(days=date.today().weekday())
            start = monday
        if not end:
            end = start + timedelta(days=5)

        response = await self._request_with_optional_relogin(
            requests_timeout,
            self._wrapped_client.client.build_request(
                method="GET",
                url='student/diary/pastMandatory',
                params={
                    'studentId': self._student_id,
                    'yearId': self._year_id,
                    'weekStart': start.isoformat(),
                    'weekEnd': end.isoformat(),
                },
            )
        )
        assignments_schema = schemas.AssignmentSchema()
        assignments_schema.context['assignment_types'] = self._assignment_types
        assignments = assignments_schema.load(response.json(), many=True)
        return assignments  # type: ignore

    async def announcements(
            self, take: Optional[int] = -1,
            requests_timeout: int = None) -> List[schemas.Announcement]:
        response = await self._request_with_optional_relogin(
            requests_timeout,
            self._wrapped_client.client.build_request(
                method="GET",
                url="announcements",
                params={"take": take},
            )
        )
        announcements = schemas.AnnouncementSchema().load(response.json(), many=True)
        return announcements  # type: ignore

    async def attachments(
            self, assignment_id: int,
            requests_timeout: int = None) -> List[schemas.Attachment]:
        response = await self._request_with_optional_relogin(
            requests_timeout,
            self._wrapped_client.client.build_request(
                method="POST",
                url='student/diary/get-attachments',
                params={'studentId': self._student_id},
                json={'assignId': [assignment_id]},
            ),
        )
        response = response.json()
        if not response:
            return []
        attachments_json = response[0]['attachments']
        attachments = schemas.AttachmentSchema().load(attachments_json, many=True)
        return attachments  # type: ignore

    async def school(self, requests_timeout: int = None) -> schemas.School:
        response = await self._request_with_optional_relogin(
            requests_timeout,
            self._wrapped_client.client.build_request(
                method="GET",
                url='schools/{0}/card'.format(self._school_id),
            )
        )
        school = schemas.SchoolSchema().load(response.json())
        return school  # type: ignore

    async def report_file(
            self, start: Optional[date] = None,
            end: Optional[date] = None,
            requests_timeout: int = None) -> str:
        if not start:
            monday = date.today() - timedelta(days=date.today().weekday())
            start = monday
        if not end:
            end = start + timedelta(days=5)

        client = self._wrapped_client.client

        filter_sources = (await self._request_with_optional_relogin(
            requests_timeout,
            client.build_request(
                method="GET",
                url="reports/studenttotal",
            ),
        )).json()["filterSources"]
        filters = {
            source["filterId"]: source
            for source in filter_sources
        }

        period = (
            f"{start.isoformat()}T00:00:00.000Z - "
            f"{end.isoformat()}T00:00:00.000Z"
        )

        task = (await self._request_with_optional_relogin(
            requests_timeout,
            client.build_request(
                method="POST",
                url="reports/studenttotal/queue",
                json={
                    "selectedData": [
                        {
                            "filterId": "SID",
                            "filterValue": filters["SID"]["defaultValue"],
                        },
                        {
                            "filterId": "PCLID",
                            "filterValue": filters["PCLID"]["defaultValue"],
                        },
                        {
                            "filterId": "TERMID",
                            "filterValue": filters["TERMID"]["defaultValue"],
                        },
                        {
                            "filterId": "period",
                            "filterValue": period,
                        },
                    ],
                    "params": [
                        {
                            "name": "SCHOOLYEARID",
                            "value": str(self._year_id),
                        },
                        {"name": "SERVERTIMEZONE", "value": 3},
                        {
                            "name": "FULLSCHOOLNAME",
                            "value": self._school_name,
                        },
                        {
                            "name": "DATEFORMAT",
                            "value": "d\x01mm\x01yyyy\x01.",
                        },
                    ],
                },
            ),
        )).json()
        task_id = task["taskId"]
        queue_key = task.get("queueKey", "report-v2")

        cookies = "; ".join(
            f"{key}={value}"
            for key, value in client.cookies.items()
        )
        ws_url = (
            self._url.replace("https://", "wss://", 1)
            + f"/signalr/queueHub?at={self._access_token}"
        )

        file_id = None
        async with connect(
            ws_url,
            additional_headers={"Cookie": cookies},
            open_timeout=15,
        ) as websocket:
            await websocket.send('{"protocol":"json","version":1}\x1e')
            await websocket.send(
                json.dumps({
                    "arguments": [task_id, queue_key],
                    "invocationId": "0",
                    "target": "startTask",
                    "type": 1,
                })
                + "\x1e"
            )
            while file_id is None:
                raw = await asyncio.wait_for(
                    websocket.recv(), timeout=requests_timeout or 120,
                )
                if isinstance(raw, bytes):
                    raw = raw.decode(errors="replace")
                for chunk in raw.split("\x1e"):
                    chunk = chunk.strip()
                    if not chunk:
                        continue
                    try:
                        message = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    if (
                        message.get("type") == 1
                        and message.get("target") == "complete"
                    ):
                        for argument in message.get("arguments") or []:
                            if "data" in argument:
                                file_id = argument["data"]
                                break
                    if file_id:
                        break

        file_response = await self._request_with_optional_relogin(
            requests_timeout,
            client.build_request(
                method="GET",
                url=f"files/{file_id}",
            ),
        )
        return file_response.text

    async def report_studenttotal(
            self, start: Optional[date] = None,
            end: Optional[date] = None,
            requests_timeout: int = None) -> schemas.StudentTotalReport:
        if not start:
            monday = date.today() - timedelta(days=date.today().weekday())
            start = monday
        if not end:
            end = start + timedelta(days=5)
        html = await self.report_file(start, end, requests_timeout)
        return parse_student_total_report(html)

    async def logout(self, requests_timeout: int = None):
        try:
            await self._wrapped_client.request(
                requests_timeout,
                self._wrapped_client.client.build_request(
                    method="POST",
                    url='auth/logout',
                )
            )
        except httpx.HTTPStatusError as http_status_error:
            if (
                http_status_error.response.status_code
                == httpx.codes.UNAUTHORIZED
            ):
                # Session is dead => we are logged out already
                # OR
                # We are logged out already
                pass
            else:
                raise http_status_error

    async def full_logout(self, requests_timeout: int = None):
        await self.logout(requests_timeout)
        await self._wrapped_client.client.aclose()

    async def schools(
            self, requests_timeout: int = None) -> List[schemas.ShortSchool]:
        resp = await self._wrapped_client.request(
            requests_timeout,
            self._wrapped_client.client.build_request(
                method="GET", url="schools/search?name=У",
            )
        )
        schools = schemas.ShortSchoolSchema().load(resp.json(), many=True)
        return schools  # type: ignore

    async def _get_school_id(
            self, school_name: str,
            requester: Requester) -> Dict[str, int]:
        schools = (await requester(
            self._wrapped_client.client.build_request(
                method="GET",
                url=f"schools/search?name={school_name}",
            )
        )).json()

        for school in schools:
            if school["shortName"] == school_name:
                self._school_id = school['id']
                self._school_name = (
                    school.get("fullName")
                    or school.get("shortName")
                    or school.get("name", "")
                )
                return school["id"]
        raise errors.SchoolNotFoundError(school_name)

    async def download_profile_picture(
            self, user_id: int, buffer: BytesIO,
            requests_timeout: int = None):
        buffer.write((
            await self._request_with_optional_relogin(
                requests_timeout,
                self._wrapped_client.client.build_request(
                    method="GET",
                    url="users/photo",
                    params={"at": self._access_token, "userId": user_id},
                ),
                follow_redirects=True,
            )
        ).content)
