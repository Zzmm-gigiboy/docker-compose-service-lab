import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import app as module


@pytest.fixture
def test_client():
    with tempfile.TemporaryDirectory() as temp:
        module.DB_PATH = Path(temp) / 'pocket.db'
        module.init_db()
        with TestClient(module.app) as client:
            yield client


def test_health(test_client):
    res = test_client.get('/health')
    assert res.status_code == 200
    assert res.json() == {'status': 'ok'}


def test_crud(test_client):
    note = test_client.post('/api/notes', json={'title': 'Build a demo'})
    assert note.status_code == 201
    note_id = note.json()['id']
    assert len(test_client.get('/api/notes').json()) == 1
    assert test_client.patch(f'/api/notes/{note_id}', json={'completed': True}).json()['completed']
    assert test_client.delete(f'/api/notes/{note_id}').status_code == 204
    assert test_client.patch(f'/api/notes/{note_id}', json={'completed': False}).status_code == 404
    assert test_client.post('/api/notes', json={'title': ''}).status_code == 422


def test_notes_empty_and_ordering(test_client):
    # Fresh database has no notes
    assert test_client.get('/api/notes').json() == []

    # Insert sequential notes
    n1 = test_client.post('/api/notes', json={'title': 'First Note'}).json()
    n2 = test_client.post('/api/notes', json={'title': 'Second Note'}).json()
    n3 = test_client.post('/api/notes', json={'title': 'Third Note'}).json()

    notes = test_client.get('/api/notes').json()
    assert len(notes) == 3
    # Check ID DESC order
    ids = [n['id'] for n in notes]
    assert ids == [n3['id'], n2['id'], n1['id']]
    # Default completion is False
    assert all(not n['completed'] for n in notes)


def test_note_creation_validation(test_client):
    # Valid note at max length (100 chars)
    max_title = 'A' * 100
    res = test_client.post('/api/notes', json={'title': max_title})
    assert res.status_code == 201
    assert res.json()['title'] == max_title

    # Exceeding max length (101 chars) returns 422
    assert test_client.post('/api/notes', json={'title': 'A' * 101}).status_code == 422

    # Empty string title returns 422
    assert test_client.post('/api/notes', json={'title': ''}).status_code == 422

    # Missing title field returns 422
    assert test_client.post('/api/notes', json={}).status_code == 422

    # Title with whitespace gets trimmed
    res_trimmed = test_client.post('/api/notes', json={'title': '   Padded Note   '})
    assert res_trimmed.status_code == 201
    assert res_trimmed.json()['title'] == 'Padded Note'


def test_note_toggle_and_not_found(test_client):
    note = test_client.post('/api/notes', json={'title': 'Toggle Me'}).json()
    nid = note['id']

    # Toggle to True
    res_true = test_client.patch(f'/api/notes/{nid}', json={'completed': True})
    assert res_true.status_code == 200
    assert res_true.json() == {'id': nid, 'completed': True}

    # Verify state in list
    listed = test_client.get('/api/notes').json()
    assert listed[0]['completed'] is True

    # Toggle back to False
    res_false = test_client.patch(f'/api/notes/{nid}', json={'completed': False})
    assert res_false.status_code == 200
    assert res_false.json() == {'id': nid, 'completed': False}

    # Patch non-existent note returns 404
    assert test_client.patch('/api/notes/99999', json={'completed': True}).status_code == 404

    # Missing completed field returns 422
    assert test_client.patch(f'/api/notes/{nid}', json={}).status_code == 422


def test_note_delete_idempotency_and_404(test_client):
    note = test_client.post('/api/notes', json={'title': 'To be deleted'}).json()
    nid = note['id']

    # Delete existing note
    res = test_client.delete(f'/api/notes/{nid}')
    assert res.status_code == 204

    # Verify no longer in list
    assert test_client.get('/api/notes').json() == []

    # Second delete returns 404
    assert test_client.delete(f'/api/notes/{nid}').status_code == 404

    # Deleting non-existent ID returns 404
    assert test_client.delete('/api/notes/99999').status_code == 404
