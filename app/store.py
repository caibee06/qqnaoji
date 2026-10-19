import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY, session TEXT NOT NULL,
                role TEXT NOT NULL, content TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS profiles (
                session TEXT PRIMARY KEY, name TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS messages_session ON messages(session, id);
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', reply TEXT,
                created REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0);
        ''')
        self.db.execute("UPDATE events SET status='pending' WHERE status='processing'")
        self.db.commit()

    def history(self, session, turns):
        rows = self.db.execute('SELECT role, content FROM messages WHERE session=? ORDER BY id DESC LIMIT ?',
                               (session, turns * 2)).fetchall()
        return [{'role': role, 'content': content} for role, content in reversed(rows)]

    def append(self, session, question, answer, turns):
        with self.db:
            self.db.executemany('INSERT INTO messages(session,role,content) VALUES (?,?,?)',
                                [(session, 'user', question), (session, 'assistant', answer)])
            self.db.execute('DELETE FROM messages WHERE session=? AND id NOT IN '
                            '(SELECT id FROM messages WHERE session=? ORDER BY id DESC LIMIT ?)',
                            (session, session, turns * 2))

    def clear(self, session):
        with self.db:
            self.db.execute('DELETE FROM messages WHERE session=?', (session,))

    def profile(self, session):
        row = self.db.execute('SELECT name FROM profiles WHERE session=?', (session,)).fetchone()
        return row[0] if row else 'default'

    def set_profile(self, session, name):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO profiles(session,name) VALUES (?,?)', (session, name))
            self.db.execute('DELETE FROM messages WHERE session=?', (session,))

    def close(self):
        self.db.close()
