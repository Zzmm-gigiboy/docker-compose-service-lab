"""Occasion Messenger prototype: no messages are ever sent."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import date, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DB_PATH = Path(os.environ.get('GREETINGS_DB', str(Path(__file__).with_name('greetings.sqlite3'))))
app = FastAPI(title='Occasion Messenger API')
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5174', 'http://127.0.0.1:5174'], allow_methods=['*'], allow_headers=['*'])


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS contacts(id INTEGER PRIMARY KEY, name TEXT NOT NULL, month INTEGER NOT NULL, day INTEGER NOT NULL, channel TEXT NOT NULL)')


class Contact(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)
    channel: str = Field(pattern='^(email|sms)$')


class Preview(BaseModel):
    contact_id: int
    template: str = Field(min_length=1, max_length=500)


def birthday_in_year(month, day, year):
    try:
        return date(year, month, day)
    except ValueError:
        if month == 2 and day == 29:
            return date(year, 2, 28)
        raise


@app.get('/health')
def health():
    return {'status': 'ok', 'sending_enabled': False}


@app.get('/api/contacts')
def contacts():
    with db() as conn:
        return [dict(r) for r in conn.execute('SELECT * FROM contacts ORDER BY name').fetchall()]


@app.post('/api/contacts', status_code=201)
def add_contact(contact: Contact):
    try:
        birthday_in_year(contact.month, contact.day, 2024)
    except ValueError:
        raise HTTPException(422, detail='Invalid calendar date')
    with db() as conn:
        cur = conn.execute('INSERT INTO contacts(name,month,day,channel) VALUES(?,?,?,?)',
                           (contact.name.strip(), contact.month, contact.day, contact.channel))
        return {'id': cur.lastrowid, **contact.model_dump()}


@app.get('/api/upcoming')
def upcoming(days: int = 30):
    if not 0 <= days <= 366:
        raise HTTPException(422, detail='days must be 0-366')
    today = date.today()
    with db() as conn:
        result = []
        for row in conn.execute('SELECT * FROM contacts'):
            when = birthday_in_year(row['month'], row['day'], today.year)
            if when < today:
                when = birthday_in_year(row['month'], row['day'], today.year + 1)
            if when <= today + timedelta(days=days):
                result.append({'name': row['name'], 'date': when.isoformat(), 'days_until': (when-today).days})
    return sorted(result, key=lambda r: r['days_until'])


@app.post('/api/preview')
def preview(item: Preview):
    with db() as conn:
        row = conn.execute('SELECT name,month,day,channel FROM contacts WHERE id=?', (item.contact_id,)).fetchone()
        if not row:
            raise HTTPException(404, detail='Contact not found')
        text = item.template.replace('{name}', row['name']).replace('{month}', str(row['month'])).replace('{day}', str(row['day']))
        return {'channel': row['channel'], 'message': text, 'sent': False}


init_db()
