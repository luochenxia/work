"""Add clearly labelled phase-two demo records; never clear existing data."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from bson import ObjectId

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.catalog import create_question, create_version, migrate_legacy_questions, snapshot
from app.config import settings
from app.db import create_client, init_indexes
from app.security import hash_password


def run():
    client = create_client(settings)
    try:
        db = client[settings.mongodb_db]
        init_indexes(db)
        migrate_legacy_questions(db)
        if db.question_series.find_one({'demo_tag': 'phase2'}):
            print('Phase-two demo already exists; no records were changed.')
            return
        now = datetime.now(timezone.utc)
        accounts = []
        for username in ('phase2_author', 'phase2_colleague'):
            if db.users.find_one({'username': username}):
                raise RuntimeError('Demo username already exists; use a clean demo database.')
        for username in ('phase2_author', 'phase2_colleague'):
            accounts.append(db.users.insert_one({'username': username,
                'password_hash': hash_password('password123'), 'created_at': now}).inserted_id)
        author, colleague = accounts
        v1 = create_question(db, author, {'prompt': '你的年龄（周岁）', 'type': 'number',
            'required': True, 'options': [], 'validation': {'min_value': 0, 'max_value': 120, 'integer_only': True}})
        v2 = create_version(db, author, v1['series_id'], v1['_id'],
            {**v1, 'prompt': '你的年龄（月）', 'validation': {'min_value': 0, 'max_value': 1500, 'integer_only': True}})
        v3 = create_version(db, author, v1['series_id'], v2['_id'], v1, restored_from=v1['_id'])
        db.question_series.update_one({'_id': v1['series_id']},
            {'$set': {'demo_tag': 'phase2', 'shared_with': [colleague]}})
        satisfaction = create_question(db, author, {'prompt': '你对课程满意吗？', 'type': 'single',
            'required': True, 'options': ['满意', '一般', '不满意'], 'validation': {}})
        for title, owner, version, value in [
            ('演示：春季调查（旧版本）', author, v1, 20),
            ('演示：秋季调查（旧版本）', author, v1, 22),
            ('演示：同事调查（共享题目）', colleague, v1, 24),
            ('演示：下一期调查（草稿）', author, v3, None),
        ]:
            question = snapshot(version, 0)
            survey = {'owner_id': owner, 'title': title, 'description': '仅用于演示的合成数据',
                'public_id': 'demo_' + str(ObjectId()), 'questions': [question],
                'status': 'published' if value else 'draft', 'allow_anonymous': True,
                'allow_multiple': False, 'deadline': None, 'created_at': now, 'updated_at': now}
            if value:
                survey['published_at'] = now
            else:
                survey['questions'].append(snapshot(satisfaction, 1))
            survey_id = db.surveys.insert_one(survey).inserted_id
            if value:
                db.responses.insert_one({'survey_id': survey_id, 'respondent_id': None,
                    'is_anonymous': True, 'answers': [{'question_id': question['_id'], 'value': value}],
                    'visited_question_ids': [question['_id']], 'submitted_at': now})
        print('Demo ready: phase2_author / password123; phase2_colleague / password123')
    finally:
        client.close()


if __name__ == '__main__':
    run()
