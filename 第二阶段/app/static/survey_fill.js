(function () {
  "use strict";

  const config = window.SURVEY_CONFIG || { questions: [] };
  const questions = config.questions || [];
  const form = document.getElementById("survey-form");
  const backButton = document.getElementById("back-button");
  const nextButton = document.getElementById("next-button");
  const submitButton = document.getElementById("submit-button");
  const progressBar = document.getElementById("progress-bar");
  const progressText = document.getElementById("progress-text");
  const history = [];
  let currentId = questions.length ? questions[0].id : null;

  function questionById(id) {
    return questions.find((question) => question.id === id);
  }

  function stepById(id) {
    return document.querySelector(`[data-question-id="${id}"]`);
  }

  function readAnswer(question) {
    const name = `q_${question.id}`;
    if (question.type === "multiple") {
      return [...form.querySelectorAll(`input[name="${name}"]:checked`)].map((el) => el.value);
    }
    if (question.type === "single") {
      const selected = form.querySelector(`input[name="${name}"]:checked`);
      return selected ? selected.value : "";
    }
    const input = form.querySelector(`[name="${name}"]`);
    return input ? input.value.trim() : "";
  }

  function validate(question, answer) {
    const rules = question.validation || {};
    const blank = answer === "" || answer == null || (Array.isArray(answer) && !answer.length);
    if (question.required && blank) return "这是一道必答题";
    if (blank) return "";
    if (question.type === "multiple") {
      if (rules.min_choices != null && answer.length < rules.min_choices) return `至少选择 ${rules.min_choices} 项`;
      if (rules.max_choices != null && answer.length > rules.max_choices) return `最多选择 ${rules.max_choices} 项`;
    }
    if (question.type === "text") {
      if (rules.min_length != null && answer.length < rules.min_length) return `至少输入 ${rules.min_length} 个字符`;
      if (rules.max_length != null && answer.length > rules.max_length) return `最多输入 ${rules.max_length} 个字符`;
    }
    if (question.type === "number") {
      const value = Number(answer);
      if (!Number.isFinite(value)) return "请输入有效数字";
      if (rules.integer_only && !Number.isInteger(value)) return "请输入整数";
      if (rules.min_value != null && value < rules.min_value) return `数值不能小于 ${rules.min_value}`;
      if (rules.max_value != null && value > rules.max_value) return `数值不能大于 ${rules.max_value}`;
    }
    return "";
  }

  function matches(rule, answer) {
    if (rule.operator === "equals") return String(answer) === String(rule.value);
    if (rule.operator === "contains") return Array.isArray(answer) && answer.map(String).includes(String(rule.value));
    const actual = Number(answer);
    const expected = Number(rule.value);
    if (!Number.isFinite(actual) || !Number.isFinite(expected)) return false;
    if (rule.operator === "gt") return actual > expected;
    if (rule.operator === "gte") return actual >= expected;
    if (rule.operator === "lt") return actual < expected;
    if (rule.operator === "lte") return actual <= expected;
    return false;
  }

  function nextQuestionId(question, answer) {
    const matchedRule = (question.jump_rules || []).find((rule) => matches(rule, answer));
    if (matchedRule) return matchedRule.target_question_id;
    const index = questions.findIndex((item) => item.id === question.id);
    return index >= 0 && index + 1 < questions.length ? questions[index + 1].id : null;
  }

  function showQuestion(id) {
    document.querySelectorAll(".question-step").forEach((step) => { step.hidden = true; });
    currentId = id;
    const step = stepById(id);
    if (step) step.hidden = false;
    const index = questions.findIndex((question) => question.id === id);
    const percent = questions.length ? ((index + 1) / questions.length) * 100 : 0;
    progressBar.style.width = `${percent}%`;
    progressText.textContent = `第 ${index + 1} 题，共 ${questions.length} 题`;
    backButton.hidden = history.length === 0;
    const isLastDefaultQuestion = index === questions.length - 1;
    nextButton.hidden = isLastDefaultQuestion;
    submitButton.hidden = !isLastDefaultQuestion;
  }

  function validateCurrent() {
    const question = questionById(currentId);
    if (!question) return false;
    const answer = readAnswer(question);
    const error = validate(question, answer);
    const step = stepById(currentId);
    step.querySelector(".field-error").textContent = error;
    return !error;
  }

  nextButton.addEventListener("click", function () {
    if (!validateCurrent()) return;
    const question = questionById(currentId);
    const target = nextQuestionId(question, readAnswer(question));
    if (!target) return;
    history.push(currentId);
    showQuestion(target);
  });

  backButton.addEventListener("click", function () {
    if (!history.length) return;
    showQuestion(history.pop());
  });

  form.addEventListener("submit", function (event) {
    if (!validateCurrent()) event.preventDefault();
  });

  if (currentId) showQuestion(currentId);
})();

