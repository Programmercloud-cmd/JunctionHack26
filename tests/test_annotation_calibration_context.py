"""Selected source dimensions expose deterministic reference scales, not new facts."""
from copy import deepcopy
import math

import pytest

from app.documents import DocumentStore
from app.service import _agent_context, _annotation_calibrations, ask_agent
from test_agent_chat import AgentFixture
from test_backend import png


@pytest.fixture
def drawing(tmp_path):
    store = DocumentStore(tmp_path)
    document = store.add(png(), 'reference-source.png')
    document.revision_id = 'source-revision'
    yield document
    store.close()


def mark(document, *, identity='selected-width', points=None, value=3, unit='m', **extra):
    page = document.pages[0]
    return {'id': identity, 'kind': 'measurement', 'space': 'source', 'revision_id': document.revision_id,
        'page': page.number, 'source_id': page.source_id, 'source_page': page.source_page,
        'floor_id': 'ground', 'value': value, 'unit': unit, 'points': points or [[.1, .2], [.7, .2]],
        'provenance': 'user_provided', **extra}


def test_original_aspect_ratio_and_entered_unit_are_preserved(drawing):
    marks = [mark(drawing, points=[[0, 0], [1, 1]], value=300, unit='cm')]
    before = deepcopy(marks)
    result = _annotation_calibrations(drawing, marks)
    assert len(result) == 1
    hint = result[0]
    assert hint['pixel_span'] == pytest.approx(math.hypot(100, 80))
    assert hint['length_metres'] == 3
    assert hint['metres_per_pixel'] == pytest.approx(3 / math.hypot(100, 80))
    assert hint['pixels_per_metre'] == pytest.approx(math.hypot(100, 80) / 3)
    assert hint['value'] == 300 and hint['unit'] == 'cm' and hint['points'] == marks[0]['points']
    assert hint['user_value_id'] == marks[0]['id'] and hint['floor_id'] == 'ground'
    assert (hint['page'], hint['source_id'], hint['source_page']) == (1, drawing.pages[0].source_id, 1)
    assert hint['provenance'] == 'user_provided' and 'not a printed scale or geometry fact' in hint['basis']
    assert marks == before


@pytest.mark.parametrize('changes', [
    {'space': 'model'}, {'kind': 'point'}, {'value': float('nan')}, {'value': float('inf')}, {'value': 0},
    {'value': -1}, {'value': True}, {'unit': 'unknown'}, {'points': [[.2, .2], [.2, .2]]},
    {'points': [[0, 0], [float('inf'), 1]]}, {'points': [[0, 0], [2, 1]]}, {'points': [[0, 0, 0], [1, 1, 1]]},
    {'page': 99}, {'source_id': 'another-source'}, {'source_page': 99},
])
def test_bad_or_unresolved_derivation_is_skipped_without_mutating_marks(drawing, changes):
    marks = [mark(drawing, **changes)]
    before = deepcopy(marks)
    assert _annotation_calibrations(drawing, marks) == []
    # Compare a serialization-free subset because NaN does not equal itself.
    assert marks[0]['id'] == before[0]['id'] and marks[0]['points'] == before[0]['points']


def test_selected_subset_only_and_no_context_persistence(drawing):
    selected = mark(drawing)
    unattached = mark(drawing, identity='unattached-height', points=[[.1, .2], [.1, .8]])
    drawing.conversation_context = {'evidence_scope': 'sources_and_user', 'user_annotations': [selected]}
    drawing.question_context = {'evidence_scope': 'sources_and_user'}
    before_values, before_context = deepcopy(drawing.user_values), deepcopy(drawing.conversation_context)
    _agent_context(drawing, False)
    hints = drawing.question_context['annotation_calibrations']
    assert [hint['user_value_id'] for hint in hints] == [selected['id']]
    assert unattached['id'] not in {hint['user_value_id'] for hint in hints}
    assert drawing.user_values == before_values and drawing.conversation_context == before_context


def test_source_only_and_native_context_have_no_derived_scales(drawing):
    drawing.conversation_context = {'evidence_scope': 'sources_only', 'user_annotations': [mark(drawing)]}
    drawing.question_context = {'evidence_scope': 'sources_only', 'annotation_calibrations': [{'value': 999}]}
    _agent_context(drawing, False)
    assert 'annotation_calibrations' not in drawing.question_context
    assert not {'value', 'unit', 'label'} & drawing.conversation_context['user_annotations'][0].keys()
    drawing.conversation_context = {'evidence_scope': 'sources_and_user', 'user_annotations': [mark(drawing)]}
    drawing.question_context = {'evidence_scope': 'sources_and_user'}
    _agent_context(drawing, True)
    assert 'annotation_calibrations' not in drawing.question_context


class CapturedReview(AgentFixture):
    def __init__(self):
        super().__init__('technical_advanced')
        self.reviewed = []
    def review_answer(self, document, *args, **kwargs):
        self.reviewed.append(document.snapshot())
        return super().review_answer(document, *args, **kwargs)


def test_worker_and_review_receive_same_selected_reference_scales(drawing):
    marks = [mark(drawing), mark(drawing, identity='selected-height', points=[[.1, .2], [.1, .8]])]
    drawing.conversation_context = {'evidence_scope': 'sources_and_user', 'user_annotations': marks}
    provider = CapturedReview()
    provider.model = provider.advanced_model
    answer = ask_agent(drawing, 'Based on my measurements, what is the footprint in the blueprint?', provider)
    assert answer.status == 'answered'
    assert len(provider.reviewed) == 1
    seen = provider.seen[0][0].question_context['annotation_calibrations']
    reviewed = provider.reviewed[0].question_context['annotation_calibrations']
    assert seen == reviewed and len(seen) == 2
    assert [row['pixel_span'] for row in seen] == pytest.approx([60, 48])
    assert [row['metres_per_pixel'] for row in seen] == pytest.approx([3/60, 3/48])
    # Differing reference scales remain data, rather than an automatic gate.
    assert not drawing.user_values and drawing.question_context is None
