from copy import deepcopy

import pytest
from bson import ObjectId

from app.catalog import CatalogError, parse_content, snapshot
from app.domain import validate_submission


@pytest.mark.parametrize('fields', [
    {'prompt': ''}, {'question_type': 'unknown'},
    {'question_type': 'single', 'options_text': 'A\nA'},
    {'question_type': 'multiple', 'options_text': 'A\nB', 'min_choices': '3'},
    {'question_type': 'text', 'min_length': '8', 'max_length': '3'},
    {'min_value': 'nan'}, {'max_value': 'inf'}, {'min_value': 'bad'},
])
def test_invalid_catalog_content_is_rejected(fields):
    with pytest.raises(CatalogError):
        parse_content({'prompt': '年龄', 'question_type': 'number', **fields})


def test_snapshot_does_not_share_mutable_configuration():
    version = {'_id': ObjectId(), 'series_id': ObjectId(), 'version': 1,
               'prompt': '选课', 'type': 'single', 'options': ['A', 'B'],
               'validation': {'min_choices': 1}}
    baseline = deepcopy(version)
    first, second = snapshot(version, 0), snapshot(version, 1)
    first['options'].append('C')
    first['validation']['min_choices'] = 2
    assert version == baseline
    assert second['options'] == ['A', 'B']
    assert first['_id'] != second['_id']
    assert first['source_version_id'] == second['source_version_id']


@pytest.mark.parametrize('value', ['nan', 'inf', '-inf'])
def test_non_finite_answers_cannot_pollute_numeric_statistics(value):
    result = validate_submission({'questions': [{'_id': 'age', 'prompt': '年龄',
        'type': 'number', 'required': True, 'validation': {}, 'order': 0}]}, {'age': value})
    assert result.errors
