"""A source location must not erase explicitly requested, attached dimensions."""
from copy import deepcopy

import pytest

from app.agent_chat import agent_chat
from app.annotations import save_annotation
from app.reasoning import source_only_question
from app.schemas import DraftAnswer
from test_agent_chat import AgentFixture, Runner, request
from test_backend import png
from app.bundles import BuildingStore


QUESTION = 'based on my measurements, what is the footprint of the whole building seen in the blueprint'

EXCLUDED_AUTHORED_INPUTS = [
    'Do not use my marked dimensions; what is the footprint in the blueprint?',
    "Don't use our drawn measurements; what is the footprint in the blueprint?",
    'Without using the measurements I supplied, what is the footprint in the blueprint?',
    'Do not use the dimensions I provided; answer from the blueprint.',
    "Don't use the measurements I entered; answer from the blueprint.",
    'Without relying on the dimensions we marked, what is the footprint in the blueprint?',
]


@pytest.mark.parametrize('question', [
    QUESTION,
    'Using my dimensions, what is the building area shown in the plan?',
    'Use my measurements to estimate the footprint from the blueprint.',
    'Use the attached measurements to calculate the footprint shown on this blueprint.',
    'What is the footprint in the blueprint based on the measurements I provided?',
    'Based on my measurements, what is the footprint of the whole building that the blueprint shows?',
    'Using my marked dimensions, estimate the footprint of the building the drawing shows.',
    'Use my measurements, not dimensions printed in the drawing, to estimate the building footprint.',
])
def test_explicit_user_dimensions_survive_incidental_source_location(question):
    assert not source_only_question(question)


@pytest.mark.parametrize('question', [
    'What dimension is printed in the original drawing?',
    'My measurements are 3 m, but what dimension is printed in the original drawing?',
    'Use my measurements but answer from the drawing only.',
    'Based on my measurements, answer solely from the original blueprint.',
    'Based on my measurements, only the original drawing may establish the answer.',
    'Using my dimensions, the plan alone must establish the answer.',
    'Use my measurements but base the result only on the original blueprint.',
    'Use my measurements, but base the answer only on the original sources.',
    'My dimensions are available. What does the original drawing specify?',
    'Do not use my measurements. What is the footprint in the blueprint?',
    'Ignore my dimensions and use the original drawing.',
    'Without my measurements, what is the footprint in the drawing?',
    'Using my measurements, but without relying on my dimensions, what is the footprint?',
    'What is shown in the drawing?',
    *EXCLUDED_AUTHORED_INPUTS,
])
def test_explicit_source_authority_and_exclusions_still_require_originals(question):
    assert source_only_question(question)


class ContextFixture(AgentFixture):
    def __init__(self, *, draft=None):
        super().__init__('technical_advanced', route={'evidence_scope': 'sources_and_user'},
                         draft=draft, reviews=('supported', 'supported'))
        self.reviewed = []

    def review_answer(self, document, *args, **kwargs):
        self.reviewed.append(document.snapshot())
        return super().review_answer(document, *args, **kwargs)


@pytest.fixture
def measured_source(tmp_path):
    store = BuildingStore(tmp_path)
    document = store.add(png(), 'synthetic-footprint.png')
    marks = []
    for points in ([[.2, .2], [.4, .2]], [[.2, .2], [.2, .4]]):
        marks.append(save_annotation(store, document.id, {
            'revision_id': document.revision_id, 'kind': 'measurement', 'space': 'source',
            'page': 1, 'value': 3, 'unit': 'm', 'points': points}))
    yield store, document, marks
    store.close()


def test_exact_footprint_message_keeps_both_measurements_for_worker_and_review(measured_source):
    store, document, marks = measured_source
    provider = ContextFixture()
    before = deepcopy(marks)
    result = agent_chat(store, Runner(), lambda: provider,
                        request(document, QUESTION, annotation_ids=[mark['id'] for mark in marks]),
                        document=document, annotations=marks)
    expected = {mark['id']: (3, 'm') for mark in marks}
    for seen in [provider.seen[0][0], *provider.reviewed]:
        context = seen.question_context
        assert context['evidence_scope'] == 'sources_and_user'
        assert {row['id']: (row['value'], row['unit']) for row in context['user_values']} == expected
        assert all(row['provenance'] == 'user_provided' for row in context['user_values'])
        assert {row['id']: (row['value'], row['unit']) for row in context['conversation_context']['user_annotations']} == expected
    assert provider.calls == [(name, QUESTION) for name in ('route', 'answer', 'review')]
    assert marks == before and not document.user_values
    assert result['answer']['gate'] is None


@pytest.mark.parametrize('question', [
    'My measurements are 3 m, but what dimension is printed in the original drawing?',
    'Use my measurements but answer from the drawing only.',
    'Use my measurements, but base the answer only on the original sources.',
    'Ignore my measurements. What is the footprint in the blueprint?',
    *EXCLUDED_AUTHORED_INPUTS,
])
def test_explicit_source_only_worker_and_review_do_not_receive_mark_numbers(measured_source, question):
    store, document, marks = measured_source
    provider = ContextFixture()
    agent_chat(store, Runner(), lambda: provider,
               request(document, question, annotation_ids=[mark['id'] for mark in marks]),
               document=document, annotations=marks)
    for seen in [provider.seen[0][0], *provider.reviewed]:
        assert seen.question_context['evidence_scope'] == 'sources_only'
        assert seen.question_context['user_values'] == []
        for mark in seen.question_context['conversation_context']['user_annotations']:
            assert not {'value', 'unit', 'label'} & mark.keys()
            assert mark['points']


@pytest.mark.parametrize('question', [
    'My measurements are 3 m, but what dimension is printed in the original drawing?',
    'Use my measurements, but base the answer only on the original sources.',
    *EXCLUDED_AUTHORED_INPUTS,
])
def test_source_only_cannot_cite_attached_measurements_even_if_review_supports_it(measured_source, question):
    store, document, marks = measured_source
    provider = ContextFixture(draft=DraftAnswer(status='answered', answer='The original specifies 3 m.',
                                               user_value_evidence=[marks[0]['id']]))
    result = agent_chat(store, Runner(), lambda: provider,
                        request(document, question, annotation_ids=[mark['id'] for mark in marks]),
                        document=document, annotations=marks)
    assert result['answer']['status'] == 'unclear'
    assert result['answer']['user_value_evidence'] == []
    assert '3 m' not in result['answer']['answer']


def test_asking_for_measurements_does_not_import_unattached_saved_marks(measured_source):
    store, document, marks = measured_source
    provider = ContextFixture()
    agent_chat(store, Runner(), lambda: provider, request(document, QUESTION),
               document=document, annotations=[])
    for seen in [provider.seen[0][0], *provider.reviewed]:
        assert seen.question_context['evidence_scope'] == 'sources_and_user'
        assert seen.question_context['user_values'] == []
        assert seen.question_context['conversation_context']['user_annotations'] == []
    assert len(marks) == 2
