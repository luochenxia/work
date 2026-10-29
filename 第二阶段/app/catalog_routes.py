from __future__ import annotations

import re
import secrets
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request
from pymongo.errors import DuplicateKeyError

from .catalog import (CatalogError, add_to_bank, choices, content_fields, create_question,
                      create_version, cross_stats, get_series, get_version, oid, parse_content,
                      snapshot, version_usages, visible_query)


def install_catalog_routes(app, page, redirect, current_user, owned_survey, message_page):
    router = APIRouter()

    def user_for(request):
        user = current_user(request)
        if not user:
            raise CatalogError("请先登录", 401)
        return user

    def draft_for(request, survey_id):
        user_for(request)
        survey = owned_survey(request, survey_id)
        if not survey:
            raise CatalogError("问卷不存在或无权访问", 404)
        if survey.get("status") != "draft" or survey.get("published_at"):
            raise CatalogError("已发布或已关闭的问卷题目已锁定，请复制问卷后修改", 409)
        return survey

    @app.exception_handler(CatalogError)
    async def catalog_error(request, exc):
        if exc.status == 401:
            return redirect("/login")
        response = message_page(request, "操作未完成", str(exc))
        response.status_code = exc.status
        return response

    @router.get("/questions")
    def question_list(request: Request, bank_id: Optional[str] = None, q: str = ""):
        user, db = user_for(request), request.app.state.db
        series, versions = choices(db, user["_id"], bank_id)
        by_id = {v["_id"]: v for v in versions}
        items = [{"series": s, "version": by_id.get(s["latest_version_id"])} for s in series]
        items = [x for x in items if x["version"] and q.strip().lower() in x["version"]["prompt"].lower()]
        banks = list(db.question_banks.find({"owner_id": user["_id"]}).sort("name", 1))
        drafts = list(db.surveys.find({"owner_id": user["_id"], "status": "draft"}))
        return page(request, "question_list.html", items=items, banks=banks, drafts=drafts,
                    bank_id=bank_id or "", search=q)

    @router.get("/questions/new")
    def question_new(request: Request):
        user, db = user_for(request), request.app.state.db
        return page(request, "question_form.html", question={"type": "single", "validation": {},
                    "options": []}, series=None, base=None, error=None,
                    banks=list(db.question_banks.find({"owner_id": user["_id"]})))

    @router.post("/questions/new")
    async def question_create(request: Request):
        user, db = user_for(request), request.app.state.db
        form = await request.form()
        version = create_question(db, user["_id"], parse_content(form), form.get("bank_id") or None)
        return redirect(f"/questions/{version['series_id']}")

    @router.get("/questions/{series_id}")
    def question_detail(request: Request, series_id: str):
        user, db = user_for(request), request.app.state.db
        series = get_series(db, series_id, user["_id"])
        versions = list(db.question_versions.find({"series_id": series["_id"]}).sort("version", -1))
        numbers = {v["_id"]: v["version"] for v in versions}
        uses = {v["_id"]: version_usages(db, series, v["_id"], user["_id"]) for v in versions}
        names = [u["username"] for u in db.users.find({"_id": {"$in": series.get("shared_with", [])}})]
        fork_sources = {}
        for version in versions:
            if version.get("forked_from_id"):
                try:
                    origin_series, origin_version = get_version(db, version["forked_from_id"], user["_id"])
                    fork_sources[version["_id"]] = {"series_id": origin_series["_id"],
                        "prompt": origin_version["prompt"], "version": origin_version["version"]}
                except CatalogError:
                    pass
        return page(request, "question_detail.html", series=series, versions=versions,
                    numbers=numbers, uses=uses, shared_names="\n".join(names), fork_sources=fork_sources,
                    drafts=list(db.surveys.find({"owner_id": user["_id"], "status": "draft"})),
                    banks=list(db.question_banks.find({"owner_id": user["_id"]})))

    @router.get("/questions/{series_id}/versions/new")
    def version_form(request: Request, series_id: str, base: Optional[str] = None):
        user, db = user_for(request), request.app.state.db
        series = get_series(db, series_id, user["_id"], owner_only=True)
        version = db.question_versions.find_one({"_id": oid(base or series["latest_version_id"]),
                                                  "series_id": series["_id"]})
        if not version:
            raise CatalogError("来源版本不存在", 404)
        return page(request, "question_form.html", question=version, series=series,
                    base=version, banks=[], error=None)

    @router.post("/questions/{series_id}/versions/new")
    async def version_create(request: Request, series_id: str):
        user, db = user_for(request), request.app.state.db
        form = await request.form()
        create_version(db, user["_id"], series_id, form.get("parent_version_id"), parse_content(form))
        return redirect(f"/questions/{series_id}")

    @router.post("/questions/{series_id}/restore/{version_id}")
    def restore_version(request: Request, series_id: str, version_id: str):
        user, db = user_for(request), request.app.state.db
        series = get_series(db, series_id, user["_id"], owner_only=True)
        old = db.question_versions.find_one({"_id": oid(version_id), "series_id": series["_id"]})
        if not old:
            raise CatalogError("历史版本不存在", 404)
        create_version(db, user["_id"], series_id, series["latest_version_id"],
                       content_fields(old), restored_from=old["_id"])
        return redirect(f"/questions/{series_id}")

    @router.post("/questions/{series_id}/share")
    async def share_question(request: Request, series_id: str):
        user, db = user_for(request), request.app.state.db
        series = get_series(db, series_id, user["_id"], owner_only=True)
        form = await request.form()
        names = set(re.split(r"[\s,，]+", str(form.get("usernames", "")).strip())) - {"", user["username"]}
        recipients = list(db.users.find({"username": {"$in": list(names)}}))
        missing = names - {u["username"] for u in recipients}
        if missing:
            raise CatalogError("以下用户尚未注册：" + "、".join(sorted(missing)))
        db.question_series.update_one({"_id": series["_id"], "owner_id": user["_id"]},
            {"$set": {"shared_with": [u["_id"] for u in recipients],
                      "is_public": bool(form.get("is_public")), "updated_at": datetime.now(timezone.utc)}})
        return redirect(f"/questions/{series_id}")

    @router.post("/questions/{series_id}/fork")
    async def fork_question(request: Request, series_id: str):
        user, db = user_for(request), request.app.state.db
        form = await request.form()
        source, version = get_version(db, form.get("version_id"), user["_id"])
        if source["_id"] != oid(series_id):
            raise CatalogError("版本不属于该题目")
        new = create_question(db, user["_id"], version, forked_from=version["_id"])
        return redirect(f"/questions/{new['series_id']}")

    @router.post("/questions/{series_id}/bank")
    async def save_to_bank(request: Request, series_id: str):
        user, db = user_for(request), request.app.state.db
        form = await request.form()
        add_to_bank(db, user["_id"], form.get("bank_id") or None, series_id)
        return redirect("/questions")

    @router.get("/questions/{series_id}/stats")
    def question_statistics(request: Request, series_id: str, version_id: Optional[str] = None):
        user, db = user_for(request), request.app.state.db
        series = get_series(db, series_id, user["_id"])
        query = {"series_id": series["_id"]}
        if version_id:
            query["_id"] = oid(version_id)
        versions = list(db.question_versions.find(query).sort("version", -1))
        if not versions:
            raise CatalogError("没有可查看的版本", 404)
        items = []
        for version in versions:
            data, uses = cross_stats(db, series, version, user["_id"])
            items.append({"question": version, "data": data, "uses": uses,
                          "survey_count": len({u["survey_id"] for u in uses})})
        return page(request, "question_stats.html", series=series, items=items,
                    selected_version_id=version_id, is_author=series["owner_id"] == user["_id"])

    @router.get("/banks")
    def banks_page(request: Request):
        user = user_for(request)
        return page(request, "banks.html", banks=list(request.app.state.db.question_banks.find(
            {"owner_id": user["_id"]}).sort("name", 1)))

    @router.post("/banks")
    async def create_bank(request: Request):
        user, db = user_for(request), request.app.state.db
        form = await request.form()
        name = str(form.get("name", "")).strip()
        if not name or len(name) > 100:
            raise CatalogError("题库名称应为1至100个字符")
        try:
            db.question_banks.insert_one({"owner_id": user["_id"], "name": name,
                "description": str(form.get("description", "")).strip(), "question_ids": [],
                "created_at": datetime.now(timezone.utc)})
        except DuplicateKeyError:
            raise CatalogError("你已经有同名题库")
        return redirect("/banks")

    @router.post("/banks/{bank_id}/settings")
    async def bank_settings(request: Request, bank_id: str):
        user, db = user_for(request), request.app.state.db
        form = await request.form()
        name = str(form.get("name", "")).strip()
        if not name or len(name) > 100:
            raise CatalogError("题库名称应为1至100个字符")
        try:
            result = db.question_banks.update_one({"_id": oid(bank_id), "owner_id": user["_id"]},
                {"$set": {"name": name, "description": str(form.get("description", "")).strip()}})
        except DuplicateKeyError:
            raise CatalogError("你已经有同名题库")
        if not result.matched_count:
            raise CatalogError("题库不存在或无权修改", 404)
        return redirect("/banks")

    @router.post("/banks/{bank_id}/remove/{series_id}")
    def remove_from_bank(request: Request, bank_id: str, series_id: str):
        user = user_for(request)
        result = request.app.state.db.question_banks.update_one(
            {"_id": oid(bank_id), "owner_id": user["_id"]}, {"$pull": {"question_ids": oid(series_id)}})
        if not result.matched_count:
            raise CatalogError("题库不存在或无权修改", 404)
        return redirect(f"/questions?bank_id={bank_id}")

    @router.post("/banks/{bank_id}/delete")
    def delete_bank(request: Request, bank_id: str):
        user = user_for(request)
        result = request.app.state.db.question_banks.delete_one({"_id": oid(bank_id), "owner_id": user["_id"]})
        if not result.deleted_count:
            raise CatalogError("题库不存在或无权删除", 404)
        return redirect("/banks")

    @router.post("/surveys/{survey_id}/questions/from-library")
    async def attach_question(request: Request, survey_id: str):
        user, db = user_for(request), request.app.state.db
        survey, form = draft_for(request, survey_id), await request.form()
        _, version = get_version(db, form.get("version_id"), user["_id"])
        order = max((q.get("order", 0) for q in survey.get("questions", [])), default=-1) + 1
        result = db.surveys.update_one({"_id": survey["_id"], "status": "draft", "published_at": {"$exists": False}},
            {"$push": {"questions": snapshot(version, order)},
             "$set": {"updated_at": datetime.now(timezone.utc)}})
        if not result.matched_count:
            raise CatalogError("问卷已发布，不能再添加题目", 409)
        return redirect(f"/surveys/{survey_id}/edit")

    @router.post("/surveys/{survey_id}/questions/{question_id}/version")
    async def switch_version(request: Request, survey_id: str, question_id: str):
        user, db = user_for(request), request.app.state.db
        survey, form = draft_for(request, survey_id), await request.form()
        old = next((q for q in survey["questions"] if str(q["_id"]) == question_id), None)
        _, version = get_version(db, form.get("version_id"), user["_id"])
        if not old or old.get("source_question_id") != version["series_id"]:
            raise CatalogError("请选择这道题自己的版本")
        replacement = snapshot(version, old.get("order", 0), local_id=question_id)
        result = db.surveys.update_one({"_id": survey["_id"], "status": "draft",
                                      "published_at": {"$exists": False}, "questions._id": question_id},
            {"$set": {"questions.$": replacement, "updated_at": datetime.now(timezone.utc)}})
        if not result.matched_count:
            raise CatalogError("问卷状态已变化，不能替换版本", 409)
        return redirect(f"/surveys/{survey_id}/edit")

    @router.post("/surveys/{survey_id}/clone")
    def clone_survey(request: Request, survey_id: str):
        user, db = user_for(request), request.app.state.db
        survey = owned_survey(request, survey_id)
        if not survey:
            raise CatalogError("问卷不存在或无权访问", 404)
        clone = deepcopy({k: survey.get(k) for k in (
            "title", "description", "allow_anonymous", "allow_multiple", "questions")})
        ids = {str(q["_id"]): uuid.uuid4().hex[:12] for q in clone["questions"]}
        for i, question in enumerate(clone["questions"]):
            question["_id"], question["order"] = ids[str(question["_id"])], i
            question["jump_rules"] = [r for r in question.get("jump_rules", []) if r.get("target_question_id") in ids]
            for rule in question["jump_rules"]:
                rule["target_question_id"] = ids[rule["target_question_id"]]
        clone.update({"title": survey["title"] + "（副本）", "owner_id": user["_id"],
                      "public_id": secrets.token_urlsafe(8), "status": "draft", "deadline": None,
                      "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)})
        result = db.surveys.insert_one(clone)
        return redirect(f"/surveys/{result.inserted_id}/edit")

    app.include_router(router)
