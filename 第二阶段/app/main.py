from __future__ import annotations

import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pymongo.errors import DuplicateKeyError
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .db import create_client, init_indexes
from .domain import JUMP_OPERATORS, QUESTION_TYPES, validate_submission
from .security import hash_password, make_dedupe_key, verify_password
from .stats import build_question_stats
from .catalog import CatalogError, choices, create_question, migrate_legacy_questions, parse_content, snapshot


BASE_DIR = Path(__file__).resolve().parent
LOCAL_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = create_client(settings)
    client.admin.command("ping")
    db = client[settings.mongodb_db]
    init_indexes(db)
    migrate_legacy_questions(db)
    app.state.mongo_client = client
    app.state.db = db
    yield
    client.close()


app = FastAPI(title="MongoDB 问卷系统", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=False,
    max_age=60 * 60 * 12,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url=url, status_code=303)


def parse_object_id(value: str) -> Optional[ObjectId]:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


def current_user(request: Request) -> Optional[dict[str, Any]]:
    user_id = request.session.get("user_id")
    object_id = parse_object_id(user_id) if user_id else None
    return request.app.state.db.users.find_one({"_id": object_id}) if object_id else None


def owned_survey(request: Request, survey_id: str) -> Optional[dict[str, Any]]:
    user = current_user(request)
    object_id = parse_object_id(survey_id)
    if not user or not object_id:
        return None
    return request.app.state.db.surveys.find_one(
        {"_id": object_id, "owner_id": user["_id"]}
    )


def page(
    request: Request,
    name: str,
    *,
    status_code: int = 200,
    **context: Any,
) -> HTMLResponse:
    context.update({"request": request, "current_user": current_user(request)})
    return templates.TemplateResponse(
        request=request, name=name, context=context, status_code=status_code
    )


def message_page(
    request: Request, title: str, message: str, back_url: str = "/"
) -> HTMLResponse:
    return page(
        request,
        "message.html",
        title=title,
        message=message,
        back_url=back_url,
    )


def parse_deadline(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    local_value = datetime.fromisoformat(value)
    return local_value.replace(tzinfo=LOCAL_TIMEZONE).astimezone(timezone.utc)


def deadline_for_form(value: Optional[datetime]) -> str:
    if not value:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(LOCAL_TIMEZONE).strftime("%Y-%m-%dT%H:%M")


def optional_int(value: Optional[str]) -> Optional[int]:
    if value is None or not str(value).strip():
        return None
    return int(value)


def optional_float(value: Optional[str]) -> Optional[float]:
    if value is None or not str(value).strip():
        return None
    return float(value)


@app.get("/health")
def health(request: Request):
    request.app.state.db.command("ping")
    return {"status": "ok", "database": settings.mongodb_db}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    user = current_user(request)
    if not user:
        return redirect("/login")
    surveys = list(
        request.app.state.db.surveys.find({"owner_id": user["_id"]}).sort(
            "created_at", -1
        )
    )
    response_counts = {
        row["_id"]: row["count"]
        for row in request.app.state.db.responses.aggregate(
            [
                {"$match": {"survey_id": {"$in": [s["_id"] for s in surveys]}}},
                {"$group": {"_id": "$survey_id", "count": {"$sum": 1}}},
            ]
        )
    } if surveys else {}
    return page(
        request,
        "dashboard.html",
        surveys=surveys,
        response_counts=response_counts,
    )


@app.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    return page(request, "register.html", error=None)


@app.post("/register", response_class=HTMLResponse)
def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
):
    username = username.strip()
    if len(username) < 3 or len(username) > 30:
        return page(request, "register.html", error="用户名长度应为3至30个字符")
    if len(password) < 8:
        return page(request, "register.html", error="密码至少需要8个字符")
    if password != password_confirm:
        return page(request, "register.html", error="两次输入的密码不一致")
    try:
        result = request.app.state.db.users.insert_one(
            {
                "username": username,
                "password_hash": hash_password(password),
                "created_at": datetime.now(timezone.utc),
            }
        )
    except DuplicateKeyError:
        return page(request, "register.html", error="用户名已存在")
    request.session["user_id"] = str(result.inserted_id)
    return redirect("/")


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return page(request, "login.html", error=None)


