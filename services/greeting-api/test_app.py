import tempfile
from datetime import date
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import app as module


@pytest.fixture
def test_client():
    with tempfile.TemporaryDirectory() as temp:
        module.DB_PATH = Path(temp) / 'test.db'
        module.init_db()
        with TestClient(module.app) as client:
            yield client


def test_health_endpoint(test_client):
    res = test_client.get('/health')
    assert res.status_code == 200
    data = res.json()
    assert data['status'] == 'ok'
    assert data['sending_enabled'] is False


def test_messages_are_preview_only(test_client):
    assert test_client.get('/health').json()['sending_enabled'] is False
    c = test_client.post('/api/contacts', json={'name': 'Amina', 'month': 12, 'day': 20, 'channel': 'email'})
    assert c.status_code == 201
    p = test_client.post('/api/preview', json={'contact_id': c.json()['id'], 'template': 'Happy birthday, {name}!'})
    assert p.json() == {'channel': 'email', 'message': 'Happy birthday, Amina!', 'sent': False}
    assert test_client.get('/api/contacts').json()[0]['name'] == 'Amina'
    assert test_client.post('/api/contacts', json={'name': 'Bad', 'month': 2, 'day': 30, 'channel': 'sms'}).status_code == 422
    assert test_client.post('/api/preview', json={'contact_id': 999, 'template': 'Hi'}).status_code == 404


def test_contacts_crud_and_sorting(test_client):
    assert test_client.get('/api/contacts').json() == []

    test_client.post('/api/contacts', json={'name': 'Zara', 'month': 5, 'day': 15, 'channel': 'email'})
    test_client.post('/api/contacts', json={'name': 'Alice', 'month': 8, 'day': 22, 'channel': 'sms'})
    test_client.post('/api/contacts', json={'name': 'Bob', 'month': 1, 'day': 1, 'channel': 'email'})

    contacts = test_client.get('/api/contacts').json()
    assert len(contacts) == 3
    # Check alphabetical ordering by name
    names = [c['name'] for c in contacts]
    assert names == ['Alice', 'Bob', 'Zara']


def test_contact_calendar_validation_and_leap_year(test_client):
    # Feb 29 on leap year (2024 is a leap year) is accepted
    res_leap = test_client.post('/api/contacts', json={'name': 'Leap Baby', 'month': 2, 'day': 29, 'channel': 'sms'})
    assert res_leap.status_code == 201
    assert res_leap.json()['day'] == 29

    # Feb 30 is impossible
    assert test_client.post('/api/contacts', json={'name': 'Bad Feb', 'month': 2, 'day': 30, 'channel': 'sms'}).status_code == 422

    # April 31 does not exist (30 days in April)
    assert test_client.post('/api/contacts', json={'name': 'Bad Apr', 'month': 4, 'day': 31, 'channel': 'email'}).status_code == 422

    # Month out of range
    assert test_client.post('/api/contacts', json={'name': 'Month 13', 'month': 13, 'day': 1, 'channel': 'email'}).status_code == 422
    assert test_client.post('/api/contacts', json={'name': 'Month 0', 'month': 0, 'day': 1, 'channel': 'email'}).status_code == 422

    # Day out of range
    assert test_client.post('/api/contacts', json={'name': 'Day 32', 'month': 1, 'day': 32, 'channel': 'email'}).status_code == 422
    assert test_client.post('/api/contacts', json={'name': 'Day 0', 'month': 1, 'day': 0, 'channel': 'email'}).status_code == 422


def test_contact_payload_validation(test_client):
    # Name too short (< 2)
    assert test_client.post('/api/contacts', json={'name': 'A', 'month': 1, 'day': 1, 'channel': 'email'}).status_code == 422
    # Name too long (> 100)
    assert test_client.post('/api/contacts', json={'name': 'A' * 101, 'month': 1, 'day': 1, 'channel': 'email'}).status_code == 422

    # Unsupported channels (pattern='^(email|sms)$')
    assert test_client.post('/api/contacts', json={'name': 'Tester', 'month': 1, 'day': 1, 'channel': 'slack'}).status_code == 422
    assert test_client.post('/api/contacts', json={'name': 'Tester', 'month': 1, 'day': 1, 'channel': 'whatsapp'}).status_code == 422
    assert test_client.post('/api/contacts', json={'name': 'Tester', 'month': 1, 'day': 1, 'channel': ''}).status_code == 422

    # Empty payload or missing fields
    assert test_client.post('/api/contacts', json={}).status_code == 422
    assert test_client.post('/api/contacts', json={'name': 'Only Name'}).status_code == 422


def test_upcoming_greetings(test_client):
    today = date.today()
    # Add a contact with birthday today
    test_client.post('/api/contacts', json={'name': 'Today Bday', 'month': today.month, 'day': today.day, 'channel': 'email'})

    # Default days window (30)
    res = test_client.get('/api/upcoming')
    assert res.status_code == 200
    items = res.json()
    assert any(item['name'] == 'Today Bday' and item['days_until'] == 0 for item in items)

    # Custom window
    res_custom = test_client.get('/api/upcoming?days=365')
    assert res_custom.status_code == 200

    # Boundary validation: days must be 0-366
    assert test_client.get('/api/upcoming?days=-1').status_code == 422
    assert test_client.get('/api/upcoming?days=367').status_code == 422


def test_preview_templating_and_boundaries(test_client):
    contact = test_client.post('/api/contacts', json={'name': 'Elena Rostova', 'month': 7, 'day': 14, 'channel': 'sms'}).json()
    cid = contact['id']

    # Template replacing multiple placeholders
    res = test_client.post('/api/preview', json={
        'contact_id': cid,
        'template': 'Hello {name}, your special day is on month {month}, day {day}! Cheers {name}!'
    })
    assert res.status_code == 200
    assert res.json() == {
        'channel': 'sms',
        'message': 'Hello Elena Rostova, your special day is on month 7, day 14! Cheers Elena Rostova!',
        'sent': False
    }

    # Non-existent contact ID returns 404
    assert test_client.post('/api/preview', json={'contact_id': 99999, 'template': 'Hi {name}'}).status_code == 404

    # Empty template (< 1 char) returns 422
    assert test_client.post('/api/preview', json={'contact_id': cid, 'template': ''}).status_code == 422

    # Oversized template (> 500 chars) returns 422
    assert test_client.post('/api/preview', json={'contact_id': cid, 'template': 'X' * 501}).status_code == 422
