from fastapi.testclient import TestClient

from app.main import app
from app.stats import build_question_stats


def test_filling_survey_requires_login():
    client = TestClient(app)

    response = client.get("/survey/example-public-id", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


class FakeResponses:
    def aggregate(self, pipeline):
        if pipeline[-1] == {"$count": "count"}:
            return [{"count": 1}]
        return [{"_id": "满意", "count": 1}]


class FakeDatabase:
    responses = FakeResponses()


def test_single_choice_stats_include_zero_count_options():
    question = {
        "_id": "question-1",
        "type": "single",
        "options": ["满意", "一般", "不满意"],
    }

    result = build_question_stats(FakeDatabase(), "survey-1", question)

    assert result["answered_total"] == 1
    assert result["items"] == [
        {"_id": "满意", "count": 1},
        {"_id": "一般", "count": 0},
        {"_id": "不满意", "count": 0},
    ]
