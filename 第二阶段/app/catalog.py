"""Reusable questions: immutable versions, sharing, banks and legacy migration."""
from __future__ import annotations

import math
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument

from .domain import QUESTION_TYPES


class CatalogError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def oid(value) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise CatalogError("记录不存在", 404)


def visible_query(user_id) -> dict:
    return {"$or": [{"owner_id": user_id}, {"shared_with": user_id}, {"is_public": True}]}


def get_series(db, series_id, user_id, owner_only=False):
    query = {"_id": oid(series_id)}
    query.update({"owner_id": user_id} if owner_only else visible_query(user_id))
    series = db.question_series.find_one(query)
    if not series:
        raise CatalogError("题目不存在或没有访问权限", 404)
    return series


def get_version(db, version_id, user_id):
    version = db.question_versions.find_one({"_id": oid(version_id)})
    if not version:
        raise CatalogError("题目版本不存在", 404)
    series = get_series(db, version["series_id"], user_id)
    return series, version


def content_fields(question: dict) -> dict:
    return deepcopy({
        "prompt": question.get("prompt", ""), "type": question.get("type", "text"),
        "required": bool(question.get("required")), "options": question.get("options", []),
        "validation": question.get("validation", {}),
    })


def parse_content(form) -> dict:
    prompt = str(form.get("prompt", "")).strip()
    kind = str(form.get("question_type", ""))
    if not prompt or len(prompt) > 2000:
        raise CatalogError("题目内容不能为空，且不能超过2000个字符")
    if kind not in QUESTION_TYPES:
        raise CatalogError("请选择有效题型")
    options = [x.strip() for x in str(form.get("options_text", "")).splitlines() if x.strip()]
    if kind in {"single", "multiple"}:
        if len(options) < 2 or len(options) != len(set(options)):
            raise CatalogError("选择题至少需要两个不重复的选项")
    else:
        options = []
    validation = {}
    pairs = {"multiple": ("choices", int), "text": ("length", int), "number": ("value", float)}
    if kind in pairs:
        suffix, convert = pairs[kind]
        for prefix in ("min", "max"):
            key = prefix + "_" + suffix
            value = form.get(key)
            if value is not None and str(value).strip():
                try:
                    number = convert(value)
                except (TypeError, ValueError):
                    raise CatalogError("校验规则必须填写有效数字")
                if not math.isfinite(number) or (kind != "number" and number < 0):
                    raise CatalogError("校验规则中的数值无效")
                validation[key] = number
        low, high = validation.get("min_" + suffix), validation.get("max_" + suffix)
        if low is not None and high is not None and low > high:
            raise CatalogError("最小值不能大于最大值")
        if kind == "multiple" and any(v > len(options) for v in validation.values()):
            raise CatalogError("选择数量不能超过选项总数")
    if kind == "number":
        validation["integer_only"] = bool(form.get("integer_only"))
    return {"prompt": prompt, "type": kind, "required": bool(form.get("required")),
            "options": options, "validation": validation}


def default_bank(db, user_id):
    return db.question_banks.find_one_and_update(
        {"owner_id": user_id, "name": "默认题库"},
        {"$setOnInsert": {"description": "常用题目", "question_ids": [],
                          "created_at": datetime.now(timezone.utc)}},
        upsert=True, return_document=ReturnDocument.AFTER,
    )


def add_to_bank(db, user_id, bank_id, series_id):
    get_series(db, series_id, user_id)
    bank = (db.question_banks.find_one({"_id": oid(bank_id), "owner_id": user_id})
            if bank_id else default_bank(db, user_id))
    if not bank:
        raise CatalogError("题库不存在或不属于当前用户", 404)
    db.question_banks.update_one({"_id": bank["_id"], "owner_id": user_id},
                                 {"$addToSet": {"question_ids": oid(series_id)}})
    return bank


def create_question(db, owner_id, content, bank_id=None, forked_from=None):
    # Validate the bank before making any persistent question records.
    if bank_id and not db.question_banks.find_one({"_id": oid(bank_id), "owner_id": owner_id}):
        raise CatalogError("请选择自己的题库")
    now, series_id, version_id = datetime.now(timezone.utc), ObjectId(), ObjectId()
    series = {"_id": series_id, "owner_id": owner_id, "latest_version_id": version_id,
              "latest_version": 1, "next_version": 1, "shared_with": [], "is_public": False,
              "created_at": now, "updated_at": now}
    version = {"_id": version_id, "series_id": series_id, "version": 1,
               "parent_version_id": None, "restored_from_id": None,
               "forked_from_id": forked_from, "created_at": now, **content_fields(content)}
    db.question_series.insert_one(series)
    db.question_versions.insert_one(version)
    add_to_bank(db, owner_id, bank_id, series_id)
    return version


