"""In-memory PostgREST double: exercise real SupabaseStore HTTP/params/headers offline."""
from __future__ import annotations

import json as jsonlib
from typing import Any

import requests


class FakePostgrest:
    def __init__(self) -> None:
        self.students: dict[str, dict[str, Any]] = {}
        self.attendance: dict[tuple[str, str], dict[str, Any]] = {}
        self.calls: list[dict[str, Any]] = []
        self.fail = False

    @staticmethod
    def _response(status: int, payload: Any) -> requests.Response:
        response = requests.Response()
        response.status_code = status
        response._content = jsonlib.dumps(payload, ensure_ascii=False).encode("utf-8")
        return response

    @staticmethod
    def _eq(filter_value: str) -> str:
        assert filter_value.startswith("eq.")
        raw = filter_value[3:]
        return jsonlib.loads(raw) if raw.startswith('"') else raw

    @staticmethod
    def _select(rows: list[dict[str, Any]], params: dict[str, str]) -> list[dict[str, Any]]:
        fields = params.get("select", "*").split(",")
        if fields == ["*"]:
            return rows
        return [{field: row[field] for field in fields if field in row} for row in rows]

    def request(self, method: str, url: str, *, params=None, json=None, headers=None, timeout=None):
        if self.fail:
            raise requests.ConnectionError("fake offline")
        assert timeout == 20
        assert url.startswith("https://fake.supabase.co/rest/v1/")
        assert headers["apikey"]
        assert headers["Prefer"] == "return=representation"
        # New sb_secret keys are not Bearer JWTs; legacy service_role JWTs are.
        if headers["apikey"].startswith("sb_secret_"):
            assert "Authorization" not in headers
        else:
            assert headers["Authorization"] == f"Bearer {headers['apikey']}"
        params = params or {}
        table = url.rsplit("/", 1)[1]
        self.calls.append({"method": method, "table": table, "params": params.copy(),
                           "body": json, "headers": headers.copy()})

        if method == "POST" and table == "students":
            if json["student_id"] in self.students or any(
                row["card_token"] == json["card_token"] for row in self.students.values()
            ):
                return self._response(409, {"code": "23505", "message": "unique violation"})
            row = {"section": "", "roll_no": "", "active": True, "valid_until": None,
                   "session": "", "face_descriptor": None, **json}
            self.students[row["student_id"]] = row
            return self._response(201, [row])

        if method == "PATCH" and table == "students":
            student = self.students.get(self._eq(params["student_id"]))
            if not student:
                return self._response(200, [])
            student.update(json)
            return self._response(200, [student])

        if method == "GET" and table == "students":
            rows = list(self.students.values())
            for field in ("student_id", "card_token"):
                if field in params:
                    rows = [row for row in rows if row[field] == self._eq(params[field])]
            rows.sort(key=lambda r: (r["class_name"], r["name"], r["student_id"]))
            rows = rows[int(params.get("offset", 0)):]
            rows = rows[:int(params.get("limit", 1000))]
            return self._response(200, self._select(rows, params))

        if method == "POST" and table == "attendance":
            key = (json["student_id"], json["date"])
            if key in self.attendance:
                return self._response(409, {"code": "23505", "message": "unique violation"})
            if json["student_id"] not in self.students:
                return self._response(409, {"code": "23503", "message": "foreign key violation"})
            self.attendance[key] = json.copy()
            return self._response(201, [json])

        if method == "GET" and table == "attendance":
            rows = [r for r in self.attendance.values() if r["date"] == self._eq(params["date"])]
            rows.sort(key=lambda r: r["student_id"])
            rows.sort(key=lambda r: r["time"], reverse=True)
            rows = rows[int(params.get("offset", 0)):]
            rows = rows[:int(params.get("limit", 1000))]
            return self._response(200, self._select(rows, params))

        raise AssertionError(f"unexpected PostgREST request: {method} {table} {params}")
