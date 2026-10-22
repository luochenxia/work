"""Create a small demo survey and two demo accounts."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.db import create_client, init_indexes  # noqa: E402
from app.security import hash_password, make_dedupe_key  # noqa: E402


def upsert_user(db, username: str):
    db.users.update_one(
        {"username": username},
        {
            "$set": {"password_hash": hash_password("password123")},
            "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
        },
        upsert=True,
    )
    return db.users.find_one({"username": username})


def main() -> None:
    client = create_client(settings)
    client.admin.command("ping")
    db = client[settings.mongodb_db]
    init_indexes(db)

    creator = upsert_user(db, "demo_creator")
    respondent = upsert_user(db, "demo_respondent")

    old = db.surveys.find_one({"public_id": "demo-survey"})
    if old:
        db.responses.delete_many({"survey_id": old["_id"]})
        db.surveys.delete_one({"_id": old["_id"]})

    now = datetime.now(timezone.utc)
    questions = [
        {
            "_id": "demo-q1",
            "prompt": "你是否参加了全部课程？",
            "type": "single",
            "required": True,
            "options": ["是", "否"],
            "validation": {},
            "jump_rules": [
                {
                    "_id": "demo-rule-1",
                    "operator": "equals",
                    "value": "否",
                    "target_question_id": "demo-q3",
                }
            ],
            "order": 0,
        },
        {
            "_id": "demo-q2",
            "prompt": "你喜欢哪些课程内容？",
            "type": "multiple",
            "required": True,
            "options": ["MongoDB", "后端开发", "数据分析"],
            "validation": {"min_choices": 1, "max_choices": 2},
            "jump_rules": [],
            "order": 1,
        },
        {
            "_id": "demo-q3",
            "prompt": "请为课程打分（0至100）",
            "type": "number",
            "required": True,
            "options": [],
            "validation": {"min_value": 0, "max_value": 100, "integer_only": True},
            "jump_rules": [],
            "order": 2,
        },
    ]
    survey_id = db.surveys.insert_one(
        {
            "owner_id": creator["_id"],
            "public_id": "demo-survey",
            "title": "课程体验演示问卷",
            "description": "用于演示题目校验、跳转与统计功能。",
            "allow_anonymous": False,
            "allow_multiple": False,
            "status": "published",
            "deadline": None,
            "questions": questions,
            "created_at": now,
            "updated_at": now,
            "published_at": now,
        }
    ).inserted_id

    db.responses.insert_one(
        {
            "survey_id": survey_id,
            "respondent_id": respondent["_id"],
            "is_anonymous": False,
            "single_submission_key": make_dedupe_key(
                settings.session_secret, str(survey_id), str(respondent["_id"])
            ),
            "answers": [
                {"question_id": "demo-q1", "value": "是"},
                {"question_id": "demo-q2", "value": ["MongoDB", "后端开发"]},
                {"question_id": "demo-q3", "value": 88},
            ],
            "visited_question_ids": ["demo-q1", "demo-q2", "demo-q3"],
            "submitted_at": now,
        }
    )
    client.close()
    print("Demo data created")
    print("Creator: demo_creator / password123")
    print("Respondent: demo_respondent / password123")
    print("Survey URL: http://127.0.0.1:8000/survey/demo-survey")


if __name__ == "__main__":
    main()