def create_version(db, user_id, series_id, parent_id, content, restored_from=None):
    series = get_series(db, series_id, user_id, owner_only=True)
    parent = db.question_versions.find_one({"_id": oid(parent_id), "series_id": series["_id"]})
    if not parent:
        raise CatalogError("来源版本不属于该题目")
    if restored_from and not db.question_versions.find_one(
        {"_id": oid(restored_from), "series_id": series["_id"]}
    ):
        raise CatalogError("恢复目标不属于该题目")
    counter = db.question_series.find_one_and_update(
        {"_id": series["_id"], "owner_id": user_id}, {"$inc": {"next_version": 1}},
        return_document=ReturnDocument.AFTER,
    )
    number = counter["next_version"]
    version = {"_id": ObjectId(), "series_id": series["_id"], "version": number,
               "parent_version_id": parent["_id"],
               "restored_from_id": oid(restored_from) if restored_from else None,
               "created_at": datetime.now(timezone.utc), **content_fields(content)}
    db.question_versions.insert_one(version)
    # A slower concurrent writer must not move the head back to an older version.
    db.question_series.update_one(
        {"_id": series["_id"], "latest_version": {"$lt": number}},
        {"$set": {"latest_version_id": version["_id"], "latest_version": number,
                  "updated_at": version["created_at"]}},
    )
    return version


def snapshot(version, order, local_id=None):
    return {"_id": local_id or uuid.uuid4().hex[:12], **content_fields(version),
            "source_question_id": version["series_id"], "source_version_id": version["_id"],
            "source_version": version["version"], "order": order, "jump_rules": []}


def choices(db, user_id, bank_id=None):
    query = visible_query(user_id)
    if bank_id:
        bank = db.question_banks.find_one({"_id": oid(bank_id), "owner_id": user_id})
        if not bank:
            raise CatalogError("题库不存在或不属于当前用户", 404)
        query["_id"] = {"$in": bank.get("question_ids", [])}
    series = list(db.question_series.find(query).sort("updated_at", -1))
    versions = list(db.question_versions.find({"series_id": {"$in": [s["_id"] for s in series]}})
                    .sort("version", -1))
    return series, versions


def version_usages(db, series, version_id, user_id):
    query = {"questions.source_version_id": oid(version_id)}
    # The question author sees usage and anonymous question-level aggregates;
    # a recipient sees only surveys they own, never other survey contents.
    if series["owner_id"] != user_id:
        query["owner_id"] = user_id
    result = []
    for survey in db.surveys.find(query):
        for question in survey.get("questions", []):
            if question.get("source_version_id") == oid(version_id):
                result.append({"survey_id": survey["_id"], "title": survey["title"],
                               "status": survey["status"], "question_id": question["_id"],
                               "order": question.get("order", 0),
                               "is_owner": survey["owner_id"] == user_id})
    return result


def cross_stats(db, series, version, user_id):
    from .stats import aggregate_question_stats
    uses = version_usages(db, series, version["_id"], user_id)
    pairs = [{"survey_id": u["survey_id"], "answers.question_id": u["question_id"]} for u in uses]
    base = [
        {"$match": {"survey_id": {"$in": list({u["survey_id"] for u in uses})}}},
        {"$unwind": "$answers"},
        {"$match": {"$or": pairs} if pairs else {"_id": {"$in": []}}},
    ]
    return aggregate_question_stats(db, base, version), uses


def migrate_legacy_questions(db):
    """Idempotent metadata-only backfill; question text and existing answers stay intact."""
    for survey in db.surveys.find({"questions": {"$elemMatch": {"source_version_id": {"$exists": False}}}}):
        for question in survey.get("questions", []):
            if question.get("source_version_id"):
                continue
            key = str(survey["_id"]) + ":" + str(question["_id"])
            now = datetime.now(timezone.utc)
            series = db.question_series.find_one_and_update(
                {"legacy_key": key}, {"$setOnInsert": {
                    "owner_id": survey["owner_id"], "latest_version": 1, "next_version": 1,
                    "shared_with": [], "is_public": False, "created_at": now, "updated_at": now,
                }}, upsert=True, return_document=ReturnDocument.AFTER,
            )
            version = db.question_versions.find_one_and_update(
                {"series_id": series["_id"], "version": 1}, {"$setOnInsert": {
                    **content_fields(question), "parent_version_id": None,
                    "restored_from_id": None, "created_at": now,
                }}, upsert=True, return_document=ReturnDocument.AFTER,
            )
            db.question_series.update_one(
                {"_id": series["_id"], "latest_version_id": {"$exists": False}},
                {"$set": {"latest_version_id": version["_id"]}},
            )
            db.surveys.update_one(
                {"_id": survey["_id"], "questions": {"$elemMatch": {
                    "_id": question["_id"], "source_version_id": {"$exists": False}}}},
                {"$set": {"questions.$.source_question_id": series["_id"],
                          "questions.$.source_version_id": version["_id"],
                          "questions.$.source_version": 1}},
            )
            add_to_bank(db, survey["owner_id"], None, series["_id"])
