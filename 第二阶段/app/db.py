from __future__ import annotations

from pymongo import ASCENDING, DESCENDING, MongoClient

from .config import Settings


def create_client(settings: Settings) -> MongoClient:
    return MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)


def init_indexes(db) -> None:
    db.question_series.create_index([("owner_id", ASCENDING), ("updated_at", DESCENDING)])
    db.question_series.create_index([("shared_with", ASCENDING)])
    db.question_series.create_index("legacy_key", unique=True,
                                   partialFilterExpression={"legacy_key": {"$exists": True}})
    db.question_versions.create_index([("series_id", ASCENDING), ("version", DESCENDING)], unique=True)
    db.question_banks.create_index([("owner_id", ASCENDING), ("name", ASCENDING)], unique=True)
    db.surveys.create_index([("questions.source_version_id", ASCENDING)])
    db.users.create_index([("username", ASCENDING)], unique=True)
    db.surveys.create_index([("public_id", ASCENDING)], unique=True)
    db.surveys.create_index(
        [("owner_id", ASCENDING), ("created_at", DESCENDING)]
    )
    db.surveys.create_index([("status", ASCENDING), ("deadline", ASCENDING)])
    db.responses.create_index(
        [("survey_id", ASCENDING), ("submitted_at", DESCENDING)]
    )
    db.responses.create_index(
        [("survey_id", ASCENDING), ("single_submission_key", ASCENDING)],
        unique=True,
        partialFilterExpression={"single_submission_key": {"$exists": True}},
    )

