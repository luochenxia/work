"""Real MongoDB tests. Set TEST_MONGODB_URI to enable; each test uses a disposable database."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo import MongoClient

import app.main as main
from app.catalog import (content_fields, create_question, create_version, cross_stats,
                         get_series, migrate_legacy_questions, snapshot, version_usages)
from app.db import init_indexes


@pytest.fixture
def system(monkeypatch):
    uri = os.getenv('TEST_MONGODB_URI')
    if not uri:
        pytest.skip('Set TEST_MONGODB_URI to run isolated real-MongoDB tests')
    name = 'survey_phase2_test_' + uuid.uuid4().hex
    connection = MongoClient(uri, serverSelectionTimeoutMS=3000)
    connection.admin.command('ping')
    monkeypatch.setattr(main, 'settings', replace(main.settings, mongodb_uri=uri, mongodb_db=name))
    try:
        with TestClient(main.app) as alice:
            bob, charlie = TestClient(main.app), TestClient(main.app)
            for client, username in [(alice, 'alice'), (bob, 'bob'), (charlie, 'charlie')]:
                response = client.post('/register', data={'username': username, 'password': 'password123',
                                                         'password_confirm': 'password123'})
                assert response.status_code == 200
            yield main.app.state.db, alice, bob, charlie
            bob.close()
            charlie.close()
    finally:
        assert name.startswith('survey_phase2_test_')
        connection.drop_database(name)
        connection.close()


def make_question(db, client, prompt='你的年龄', kind='number', options=''):
    response = client.post('/questions/new', data={'prompt': prompt, 'question_type': kind,
        'required': '1', 'integer_only': '1' if kind == 'number' else '', 'options_text': options}, follow_redirects=False)
    assert response.status_code == 303, response.text
    series_id = ObjectId(response.headers['location'].split('/')[-1])
    return db.question_versions.find_one({'series_id': series_id, 'version': 1})


def make_survey(db, client, title='调查'):
    response = client.post('/surveys/new', data={'title': title, 'allow_anonymous': '1'}, follow_redirects=False)
    assert response.status_code == 303
    return db.surveys.find_one({'_id': ObjectId(response.headers['location'].split('/')[2])})


def attach(db, client, survey, version):
    response = client.post(f"/surveys/{survey['_id']}/questions/from-library",
                           data={'version_id': str(version['_id'])}, follow_redirects=False)
    assert response.status_code == 303, response.text
    return db.surveys.find_one({'_id': survey['_id']})


def publish_and_answer(db, owner, respondent, survey, values):
    assert owner.post(f"/surveys/{survey['_id']}/publish").status_code == 200
    response = respondent.post(f"/survey/{survey['public_id']}/submit",
                               data={f'q_{key}': value for key, value in values.items()})
    assert '提交成功' in response.text, response.text


def test_private_questions_and_banks_are_isolated(system):
    db, alice, bob, _ = system
    version = make_question(db, alice)
    assert bob.get(f"/questions/{version['series_id']}").status_code == 404
    assert bob.get(f"/questions/{version['series_id']}/stats").status_code == 404
    survey = make_survey(db, bob)
    assert bob.post(f"/surveys/{survey['_id']}/questions/from-library",
                    data={'version_id': str(version['_id'])}).status_code == 404
    bank = db.question_banks.find_one({'owner_id': db.users.find_one({'username': 'alice'})['_id']})
    assert bob.post(f"/banks/{bank['_id']}/settings", data={'name': '越权'}).status_code == 404
    assert db.surveys.find_one({'_id': survey['_id']})['questions'] == []


def test_same_question_is_reused_by_two_surveys(system):
    db, alice, _, _ = system
    version = make_question(db, alice)
    first = attach(db, alice, make_survey(db, alice, 'A'), version)
    second = attach(db, alice, make_survey(db, alice, 'B'), version)
    assert first['questions'][0]['source_version_id'] == second['questions'][0]['source_version_id']
    assert first['questions'][0]['_id'] != second['questions'][0]['_id']
    assert 'A' in alice.get(f"/questions/{version['series_id']}").text


def test_sharing_grants_reuse_but_not_modification(system):
    db, alice, bob, charlie = system
    version = make_question(db, alice)
    assert alice.post(f"/questions/{version['series_id']}/share", data={'usernames': 'bob'}).status_code == 200
    assert bob.get(f"/questions/{version['series_id']}").status_code == 200
    assert charlie.get(f"/questions/{version['series_id']}").status_code == 404
    other = attach(db, bob, make_survey(db, bob, '同事调查'), version)
    own = attach(db, alice, make_survey(db, alice, '作者调查'), version)
    assert other['questions'][0]['source_version_id'] == own['questions'][0]['source_version_id']
    assert bob.post(f"/questions/{version['series_id']}/share", data={'is_public': '1'}).status_code == 404
    assert bob.post(f"/questions/{version['series_id']}/versions/new", data={'parent_version_id': str(version['_id']),
        'prompt': '篡改', 'question_type': 'text'}).status_code == 404
    assert alice.post(f"/questions/{version['series_id']}/share", data={'usernames': 'not_registered'}).status_code == 400


def test_public_sharing_and_fork_are_independent(system):
    db, alice, bob, _ = system
    original = make_question(db, alice)
    alice.post(f"/questions/{original['series_id']}/share", data={'is_public': '1'})
    response = bob.post(f"/questions/{original['series_id']}/fork", data={'version_id': str(original['_id'])}, follow_redirects=False)
    assert response.status_code == 303
    new_id = ObjectId(response.headers['location'].split('/')[-1])
    copied = db.question_versions.find_one({'series_id': new_id})
    assert copied['forked_from_id'] == original['_id']
    assert copied['series_id'] != original['series_id']
    assert db.question_series.find_one({'_id': new_id})['owner_id'] == db.users.find_one({'username': 'bob'})['_id']
    assert '复制来源' in bob.get(f'/questions/{new_id}').text


def test_new_versions_and_restore_never_overwrite_old_content(system):
    db, alice, _, _ = system
    first = make_question(db, alice)
    frozen = deepcopy(first)
    response = alice.post(f"/questions/{first['series_id']}/versions/new", data={
        'parent_version_id': str(first['_id']), 'prompt': '你的年龄（月）', 'question_type': 'number'}, follow_redirects=False)
    assert response.status_code == 303
    second = db.question_versions.find_one({'series_id': first['series_id'], 'version': 2})
    assert second['parent_version_id'] == first['_id']
    assert db.question_versions.find_one({'_id': first['_id']}) == frozen
    assert alice.post(f"/questions/{first['series_id']}/restore/{first['_id']}").status_code == 200
    third = db.question_versions.find_one({'series_id': first['series_id'], 'version': 3})
    assert third['parent_version_id'] == second['_id']
    assert third['restored_from_id'] == first['_id']
    assert third['prompt'] == first['prompt']
    detail = alice.get(f"/questions/{first['series_id']}")
    assert '恢复自 v1' in detail.text
    assert db.question_versions.count_documents({'series_id': first['series_id']}) == 3


@pytest.mark.parametrize('closed', [False, True])
def test_all_question_mutation_routes_reject_published_surveys(system, closed):
    db, alice, _, _ = system
    version = make_question(db, alice)
    survey = attach(db, alice, make_survey(db, alice), version)
    local_id = survey['questions'][0]['_id']
    alice.post(f"/surveys/{survey['_id']}/publish")
    if closed:
        alice.post(f"/surveys/{survey['_id']}/close")
    before = db.surveys.find_one({'_id': survey['_id']})['questions']
    routes = [('/questions', {'prompt': '新增', 'question_type': 'text'}),
              (f'/questions/{local_id}/delete', {}),
              (f'/questions/{local_id}/jump-rules', {'operator': 'equals', 'value': '1', 'target_question_id': local_id}),
              (f'/questions/{local_id}/jump-rules/missing/delete', {}),
              ('/questions/from-library', {'version_id': str(version['_id'])}),
              (f'/questions/{local_id}/version', {'version_id': str(version['_id'])})]
    for suffix, data in routes:
        response = alice.post(f"/surveys/{survey['_id']}{suffix}", data=data)
        assert response.status_code == 409, (suffix, response.text)
    assert db.surveys.find_one({'_id': survey['_id']})['questions'] == before
    assert 'id="question-form"' not in alice.get(f"/surveys/{survey['_id']}/edit").text


def test_draft_can_explicitly_select_new_version_without_changing_other_surveys(system):
    db, alice, _, _ = system
    first = make_question(db, alice)
    old = attach(db, alice, make_survey(db, alice, '旧问卷'), first)
    draft = attach(db, alice, make_survey(db, alice, '新问卷'), first)
    alice.post(f"/surveys/{old['_id']}/publish")
    owner = db.users.find_one({'username': 'alice'})['_id']
    second = create_version(db, owner, first['series_id'], first['_id'], {**first, 'prompt': '你的周岁年龄'})
    local_id = draft['questions'][0]['_id']
    assert alice.post(f"/surveys/{draft['_id']}/questions/{local_id}/version",
                      data={'version_id': str(second['_id'])}).status_code == 200
    assert db.surveys.find_one({'_id': old['_id']})['questions'] == old['questions']
    changed = db.surveys.find_one({'_id': draft['_id']})['questions'][0]
    assert changed['_id'] == local_id
    assert changed['source_version_id'] == second['_id']
    assert changed['jump_rules'] == []


def test_cross_survey_stats_scope_versions_and_distribution(system):
    db, alice, bob, charlie = system
    first = make_question(db, alice)
    alice.post(f"/questions/{first['series_id']}/share", data={'usernames': 'bob'})
    survey_a = attach(db, alice, make_survey(db, alice, 'A'), first)
    survey_b = attach(db, bob, make_survey(db, bob, 'B'), first)
    publish_and_answer(db, alice, charlie, survey_a, {survey_a['questions'][0]['_id']: '20'})
    publish_and_answer(db, bob, charlie, survey_b, {survey_b['questions'][0]['_id']: '30'})
    author_id = db.users.find_one({'username': 'alice'})['_id']
    recipient_id = db.users.find_one({'username': 'bob'})['_id']
    series = get_series(db, first['series_id'], author_id)
    data, uses = cross_stats(db, series, first, author_id)
    assert data['summary']['count'] == 2
    assert data['summary']['average'] == 25
    assert data['distribution'] == [{'_id': 20, 'count': 1}, {'_id': 30, 'count': 1}]
    assert len(uses) == 2
    recipient_stats, recipient_uses = cross_stats(db, series, first, recipient_id)
    assert recipient_stats['summary']['average'] == 30
    assert len(recipient_uses) == 1
    second = create_version(db, author_id, first['series_id'], first['_id'], {**first, 'prompt': '年龄（月）'})
    second_stats, _ = cross_stats(db, series, second, author_id)
    assert second_stats['summary'] is None
    response = alice.get(f"/questions/{first['series_id']}/stats")
    assert response.status_code == 200
    assert '25.00' in response.text and '暂无回答' in response.text
    assert db.responses.count_documents({'respondent_id': None}) == 2


@pytest.mark.parametrize('kind,options,value,expected', [
    ('single', '满意\n一般', '满意', [{'_id': '满意', 'count': 1}, {'_id': '一般', 'count': 0}]),
    ('multiple', 'A\nB\nC', ['A', 'B'], [{'_id': 'A', 'count': 1}, {'_id': 'B', 'count': 1}, {'_id': 'C', 'count': 0}]),
    ('text', '', '希望增加案例', None),
])
def test_cross_survey_stats_support_other_question_types(system, kind, options, value, expected):
    db, alice, _, charlie = system
    version = make_question(db, alice, '反馈', kind, options)
    survey = attach(db, alice, make_survey(db, alice), version)
    publish_and_answer(db, alice, charlie, survey, {survey['questions'][0]['_id']: value})
    user_id = db.users.find_one({'username': 'alice'})['_id']
    data, _ = cross_stats(db, get_series(db, version['series_id'], user_id), version, user_id)
    if expected is not None:
        assert data['items'] == expected
    else:
        assert data['items'][0]['value'] == value


def test_migration_is_idempotent_and_preserves_published_answers(system):
    db, alice, _, _ = system
    user_id = db.users.find_one({'username': 'alice'})['_id']
    question = {'_id': 'legacy-age', 'prompt': '旧年龄题', 'type': 'number', 'required': True,
                'validation': {}, 'options': [], 'jump_rules': [], 'order': 0}
    survey_id = db.surveys.insert_one({'owner_id': user_id, 'title': '第一阶段问卷',
        'status': 'published', 'published_at': datetime.now(timezone.utc), 'questions': [question]}).inserted_id
    answer_id = db.responses.insert_one({'survey_id': survey_id, 'answers': [{'question_id': 'legacy-age', 'value': 18}]}).inserted_id
    answer_before = db.responses.find_one({'_id': answer_id})
    migrate_legacy_questions(db)
    migrate_legacy_questions(db)
    migrated = db.surveys.find_one({'_id': survey_id})['questions'][0]
    assert all(migrated[key] == value for key, value in question.items())
    assert db.question_versions.count_documents({}) == 1
    assert db.responses.find_one({'_id': answer_id}) == answer_before
    series = get_series(db, migrated['source_question_id'], user_id)
    version = db.question_versions.find_one({'_id': migrated['source_version_id']})
    data, _ = cross_stats(db, series, version, user_id)
    assert data['summary']['average'] == 18


def test_banks_track_series_latest_versions_and_remove_without_deleting(system):
    db, alice, _, _ = system
    version = make_question(db, alice)
    alice.post('/banks', data={'name': '人口信息', 'description': '常用问题'})
    bank = db.question_banks.find_one({'name': '人口信息'})
    assert alice.post('/banks', data={'name': '人口信息'}).status_code == 400
    alice.post(f"/questions/{version['series_id']}/bank", data={'bank_id': str(bank['_id'])})
    assert '你的年龄' in alice.get(f"/questions?bank_id={bank['_id']}").text
    alice.post(f"/banks/{bank['_id']}/remove/{version['series_id']}")
    assert db.question_banks.find_one({'_id': bank['_id']})['question_ids'] == []
    assert db.question_versions.find_one({'_id': version['_id']}) is not None
    assert alice.get('/banks').status_code == 200
    alice.post(f"/banks/{bank['_id']}/delete")
    assert db.question_banks.find_one({'_id': bank['_id']}) is None
    assert db.question_versions.find_one({'_id': version['_id']}) is not None


def test_cross_stats_match_survey_and_local_question_as_a_pair(system):
    db, alice, _, _ = system
    version = make_question(db, alice)
    first = attach(db, alice, make_survey(db, alice, 'A'), version)
    second = attach(db, alice, make_survey(db, alice, 'B'), version)
    q1, q2 = first['questions'][0]['_id'], second['questions'][0]['_id']
    db.responses.insert_many([
        {'survey_id': first['_id'], 'answers': [{'question_id': q1, 'value': 20}, {'question_id': 'noise', 'value': 999}]},
        {'survey_id': second['_id'], 'answers': [{'question_id': q2, 'value': 30}, {'question_id': q1, 'value': 999}]},
    ])
    user_id = db.users.find_one({'username': 'alice'})['_id']
    data, _ = cross_stats(db, get_series(db, version['series_id'], user_id), version, user_id)
    assert data['summary']['count'] == 2 and data['summary']['average'] == 25


def test_bank_uses_latest_version_while_old_versions_remain_selectable(system):
    db, alice, _, _ = system
    first = make_question(db, alice, '年龄旧版')
    user_id = db.users.find_one({'username': 'alice'})['_id']
    bank = db.question_banks.find_one({'owner_id': user_id})
    second = create_version(db, user_id, first['series_id'], first['_id'], {**first, 'prompt': '年龄新版'})
    response = alice.get(f"/questions?bank_id={bank['_id']}")
    assert response.status_code == 200 and '年龄新版' in response.text
    survey = attach(db, alice, make_survey(db, alice), first)
    assert survey['questions'][0]['prompt'] == '年龄旧版'
    detail = alice.get(f"/questions/{first['series_id']}/versions/new?base={second['_id']}")
    assert detail.status_code == 200 and '年龄新版' in detail.text


def test_revoking_share_does_not_break_existing_survey_snapshots(system):
    db, alice, bob, charlie = system
    version = make_question(db, alice)
    alice.post(f"/questions/{version['series_id']}/share", data={'usernames': 'bob'})
    survey = attach(db, bob, make_survey(db, bob), version)
    alice.post(f"/questions/{version['series_id']}/share", data={})
    assert bob.get(f"/questions/{version['series_id']}").status_code == 404
    publish_and_answer(db, bob, charlie, survey, {survey['questions'][0]['_id']: '24'})
    assert db.responses.count_documents({'survey_id': survey['_id']}) == 1


def test_concurrent_version_numbers_are_unique_and_head_is_latest(system):
    db, alice, _, _ = system
    first = make_question(db, alice)
    user_id = db.users.find_one({'username': 'alice'})['_id']
    with ThreadPoolExecutor(max_workers=4) as pool:
        result = list(pool.map(lambda i: create_version(db, user_id, first['series_id'], first['_id'],
                                   {**first, 'prompt': f'并行版本{i}'}), range(4)))
    assert len({v['version'] for v in result}) == 4
    assert all(v['parent_version_id'] == first['_id'] for v in result)
    series = get_series(db, first['series_id'], user_id)
    assert series['latest_version'] == 5
    assert db.question_versions.find_one({'_id': series['latest_version_id']})['version'] == 5


def test_clone_keeps_version_links_but_rewrites_local_jump_targets(system):
    db, alice, _, _ = system
    first, second = make_question(db, alice), make_question(db, alice, '建议', 'text')
    survey = attach(db, alice, make_survey(db, alice), first)
    survey = attach(db, alice, survey, second)
    q1, q2 = survey['questions']
    alice.post(f"/surveys/{survey['_id']}/questions/{q1['_id']}/jump-rules",
               data={'operator': 'gt', 'value': '30', 'target_question_id': q2['_id']})
    alice.post(f"/surveys/{survey['_id']}/publish")
    response = alice.post(f"/surveys/{survey['_id']}/clone", follow_redirects=False)
    clone = db.surveys.find_one({'_id': ObjectId(response.headers['location'].split('/')[2])})
    assert clone['status'] == 'draft' and 'published_at' not in clone
    assert clone['questions'][0]['_id'] != q1['_id']
    assert clone['questions'][0]['source_version_id'] == q1['source_version_id']
    assert clone['questions'][0]['jump_rules'][0]['target_question_id'] == clone['questions'][1]['_id']
