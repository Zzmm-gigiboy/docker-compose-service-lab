import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
import app as module


def test_messages_are_preview_only():
    with tempfile.TemporaryDirectory() as temp:
        module.DB_PATH = Path(temp) / 'test.db'
        module.init_db()
        client = TestClient(module.app)
        assert client.get('/health').json()['sending_enabled'] is False
        c = client.post('/api/contacts', json={'name': 'Amina', 'month': 12, 'day': 20, 'channel': 'email'})
        assert c.status_code == 201
        p = client.post('/api/preview', json={'contact_id': c.json()['id'], 'template': 'Happy birthday, {name}!'})
        assert p.json() == {'channel': 'email', 'message': 'Happy birthday, Amina!', 'sent': False}
        assert client.get('/api/contacts').json()[0]['name'] == 'Amina'
        assert client.post('/api/contacts', json={'name': 'Bad', 'month': 2, 'day': 30, 'channel': 'sms'}).status_code == 422
        assert client.post('/api/preview', json={'contact_id': 999, 'template': 'Hi'}).status_code == 404
