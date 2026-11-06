"""Pocket Planner companion REST API."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

DB_PATH = Path(os.environ.get('POCKET_DB', str(Path(__file__).with_name('pocket.sqlite3'))))
app = FastAPI(title='Pocket Planner API')


@contextmanager
def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, title TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0)')


class NewNote(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class UpdateNote(BaseModel):
    completed: bool


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.get('/api/notes')
def notes():
    with db() as conn:
        return [{**dict(r), 'completed': bool(r['completed'])} for r in conn.execute('SELECT * FROM notes ORDER BY id DESC')]


@app.post('/api/notes', status_code=201)
def create(item: NewNote):
    clean_title = item.title.strip()
    if not clean_title:
        raise HTTPException(422, detail='Title cannot be empty or whitespace only')
    with db() as conn:
        cur = conn.execute('INSERT INTO notes(title) VALUES(?)', (clean_title,))
        return {'id': cur.lastrowid, 'title': clean_title, 'completed': False}


@app.patch('/api/notes/{note_id}')
def toggle(note_id: int, update: UpdateNote):
    if note_id <= 0:
        raise HTTPException(422, detail='Note ID must be a positive integer')
    with db() as conn:
        res = conn.execute('UPDATE notes SET completed=? WHERE id=?', (int(update.completed), note_id))
        if not res.rowcount:
            raise HTTPException(404, detail='Note not found')
        return {'id': note_id, 'completed': update.completed}


@app.delete('/api/notes/{note_id}', status_code=204)
def delete(note_id: int):
    if note_id <= 0:
        raise HTTPException(422, detail='Note ID must be a positive integer')
    with db() as conn:
        res = conn.execute('DELETE FROM notes WHERE id=?', (note_id,))
        if not res.rowcount:
            raise HTTPException(404, detail='Note not found')


init_db()
