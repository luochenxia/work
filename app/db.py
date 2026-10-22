from __future__ import annotations

from pymongo import ASCENDING, DESCENDING, MongoClient

from .config import Settings


def create_client(settings: Settings) -> MongoClient:
    return MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)


def init_indexes(db) -> None:
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

