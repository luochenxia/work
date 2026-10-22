from __future__ import annotations

from typing import Any


def build_question_stats(db, survey_id, question: dict[str, Any]) -> dict[str, Any]:
    question_id = str(question["_id"])
    base = [
        {"$match": {"survey_id": survey_id}},
        {"$unwind": "$answers"},
        {"$match": {"answers.question_id": question_id}},
    ]
    question_type = question["type"]

    answered_rows = list(db.responses.aggregate(base + [{"$count": "count"}]))
    answered_total = answered_rows[0]["count"] if answered_rows else 0

    if question_type == "single":
        pipeline = base + [
            {"$group": {"_id": "$answers.value", "count": {"$sum": 1}}},
            {"$sort": {"count": -1, "_id": 1}},
        ]
        rows = list(db.responses.aggregate(pipeline))
        counts = {row["_id"]: row["count"] for row in rows}
        items = [
            {"_id": option, "count": counts.get(option, 0)}
            for option in question.get("options", [])
        ]
        return {"kind": "options", "items": items, "answered_total": answered_total}

    if question_type == "multiple":
        pipeline = base + [
            {"$unwind": "$answers.value"},
            {"$group": {"_id": "$answers.value", "count": {"$sum": 1}}},
            {"$sort": {"count": -1, "_id": 1}},
        ]
        rows = list(db.responses.aggregate(pipeline))
        counts = {row["_id"]: row["count"] for row in rows}
        items = [
            {"_id": option, "count": counts.get(option, 0)}
            for option in question.get("options", [])
        ]
        return {"kind": "options", "items": items, "answered_total": answered_total}

    if question_type == "number":
        pipeline = base + [
            {
                "$group": {
                    "_id": None,
                    "count": {"$sum": 1},
                    "average": {"$avg": "$answers.value"},
                    "minimum": {"$min": "$answers.value"},
                    "maximum": {"$max": "$answers.value"},
                    "values": {"$push": "$answers.value"},
                }
            }
        ]
        rows = list(db.responses.aggregate(pipeline))
        return {"kind": "number", "summary": rows[0] if rows else None}

    pipeline = base + [
        {"$project": {"_id": 0, "value": "$answers.value", "submitted_at": 1}},
        {"$sort": {"submitted_at": -1}},
    ]
    return {"kind": "text", "items": list(db.responses.aggregate(pipeline))}

