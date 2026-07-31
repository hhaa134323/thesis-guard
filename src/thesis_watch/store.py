"""SQLite 持久化（v0.1）。

「后端从简、单数据库」：stdlib sqlite3，无 ORM。
- 预置 5 人 beta 账号（不做注册系统）；email 由作者填。
- thesis 卡以 JSON 存（to_dict/from_dict），便于 schema 演进。
- check_results 记录每次核对，triggered 收尾动作沉淀为 eval 标注来源。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import CheckResult, ThesisCard, from_dict, to_dict

# 5 人 beta 预置账号（email 留空，由作者填；触达前必须补）
PRESET_USERS: list[dict[str, str]] = [
    {"user_id": "beta1", "email": "", "display_name": "Beta One"},
    {"user_id": "beta2", "email": "", "display_name": "Beta Two"},
    {"user_id": "beta3", "email": "", "display_name": "Beta Three"},
    {"user_id": "beta4", "email": "", "display_name": "Beta Four"},
    {"user_id": "beta5", "email": "", "display_name": "Beta Five"},
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  user_id      TEXT PRIMARY KEY,
  email        TEXT NOT NULL DEFAULT '',
  display_name TEXT NOT NULL DEFAULT '',
  created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS thesis_cards (
  card_id     TEXT PRIMARY KEY,
  user_id     TEXT NOT NULL,
  ticker      TEXT NOT NULL,
  filer_type  TEXT NOT NULL,
  card_json   TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(user_id)
);
CREATE INDEX IF NOT EXISTS idx_cards_user ON thesis_cards(user_id);

CREATE TABLE IF NOT EXISTS check_results (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id     TEXT NOT NULL,
  cond_id     TEXT NOT NULL,
  status      TEXT NOT NULL,
  result_json TEXT NOT NULL,
  checked_at  TEXT NOT NULL,
  FOREIGN KEY(card_id) REFERENCES thesis_cards(card_id)
);
CREATE INDEX IF NOT EXISTS idx_results_card ON check_results(card_id);
"""


class ThesisStore:
    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # --- users ---
    def seed_preset_users(self) -> int:
        n = 0
        for u in PRESET_USERS:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO users(user_id, email, display_name) VALUES (?,?,?)",
                (u["user_id"], u["email"], u["display_name"]),
            )
            n += cur.rowcount
        self.conn.commit()
        return n

    def set_user_email(self, user_id: str, email: str) -> None:
        self.conn.execute(
            "UPDATE users SET email=? WHERE user_id=?", (email, user_id)
        )
        self.conn.commit()

    def get_user(self, user_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM users WHERE user_id=?", (user_id,)
        ).fetchone()

    # --- cards ---
    def upsert_card(self, card: ThesisCard) -> None:
        d = to_dict(card)
        self.conn.execute(
            """INSERT INTO thesis_cards(card_id, user_id, ticker, filer_type, card_json, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(card_id) DO UPDATE SET
                 user_id=excluded.user_id, ticker=excluded.ticker,
                 filer_type=excluded.filer_type, card_json=excluded.card_json,
                 updated_at=excluded.updated_at""",
            (card.card_id, card.user_id, card.ticker, card.filer_type,
             json.dumps(d, ensure_ascii=False), card.created_at, card.updated_at),
        )
        self.conn.commit()

    def get_card(self, card_id: str) -> ThesisCard | None:
        row = self.conn.execute(
            "SELECT card_json FROM thesis_cards WHERE card_id=?", (card_id,)
        ).fetchone()
        if not row:
            return None
        return from_dict(ThesisCard, json.loads(row["card_json"]))

    def list_cards(self, user_id: str) -> list[ThesisCard]:
        rows = self.conn.execute(
            "SELECT card_json FROM thesis_cards WHERE user_id=? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
        return [from_dict(ThesisCard, json.loads(r["card_json"])) for r in rows]

    # --- check results ---
    def save_check_result(self, r: CheckResult) -> None:
        self.conn.execute(
            """INSERT INTO check_results(card_id, cond_id, status, result_json, checked_at)
               VALUES (?,?,?,?,?)""",
            (r.card_id, r.cond_id, r.status.value,
             json.dumps(to_dict(r), ensure_ascii=False), r.checked_at),
        )
        self.conn.commit()

    def list_check_results(self, card_id: str) -> list[CheckResult]:
        rows = self.conn.execute(
            "SELECT result_json FROM check_results WHERE card_id=? ORDER BY checked_at DESC",
            (card_id,),
        ).fetchall()
        return [from_dict(CheckResult, json.loads(r["result_json"])) for r in rows]

    def close(self) -> None:
        self.conn.close()
