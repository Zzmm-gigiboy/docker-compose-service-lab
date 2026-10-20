from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
import app as module


def test_crud():
    with TemporaryDirectory() as t:
        module.DB_PATH = Path(t) / 'pocket.db'
        module.init_db()
        client = TestClient(module.app)
        note = client.post('/api/notes', json={'title': 'Build a demo'})
        assert note.status_code == 201
        note_id = note.json()['id']
        assert len(client.get('/api/notes').json()) == 1
        assert client.patch(f'/api/notes/{note_id}', json={'completed': True}).json()['completed']
        assert client.delete(f'/api/notes/{note_id}').status_code == 204
        assert client.patch(f'/api/notes/{note_id}', json={'completed': False}).status_code == 404
        assert client.post('/api/notes', json={'title': ''}).status_code == 422
