import sqlite3
import os
import hashlib
import secrets
from typing import Optional, Dict, Any
from app.core.config import resolve_path

class AuthService:
    """
    负责用户注册、登录和 Token 验证，使用 SQLite 作为存储。
    """
    def __init__(self):
        self.db_path = resolve_path("data/processed/users.db")
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Users table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """)
            
            # Sessions table for token management
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """)
            
            conn.commit()
            
            # Check if admin user exists
            cursor.execute("SELECT id FROM users WHERE username = 'admin'")
            if not cursor.fetchone():
                admin_hash = self._hash_password("admin123")
                cursor.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                    ("admin", admin_hash, "admin")
                )
                conn.commit()
                print("[AuthService] Default admin user created (admin / admin123)")
                
            conn.close()
        except Exception as e:
            print(f"[AuthService] Database initialization failed: {e}")

    def _hash_password(self, password: str) -> str:
        """简单的 SHA256 密码哈希（可加盐，为保持简单这里直接 hash）"""
        return hashlib.sha256(password.encode('utf-8')).hexdigest()

    def register(self, username: str, password: str) -> bool:
        """注册新用户"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            if cursor.fetchone():
                conn.close()
                return False # Username exists
                
            cursor.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, self._hash_password(password), "user")
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[AuthService] Register error: {e}")
            return False

    def login(self, username: str, password: str) -> Optional[str]:
        """登录并返回 Token"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, password_hash FROM users WHERE username = ?", 
                (username,)
            )
            user = cursor.fetchone()
            
            if user and user[1] == self._hash_password(password):
                user_id = user[0]
                token = secrets.token_hex(32)
                cursor.execute(
                    "INSERT INTO sessions (token, user_id) VALUES (?, ?)",
                    (token, user_id)
                )
                conn.commit()
                conn.close()
                return token
                
            conn.close()
            return None
        except Exception as e:
            print(f"[AuthService] Login error: {e}")
            return None

    def get_user_by_token(self, token: str) -> Optional[Dict[str, Any]]:
        """根据 Token 获取用户信息"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT u.id, u.username, u.role 
                FROM sessions s
                JOIN users u ON s.user_id = u.id
                WHERE s.token = ?
            """, (token,))
            user = cursor.fetchone()
            conn.close()
            
            if user:
                return dict(user)
            return None
        except Exception as e:
            print(f"[AuthService] Verify token error: {e}")
            return None
            
    def logout(self, token: str):
        """注销 Token"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[AuthService] Logout error: {e}")

auth_service = AuthService()
