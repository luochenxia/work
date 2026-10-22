import unittest

from app.domain import validate_submission
from app.security import hash_password, make_dedupe_key, verify_password


def make_survey(*questions):
    return {"questions": list(questions)}


def question(question_id, question_type, **kwargs):
    return {
        "_id": question_id,
        "prompt": kwargs.pop("prompt", question_id),
        "type": question_type,
        "required": kwargs.pop("required", False),
        "options": kwargs.pop("options", []),
        "validation": kwargs.pop("validation", {}),
        "jump_rules": kwargs.pop("jump_rules", []),
        "order": kwargs.pop("order", 0),
        **kwargs,
    }


class ValidationTests(unittest.TestCase):
    def test_required_single_choice(self):
        survey = make_survey(
            question("q1", "single", required=True, options=["A", "B"])
        )
        result = validate_submission(survey, {"q1": ""})
        self.assertIn("q1", result.errors)

    def test_single_choice_rejects_unknown_option(self):
        survey = make_survey(question("q1", "single", options=["A", "B"]))
        result = validate_submission(survey, {"q1": "C"})
        self.assertEqual(result.errors["q1"], "请选择有效选项")

    def test_multiple_choice_limits(self):
        survey = make_survey(
            question(
                "q1",
                "multiple",
                options=["A", "B", "C"],
                validation={"min_choices": 2, "max_choices": 2},
            )
        )
        too_few = validate_submission(survey, {"q1": ["A"]})
        valid = validate_submission(survey, {"q1": ["A", "B"]})
        self.assertIn("q1", too_few.errors)
        self.assertFalse(valid.errors)

    def test_text_length(self):
        survey = make_survey(
            question("q1", "text", validation={"min_length": 3, "max_length": 5})
        )
        self.assertIn("q1", validate_submission(survey, {"q1": "ab"}).errors)
        self.assertFalse(validate_submission(survey, {"q1": "abcd"}).errors)

    def test_number_range_and_integer(self):
        survey = make_survey(
            question(
                "q1",
                "number",
                validation={"min_value": 0, "max_value": 120, "integer_only": True},
            )
        )
        self.assertIn("q1", validate_submission(survey, {"q1": "20.5"}).errors)
        self.assertIn("q1", validate_submission(survey, {"q1": "121"}).errors)
        valid = validate_submission(survey, {"q1": "20"})
        self.assertFalse(valid.errors)
        self.assertEqual(valid.answers[0]["value"], 20)

    def test_single_choice_jump_skips_middle_question(self):
        survey = make_survey(
            question(
                "q1",
                "single",
                options=["A", "B"],
                jump_rules=[
                    {
                        "operator": "equals",
                        "value": "A",
                        "target_question_id": "q3",
                    }
                ],
                order=0,
            ),
            question("q2", "text", required=True, order=1),
            question("q3", "text", required=True, order=2),
        )
        result = validate_submission(survey, {"q1": "A", "q3": "完成"})
        self.assertFalse(result.errors)
        self.assertEqual(result.visited_question_ids, ["q1", "q3"])

    def test_multiple_contains_jump(self):
        survey = make_survey(
            question(
                "q1",
                "multiple",
                options=["苹果", "香蕉"],
                jump_rules=[
                    {
                        "operator": "contains",
                        "value": "香蕉",
                        "target_question_id": "q3",
                    }
                ],
                order=0,
            ),
            question("q2", "text", order=1),
            question("q3", "text", order=2),
        )
        result = validate_submission(survey, {"q1": ["香蕉"], "q3": "ok"})
        self.assertEqual(result.visited_question_ids, ["q1", "q3"])

    def test_cycle_is_detected(self):
        survey = make_survey(
            question(
                "q1",
                "single",
                options=["A"],
                jump_rules=[
                    {"operator": "equals", "value": "A", "target_question_id": "q1"}
                ],
            )
        )
        result = validate_submission(survey, {"q1": "A"})
        self.assertIn("_survey", result.errors)


class SecurityTests(unittest.TestCase):
    def test_password_hash_round_trip(self):
        encoded = hash_password("correct-horse-battery-staple")
        self.assertTrue(verify_password("correct-horse-battery-staple", encoded))
        self.assertFalse(verify_password("wrong", encoded))
        self.assertNotIn("correct-horse", encoded)

    def test_dedupe_key_is_stable_and_non_plaintext(self):
        first = make_dedupe_key("secret", "survey", "user")
        second = make_dedupe_key("secret", "survey", "user")
        self.assertEqual(first, second)
        self.assertNotIn("user", first)


if __name__ == "__main__":
    unittest.main()