@app.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    user = request.app.state.db.users.find_one({"username": username.strip()})
    if not user or not verify_password(password, user["password_hash"]):
        return page(request, "login.html", error="用户名或密码错误")
    next_url = request.session.get("next_url")
    request.session.clear()
    request.session["user_id"] = str(user["_id"])
    return redirect(next_url if isinstance(next_url, str) and next_url.startswith("/") else "/")


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return redirect("/login")


@app.get("/surveys/new", response_class=HTMLResponse)
def new_survey_form(request: Request):
    if not current_user(request):
        return redirect("/login")
    return page(request, "survey_new.html", error=None)


@app.post("/surveys/new", response_class=HTMLResponse)
def create_survey(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    allow_anonymous: Optional[str] = Form(None),
    allow_multiple: Optional[str] = Form(None),
    deadline: Optional[str] = Form(None),
):
    user = current_user(request)
    if not user:
        return redirect("/login")
    title = title.strip()
    if not title:
        return page(request, "survey_new.html", error="问卷标题不能为空")
    now = datetime.now(timezone.utc)
    result = request.app.state.db.surveys.insert_one(
        {
            "owner_id": user["_id"],
            "public_id": secrets.token_urlsafe(8),
            "title": title,
            "description": description.strip(),
            "allow_anonymous": bool(allow_anonymous),
            "allow_multiple": bool(allow_multiple),
            "status": "draft",
            "deadline": parse_deadline(deadline),
            "questions": [],
            "created_at": now,
            "updated_at": now,
        }
    )
    return redirect(f"/surveys/{result.inserted_id}/edit")


@app.get("/surveys/{survey_id}/edit", response_class=HTMLResponse)
def edit_survey(request: Request, survey_id: str, bank_id: Optional[str] = None):
    survey = owned_survey(request, survey_id)
    if not survey:
        return message_page(request, "无权访问", "问卷不存在或不属于当前用户")
    survey["deadline_form"] = deadline_for_form(survey.get("deadline"))
    user = current_user(request)
    _, versions = choices(request.app.state.db, user["_id"], bank_id)
    return page(request, "survey_edit.html", survey=survey, error=None, versions=versions,
                banks=list(request.app.state.db.question_banks.find({"owner_id": user["_id"]})),
                selected_bank_id=bank_id or "", editable=survey.get("status") == "draft" and not survey.get("published_at"))


def ensure_editable(survey):
    if survey.get("status") != "draft" or survey.get("published_at"):
        raise CatalogError("已发布或已关闭的问卷题目已锁定，请复制为新问卷后修改", 409)


