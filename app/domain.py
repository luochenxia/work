from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


QUESTION_TYPES = {"single", "multiple", "text", "number"}
JUMP_OPERATORS = {"equals", "contains", "gt", "gte", "lt", "lte"}


@dataclass
class SubmissionResult:
    answers: list[dict[str, Any]]
    errors: dict[str, str]
    visited_question_ids: list[str]


def _is_blank(value: Any) -> bool:
    return value is None or value == "" or value == []


def normalize_answer(question: dict[str, Any], raw_value: Any) -> Any:
    question_type = question.get("type")
    if question_type == "multiple":
        if raw_value is None:
            return []
        if isinstance(raw_value, list):
            return [str(item).strip() for item in raw_value if str(item).strip()]
        return [str(raw_value).strip()] if str(raw_value).strip() else []

    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None

    if question_type == "number":
        try:
            number = float(text)
        except (TypeError, ValueError):
            return text
        if question.get("validation", {}).get("integer_only") and number.is_integer():
            return int(number)
        return number
    return text


def validate_answer(question: dict[str, Any], answer: Any) -> Optional[str]:
    prompt = question.get("prompt", "该题")
    if question.get("required") and _is_blank(answer):
        return f"{prompt}为必答题"
    if _is_blank(answer):
        return None

    question_type = question.get("type")
    validation = question.get("validation", {})
    options = question.get("options", [])

    if question_type == "single":
        if answer not in options:
            return "请选择有效选项"

    elif question_type == "multiple":
        if any(item not in options for item in answer):
            return "多选答案包含无效选项"
        minimum = validation.get("min_choices")
        maximum = validation.get("max_choices")
        if minimum is not None and len(answer) < minimum:
            return f"至少选择{minimum}项"
        if maximum is not None and len(answer) > maximum:
            return f"最多选择{maximum}项"

    elif question_type == "text":
        length = len(str(answer))
        minimum = validation.get("min_length")
        maximum = validation.get("max_length")
        if minimum is not None and length < minimum:
            return f"至少输入{minimum}个字符"
        if maximum is not None and length > maximum:
            return f"最多输入{maximum}个字符"

    elif question_type == "number":
        if not isinstance(answer, (int, float)) or isinstance(answer, bool):
            return "请输入有效数字"
        if validation.get("integer_only") and not float(answer).is_integer():
            return "请输入整数"
        minimum = validation.get("min_value")
        maximum = validation.get("max_value")
        if minimum is not None and answer < minimum:
            return f"数值不能小于{minimum:g}"
        if maximum is not None and answer > maximum:
            return f"数值不能大于{maximum:g}"

    else:
        return "未知题型"
    return None


def _rule_matches(operator: str, expected: Any, answer: Any) -> bool:
    if operator == "equals":
        return str(answer) == str(expected)
    if operator == "contains":
        return isinstance(answer, list) and str(expected) in {str(x) for x in answer}
    try:
        actual_number = float(answer)
        expected_number = float(expected)
    except (TypeError, ValueError):
        return False
    if operator == "gt":
        return actual_number > expected_number
    if operator == "gte":
        return actual_number >= expected_number
    if operator == "lt":
        return actual_number < expected_number
    if operator == "lte":
        return actual_number <= expected_number
    return False


def select_jump_target(question: dict[str, Any], answer: Any) -> Optional[str]:
    for rule in question.get("jump_rules", []):
        if _rule_matches(rule.get("operator", ""), rule.get("value"), answer):
            return rule.get("target_question_id")
    return None


def validate_submission(
    survey: dict[str, Any], raw_answers: dict[str, Any]
) -> SubmissionResult:
    questions = sorted(survey.get("questions", []), key=lambda q: q.get("order", 0))
    if not questions:
        return SubmissionResult([], {"_survey": "问卷没有题目"}, [])

    positions = {str(q["_id"]): index for index, q in enumerate(questions)}
    answers: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    visited: list[str] = []
    seen: set[str] = set()
    index = 0

    while 0 <= index < len(questions):
        question = questions[index]
        question_id = str(question["_id"])
        if question_id in seen:
            errors["_survey"] = "跳转规则形成循环，请联系问卷创建者"
            break
        seen.add(question_id)
        visited.append(question_id)

        answer = normalize_answer(question, raw_answers.get(question_id))
        error = validate_answer(question, answer)
        if error:
            errors[question_id] = error
        elif not _is_blank(answer):
            answers.append({"question_id": question_id, "value": answer})

        target = select_jump_target(question, answer)
        if target:
            if target not in positions:
                errors["_survey"] = "问卷包含无效的跳转目标"
                break
            index = positions[target]
        else:
            index += 1

    return SubmissionResult(answers, errors, visited)

