"""End-to-end smoke test against a disposable MongoDB database."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path


os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:27018")
os.environ.setdefault("MONGODB_DB", "survey_system_smoke")
os.environ.setdefault("SESSION_SECRET", "smoke-test-secret")
os.environ.setdefault("DEBUG", "false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def run() -> None:
    creator = f"creator_{uuid.uuid4().hex[:8]}"
    respondent = f"respondent_{uuid.uuid4().hex[:8]}"
    survey_title = f"集成测试问卷_{uuid.uuid4().hex[:8]}"

    with TestClient(app) as client:
        db = app.state.db
        db.users.delete_many({"username": {"$in": [creator, respondent]}})

        response = client.post(
            "/register",
            data={
                "username": creator,
                "password": "password123",
                "password_confirm": "password123",
            },
        )
        assert response.status_code == 200

        response = client.post(
            "/surveys/new",
            data={
                "title": survey_title,
                "description": "验证完整流程",
                "allow_anonymous": "1",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        edit_url = response.headers["location"]
        survey_id = edit_url.split("/")[2]

        client.post(
            f"/surveys/{survey_id}/questions",
            data={
                "prompt": "是否跳过文字题？",
                "question_type": "single",
                "required": "1",
                "options_text": "跳过\n不跳过",
            },
        )
        client.post(
            f"/surveys/{survey_id}/questions",
            data={
                "prompt": "文字说明",
                "question_type": "text",
                "required": "1",
                "min_length": "2",
            },
        )
        client.post(
            f"/surveys/{survey_id}/questions",
            data={
                "prompt": "年龄",
                "question_type": "number",
                "required": "1",
                "min_value": "0",
                "max_value": "120",
                "integer_only": "1",
            },
        )

        survey = db.surveys.find_one({"title": survey_title})
        q1, _q2, q3 = survey["questions"]
        response = client.post(
            f"/surveys/{survey_id}/questions/{q1['_id']}/jump-rules",
            data={
                "operator": "equals",
                "value": "跳过",
                "target_question_id": q3["_id"],
            },
        )
        assert response.status_code == 200

        response = client.post(f"/surveys/{survey_id}/publish")
        assert response.status_code == 200
        survey = db.surveys.find_one({"_id": survey["_id"]})
        public_id = survey["public_id"]

        client.post("/logout")
        response = client.get(f"/survey/{public_id}", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

        client.post(
            "/register",
            data={
                "username": respondent,
                "password": "password123",
                "password_confirm": "password123",
            },
        )
        response = client.get(f"/survey/{public_id}")
        assert response.status_code == 200
        assert "是否跳过文字题" in response.text

        response = client.post(
            f"/survey/{public_id}/submit",
            data={
                f"q_{q1['_id']}": "跳过",
                f"q_{q3['_id']}": "25",
            },
        )
        assert response.status_code == 200
        assert "提交成功" in response.text

        stored = db.responses.find_one({"survey_id": survey["_id"]})
        assert stored is not None
        assert stored["respondent_id"] is None
        assert stored["visited_question_ids"] == [q1["_id"], q3["_id"]]
        assert [answer["question_id"] for answer in stored["answers"]] == [
            q1["_id"],
            q3["_id"],
        ]

        client.post("/logout")
        client.post(
            "/login", data={"username": creator, "password": "password123"}
        )
        response = client.get(f"/surveys/{survey_id}/stats")
        assert response.status_code == 200
        assert "25.00" in response.text
        assert "不跳过" in response.text
        assert "回答人数" in response.text

        response = client.get(
            f"/surveys/{survey_id}/stats?question_id={q1['_id']}"
        )
        assert response.status_code == 200
        assert "是否跳过文字题" in response.text
        assert "年龄" not in response.text

        db.responses.delete_many({"survey_id": survey["_id"]})
        db.surveys.delete_one({"_id": survey["_id"]})
        user_ids = [u["_id"] for u in db.users.find({"username": {"$in": [creator, respondent]}})]
        series_ids = [s["_id"] for s in db.question_series.find({"owner_id": {"$in": user_ids}})]
        db.question_versions.delete_many({"series_id": {"$in": series_ids}})
        db.question_series.delete_many({"owner_id": {"$in": user_ids}})
        db.question_banks.delete_many({"owner_id": {"$in": user_ids}})
        db.users.delete_many({"username": {"$in": [creator, respondent]}})

    print("Integration smoke test passed")


if __name__ == "__main__":
    run()