@app.post("/surveys/{survey_id}/settings")
def update_survey_settings(
    request: Request,
    survey_id: str,
    title: str = Form(...),
    description: str = Form(""),
    allow_anonymous: Optional[str] = Form(None),
    allow_multiple: Optional[str] = Form(None),
    deadline: Optional[str] = Form(None),
):
    survey = owned_survey(request, survey_id)
    if not survey:
        return message_page(request, "无权访问", "问卷不存在或不属于当前用户")
    if not title.strip():
        return message_page(
            request, "设置错误", "问卷标题不能为空", f"/surveys/{survey_id}/edit"
        )
    request.app.state.db.surveys.update_one(
        {"_id": survey["_id"]},
        {
            "$set": {
                "title": title.strip(),
                "description": description.strip(),
                "allow_anonymous": bool(allow_anonymous),
                "allow_multiple": bool(allow_multiple),
                "deadline": parse_deadline(deadline),
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )
    return redirect(f"/surveys/{survey_id}/edit")


@app.post("/surveys/{survey_id}/questions", response_class=HTMLResponse)
def add_question(
    request: Request,
    survey_id: str,
    prompt: str = Form(...),
    question_type: str = Form(...),
    required: Optional[str] = Form(None),
    options_text: str = Form(""),
    min_choices: Optional[str] = Form(None),
    max_choices: Optional[str] = Form(None),
    min_length: Optional[str] = Form(None),
    max_length: Optional[str] = Form(None),
    min_value: Optional[str] = Form(None),
    max_value: Optional[str] = Form(None),
    integer_only: Optional[str] = Form(None),
):
    survey = owned_survey(request, survey_id)
    if not survey:
        return message_page(request, "无权访问", "问卷不存在或不属于当前用户")
    ensure_editable(survey)
    if question_type not in QUESTION_TYPES:
        return message_page(request, "题型错误", "请选择有效题型", f"/surveys/{survey_id}/edit")
    if not prompt.strip():
        return message_page(request, "题目错误", "题目内容不能为空", f"/surveys/{survey_id}/edit")
    options = [line.strip() for line in options_text.splitlines() if line.strip()]
    if question_type in {"single", "multiple"} and len(options) < 2:
        return message_page(
            request, "选项不足", "单选题和多选题至少需要两个选项", f"/surveys/{survey_id}/edit"
        )
    try:
        validation = {
            "min_choices": optional_int(min_choices),
            "max_choices": optional_int(max_choices),
            "min_length": optional_int(min_length),
            "max_length": optional_int(max_length),
            "min_value": optional_float(min_value),
            "max_value": optional_float(max_value),
            "integer_only": bool(integer_only),
        }
    except ValueError:
        return message_page(
            request, "校验值错误", "数量和范围必须填写有效数字", f"/surveys/{survey_id}/edit"
        )
    validation = {key: value for key, value in validation.items() if value is not None}
    if any(
        validation.get(key, 0) < 0
        for key in ("min_choices", "max_choices", "min_length", "max_length")
    ):
        return message_page(
            request, "校验值错误", "数量和长度不能为负数", f"/surveys/{survey_id}/edit"
        )
    for minimum_key, maximum_key in (
        ("min_choices", "max_choices"),
        ("min_length", "max_length"),
        ("min_value", "max_value"),
    ):
        minimum = validation.get(minimum_key)
        maximum = validation.get(maximum_key)
        if minimum is not None and maximum is not None and minimum > maximum:
            return message_page(
                request,
                "校验值错误",
                "最小值不能大于最大值",
                f"/surveys/{survey_id}/edit",
            )
    question = {
        "_id": uuid.uuid4().hex[:12],
        "prompt": prompt.strip(),
        "type": question_type,
        "required": bool(required),
        "options": options,
        "validation": validation,
        "jump_rules": [],
        "order": max((q.get("order", 0) for q in survey.get("questions", [])), default=-1) + 1,
    }
    question.update(parse_content({"prompt": prompt, "question_type": question_type,
        "required": required, "options_text": options_text, "min_choices": min_choices,
        "max_choices": max_choices, "min_length": min_length, "max_length": max_length,
        "min_value": min_value, "max_value": max_value, "integer_only": integer_only}))
    version = create_question(request.app.state.db, survey["owner_id"], question)
    question = snapshot(version, question["order"], local_id=question["_id"])
    result = request.app.state.db.surveys.update_one(
        {"_id": survey["_id"], "status": "draft", "published_at": {"$exists": False}},
        {
            "$push": {"questions": question},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
    )
    if not result.matched_count:
        raise CatalogError("问卷已发布，不能再添加题目", 409)
    return redirect(f"/surveys/{survey_id}/edit")


@app.post("/surveys/{survey_id}/questions/{question_id}/delete")
def delete_question(request: Request, survey_id: str, question_id: str):
    survey = owned_survey(request, survey_id)
    if not survey:
        return message_page(request, "无权访问", "问卷不存在或不属于当前用户")
    ensure_editable(survey)
    # Replace the edited snapshot array in one atomic draft-only write.
    questions = [q for q in survey["questions"] if str(q["_id"]) != question_id]
    for question in questions:
        question["jump_rules"] = [r for r in question.get("jump_rules", []) if r.get("target_question_id") != question_id]
    result = request.app.state.db.surveys.update_one(
        {"_id": survey["_id"], "status": "draft", "published_at": {"$exists": False},
         "updated_at": survey["updated_at"]},
        {
            "$set": {"questions": questions, "updated_at": datetime.now(timezone.utc)},
        },
    )
    if not result.matched_count:
        raise CatalogError("问卷已发布或其他编辑已更新，请刷新后重试", 409)
    return redirect(f"/surveys/{survey_id}/edit")


@app.post("/surveys/{survey_id}/questions/{question_id}/jump-rules")
def add_jump_rule(
    request: Request,
    survey_id: str,
    question_id: str,
    operator: str = Form(...),
    value: str = Form(...),
    target_question_id: str = Form(...),
):
    survey = owned_survey(request, survey_id)
    if not survey:
        return message_page(request, "无权访问", "问卷不存在或不属于当前用户")
    ensure_editable(survey)
    questions = sorted(survey.get("questions", []), key=lambda q: q.get("order", 0))
    positions = {str(q["_id"]): i for i, q in enumerate(questions)}
    if operator not in JUMP_OPERATORS:
        return message_page(request, "规则错误", "无效的比较方式", f"/surveys/{survey_id}/edit")
    if question_id not in positions or target_question_id not in positions:
        return message_page(request, "规则错误", "题目不存在", f"/surveys/{survey_id}/edit")
    if positions[target_question_id] <= positions[question_id]:
        return message_page(
            request,
            "规则错误",
            "当前版本只允许跳转到后续题目，以避免循环跳转",
            f"/surveys/{survey_id}/edit",
        )
    rule = {
        "_id": uuid.uuid4().hex[:12],
        "operator": operator,
        "value": value.strip(),
        "target_question_id": target_question_id,
    }
    result = request.app.state.db.surveys.update_one(
        {"_id": survey["_id"], "questions._id": question_id, "status": "draft", "published_at": {"$exists": False}},
        {
            "$push": {"questions.$.jump_rules": rule},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
    )
    if not result.matched_count:
        raise CatalogError("问卷已发布，不能再修改跳转规则", 409)
    return redirect(f"/surveys/{survey_id}/edit")


@app.post("/surveys/{survey_id}/questions/{question_id}/jump-rules/{rule_id}/delete")
def delete_jump_rule(
    request: Request, survey_id: str, question_id: str, rule_id: str
):
    survey = owned_survey(request, survey_id)
    if not survey:
        return message_page(request, "无权访问", "问卷不存在或不属于当前用户")
    ensure_editable(survey)
    result = request.app.state.db.surveys.update_one(
        {"_id": survey["_id"], "questions._id": question_id, "status": "draft", "published_at": {"$exists": False}},
        {"$pull": {"questions.$.jump_rules": {"_id": rule_id}}, "$set": {"updated_at": datetime.now(timezone.utc)}},
    )
    if not result.matched_count:
        raise CatalogError("问卷已发布，不能再修改跳转规则", 409)
    return redirect(f"/surveys/{survey_id}/edit")


@app.post("/surveys/{survey_id}/publish")
def publish_survey(request: Request, survey_id: str):
    survey = owned_survey(request, survey_id)
    if not survey:
        return message_page(request, "无权访问", "问卷不存在或不属于当前用户")
    ensure_editable(survey)
    if not survey.get("questions"):
        return message_page(
            request, "无法发布", "请至少添加一道题", f"/surveys/{survey_id}/edit"
        )
    request.app.state.db.surveys.update_one(
        {"_id": survey["_id"], "status": "draft", "published_at": {"$exists": False}},
        {"$set": {"status": "published", "published_at": datetime.now(timezone.utc)}},
    )
    return redirect("/")


@app.post("/surveys/{survey_id}/close")
def close_survey(request: Request, survey_id: str):
    survey = owned_survey(request, survey_id)
    if not survey:
        return message_page(request, "无权访问", "问卷不存在或不属于当前用户")
    request.app.state.db.surveys.update_one(
        {"_id": survey["_id"]},
        {"$set": {"status": "closed", "closed_at": datetime.now(timezone.utc)}},
    )
    return redirect("/")


def survey_availability_error(survey: dict[str, Any]) -> Optional[str]:
    if survey.get("status") != "published":
        return "该问卷尚未发布或已经关闭"
    deadline = survey.get("deadline")
    if deadline:
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > deadline:
            return "该问卷已超过截止时间"
    return None


@app.get("/survey/{public_id}", response_class=HTMLResponse)
def fill_survey(request: Request, public_id: str):
    user = current_user(request)
    if not user:
        request.session["next_url"] = f"/survey/{public_id}"
        return redirect("/login")
    survey = request.app.state.db.surveys.find_one({"public_id": public_id})
    if not survey:
        return message_page(request, "问卷不存在", "请检查访问链接")
    error = survey_availability_error(survey)
    if error:
        return message_page(request, "暂时无法填写", error)
    dedupe_key = make_dedupe_key(
        settings.session_secret, str(survey["_id"]), str(user["_id"])
    )
    if not survey.get("allow_multiple") and request.app.state.db.responses.find_one(
        {"survey_id": survey["_id"], "single_submission_key": dedupe_key}
    ):
        return message_page(request, "已经提交", "该问卷不允许重复填写")
    client_survey = {
        "questions": [
            {
                "id": str(q["_id"]),
                "type": q["type"],
                "required": q.get("required", False),
                "validation": q.get("validation", {}),
                "jump_rules": q.get("jump_rules", []),
            }
            for q in sorted(survey.get("questions", []), key=lambda item: item.get("order", 0))
        ]
    }
    return page(
        request,
        "survey_fill.html",
        survey=survey,
        client_survey=client_survey,
        errors={},
    )


@app.post("/survey/{public_id}/submit", response_class=HTMLResponse)
async def submit_survey(request: Request, public_id: str):
    user = current_user(request)
    if not user:
        request.session["next_url"] = f"/survey/{public_id}"
        return redirect("/login")
    survey = request.app.state.db.surveys.find_one({"public_id": public_id})
    if not survey:
        return message_page(request, "问卷不存在", "请检查访问链接")
    error = survey_availability_error(survey)
    if error:
        return message_page(request, "无法提交", error)

    form = await request.form()
    raw_answers: dict[str, Any] = {}
    for question in survey.get("questions", []):
        question_id = str(question["_id"])
        field_name = f"q_{question_id}"
        raw_answers[question_id] = (
            form.getlist(field_name)
            if question["type"] == "multiple"
            else form.get(field_name)
        )
    result = validate_submission(survey, raw_answers)
    if result.errors:
        return message_page(
            request,
            "提交失败",
            "；".join(result.errors.values()),
            f"/survey/{public_id}",
        )

    dedupe_key = make_dedupe_key(
        settings.session_secret, str(survey["_id"]), str(user["_id"])
    )
    response_doc: dict[str, Any] = {
        "survey_id": survey["_id"],
        "respondent_id": None if survey.get("allow_anonymous") else user["_id"],
        "is_anonymous": bool(survey.get("allow_anonymous")),
        "answers": result.answers,
        "visited_question_ids": result.visited_question_ids,
        "submitted_at": datetime.now(timezone.utc),
    }
    if not survey.get("allow_multiple"):
        response_doc["single_submission_key"] = dedupe_key
    try:
        request.app.state.db.responses.insert_one(response_doc)
    except DuplicateKeyError:
        return message_page(request, "已经提交", "该问卷不允许重复填写")
    return message_page(request, "提交成功", "感谢填写，回答已经保存")


@app.get("/surveys/{survey_id}/stats", response_class=HTMLResponse)
def survey_stats(request: Request, survey_id: str, question_id: Optional[str] = None):
    survey = owned_survey(request, survey_id)
    if not survey:
        return message_page(request, "无权访问", "问卷不存在或不属于当前用户")
    total = request.app.state.db.responses.count_documents({"survey_id": survey["_id"]})
    questions = sorted(survey.get("questions", []), key=lambda q: q.get("order", 0))
    if question_id:
        questions = [question for question in questions if str(question["_id"]) == question_id]
        if not questions:
            return message_page(request, "题目不存在", "无法找到要查看统计的题目")
    stats = [
        {"question": question, "data": build_question_stats(request.app.state.db, survey["_id"], question)}
        for question in questions
    ]
    return page(
        request,
        "stats.html",
        survey=survey,
        total=total,
        stats=stats,
        selected_question_id=question_id,
    )


from .catalog_routes import install_catalog_routes

install_catalog_routes(app, page, redirect, current_user, owned_survey, message_page)

