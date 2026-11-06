"""
数据库服务模块 — B端旅行社/研学机构智能行程方案系统

功能:
  1. 用户管理（顾问+管理员双角色）
  2. 客户管理（CRUD）
  3. 行程需求管理（CRUD）
  4. 行程方案管理（CRUD+版本管理）
  5. 方案版本历史管理

表结构:
  users                → 用户表（含 role 字段：consultant/admin）
  clients              → 客户表
  travel_requirements  → 行程需求表
  itineraries          → 行程方案表
  itinerary_versions   → 方案版本历史表

依赖:
  bcrypt==4.1.2+    — 密码哈希
  Python 内置       — sqlite3, json, datetime
"""
import json
import logging
import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.config import DB_PATH, ADMIN_USERNAME, ADMIN_PASSWORD

logger = logging.getLogger("travel_assistant.db")

# ── 会话 Token 有效期（12小时） ──
AUTH_TOKEN_EXPIRE_HOURS = 12


def _connect() -> sqlite3.Connection:
    """
    统一的 SQLite 连接入口。

    - WAL 模式：读写并发互不阻塞（多顾问同时保存不会锁库）
    - busy_timeout：写锁冲突时等待而不是立刻抛 database is locked
    - foreign_keys：SQLite 默认关闭外键约束，这里显式打开
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        # WAL 是持久化属性，重复设置是幂等的；放在最后避免与建库锁竞争
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        # 只读文件系统等场景不影响主流程
        pass
    return conn



# =====================================================================
# 数据库初始化
# =====================================================================

def init_db() -> None:
    """
    初始化数据库所有表结构 + 自动迁移。
    首次启动自动创建，多次调用安全（IF NOT EXISTS）。
    """
    conn = _connect()
    c = conn.cursor()

    # ── 用户表（含角色标记） ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT UNIQUE NOT NULL,
            password_hash   TEXT NOT NULL,
            email           TEXT DEFAULT '',
            phone           TEXT DEFAULT '',
            role            TEXT DEFAULT 'consultant',  -- 'consultant' | 'admin'
            is_admin        INTEGER DEFAULT 0,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 迁移：为旧版 users 表补充 role 列
    _migrate_add_column(c, "users", "role", "TEXT DEFAULT 'consultant'")
    _migrate_add_column(c, "users", "phone", "TEXT DEFAULT ''")
    _migrate_add_column(c, "users", "is_admin", "INTEGER DEFAULT 0")

    # ── 客户表 ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            phone           TEXT DEFAULT '',
            email           TEXT DEFAULT '',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── 行程需求表 ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS travel_requirements (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id           INTEGER NOT NULL,
            consultant_id       INTEGER NOT NULL,
            destination         TEXT NOT NULL,
            travel_days         INTEGER NOT NULL,
            traveler_count      INTEGER NOT NULL,
            total_budget        REAL,
            travel_type         TEXT NOT NULL,       -- 亲子/研学/团建/情侣/毕业旅行
            preferences         TEXT DEFAULT '',      -- 自然风光/历史人文/美食/休闲/打卡
            special_requirements TEXT DEFAULT '',
            status              TEXT DEFAULT 'active',  -- active/archived
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (client_id) REFERENCES clients(id),
            FOREIGN KEY (consultant_id) REFERENCES users(id)
        )
    """)

    # ── 行程方案表 ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS itineraries (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            requirement_id  INTEGER NOT NULL,
            consultant_id   INTEGER NOT NULL,
            version         INTEGER DEFAULT 1,
            title           TEXT DEFAULT '',
            content_json    TEXT NOT NULL,            -- 结构化 JSON 内容
            status          TEXT DEFAULT 'draft',     -- draft/sent/confirmed/cancelled
            summary         TEXT DEFAULT '',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (requirement_id) REFERENCES travel_requirements(id),
            FOREIGN KEY (consultant_id) REFERENCES users(id)
        )
    """)

    # ── 方案版本历史表 ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS itinerary_versions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            itinerary_id    INTEGER NOT NULL,
            version         INTEGER NOT NULL,
            content_json    TEXT NOT NULL,
            change_log      TEXT DEFAULT '',
            created_by      INTEGER NOT NULL,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (itinerary_id) REFERENCES itineraries(id),
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    """)

    # 索引
    c.execute("CREATE INDEX IF NOT EXISTS idx_clients_name ON clients(name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_requirements_consultant ON travel_requirements(consultant_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_requirements_client ON travel_requirements(client_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_itineraries_requirement ON itineraries(requirement_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_itinerary_versions_itinerary ON itinerary_versions(itinerary_id)")

    # ── 认证 Token 表 ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS auth_tokens (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            token           TEXT UNIQUE NOT NULL,
            expires_at      TIMESTAMP NOT NULL,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_token ON auth_tokens(token)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_user ON auth_tokens(user_id)")

    # ── 操作审计表（B 端追责/排障用） ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER,                     -- 未登录/登录失败时为空
            username        TEXT DEFAULT '',              -- 冗余存储，用户删除后仍可追溯
            action          TEXT NOT NULL,               -- login/generate/modify/export/...
            target_type     TEXT DEFAULT '',              -- itinerary/user/knowledge_base
            target_id       INTEGER,
            detail          TEXT DEFAULT '',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id)")

    conn.commit()
    conn.close()


def _migrate_add_column(cursor, table: str, column: str, definition: str) -> None:
    """安全地向已存在的表添加缺失的列。"""
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    except Exception:
        pass  # 列已存在


# =====================================================================
# 管理员初始化
# =====================================================================

def init_admin() -> None:
    """从 .env 配置创建管理员账号。"""
    if not ADMIN_USERNAME or not ADMIN_PASSWORD:
        logger.warning(
            "未配置 ADMIN_PASSWORD，跳过管理员初始化。"
            "请在 .env 中设置强密码后重启（首次部署必需）。"
        )
        return
    if len(ADMIN_PASSWORD) < 8:
        logger.warning("ADMIN_PASSWORD 长度小于 8 位，建议更换为强密码。")

    import bcrypt
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT id FROM users WHERE username = ? AND (is_admin = 1 OR role = 'admin')",
            (ADMIN_USERNAME,),
        )
        if c.fetchone() is not None:
            return

        password_hash = bcrypt.hashpw(ADMIN_PASSWORD.encode("utf-8"), bcrypt.gensalt())
        c.execute(
            "INSERT INTO users (username, password_hash, email, role, is_admin) VALUES (?, ?, ?, 'admin', 1)",
            (ADMIN_USERNAME, password_hash.decode("utf-8"), "admin@local"),
        )
        conn.commit()
    except Exception as e:
        logger.error(f"管理员初始化失败: {e}")
    finally:
        conn.close()


# =====================================================================
# 用户管理
# =====================================================================

def register_user(username: str, password: str, email: str = "",
                  phone: str = "", role: str = "consultant") -> bool:
    """注册新用户（默认角色为顾问）。"""
    import bcrypt
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    conn = _connect()
    try:
        c = conn.cursor()
        is_admin = 1 if role == "admin" else 0
        c.execute(
            "INSERT INTO users (username, password_hash, email, phone, role, is_admin) VALUES (?, ?, ?, ?, ?, ?)",
            (username, password_hash.decode("utf-8"), email, phone, role, is_admin),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def verify_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """验证用户登录。"""
    import bcrypt
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT id, password_hash, role, is_admin FROM users WHERE username = ?",
            (username,),
        )
        row = c.fetchone()
        if row is None:
            return None
        user_id, password_hash, role, is_admin = row
        if bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8")):
            return {
                "user_id": user_id,
                "username": username,
                "role": role,
                "is_admin": bool(is_admin),
            }
        return None
    finally:
        conn.close()


def user_exists(username: str) -> bool:
    """检查用户名是否已被注册。"""
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute("SELECT 1 FROM users WHERE username = ?", (username,))
        return c.fetchone() is not None
    finally:
        conn.close()


# ── 会话管理 ──


def _now_utc_str() -> str:
    """SQLite 可直接比较的 UTC 时间字符串（与 datetime('now') 格式一致）。"""
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def purge_expired_tokens() -> None:
    """清理过期 Token，避免表无限增长。"""
    conn = _connect()
    try:
        conn.execute("DELETE FROM auth_tokens WHERE expires_at <= datetime('now')")
        conn.commit()
    finally:
        conn.close()


def create_auth_token(user_id: int) -> str:
    """
    创建登录认证 Token。

    同一用户重新登录时会吊销旧 Token（单会话），并顺带清理过期记录，
    避免长期累积大量有效 Token。
    """
    token = secrets.token_urlsafe(32)
    expires = (datetime.utcnow() + timedelta(hours=AUTH_TOKEN_EXPIRE_HOURS)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    conn = _connect()
    try:
        conn.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM auth_tokens WHERE expires_at <= datetime('now')")
        conn.execute(
            "INSERT INTO auth_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
            (user_id, token, expires),
        )
        conn.commit()
        return token
    finally:
        conn.close()


def verify_auth_token(token: str) -> Optional[Dict[str, Any]]:
    """验证 Token，返回用户信息或 None。"""
    if not token:
        return None
    conn = _connect()
    try:
        cursor = conn.execute("""
            SELECT u.id, u.username, u.role, u.is_admin
            FROM auth_tokens t
            JOIN users u ON u.id = t.user_id
            WHERE t.token = ? AND t.expires_at > datetime('now')
        """, (token,))
        row = cursor.fetchone()
        if row:
            return {
                "user_id": row[0],
                "username": row[1],
                "role": row[2],
                "is_admin": bool(row[3]),
            }
        return None
    finally:
        conn.close()


def delete_auth_token(token: str) -> None:
    """删除 Token（登出时调用）。"""
    conn = _connect()
    try:
        conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()


def revoke_user_tokens(user_id: int) -> None:
    """吊销某用户全部 Token（改密、禁用账号时调用）。"""
    conn = _connect()
    try:
        conn.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


# =====================================================================
# 操作审计
# =====================================================================

def log_action(
    user_id: Optional[int],
    action: str,
    target_type: str = "",
    target_id: Optional[int] = None,
    detail: str = "",
    username: str = "",
) -> None:
    """
    写入一条操作日志。

    审计写入失败绝不阻断业务：只记录 warning，不向调用方抛异常。
    """
    try:
        conn = _connect()
        try:
            conn.execute(
                """INSERT INTO audit_logs
                   (user_id, username, action, target_type, target_id, detail)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, username or "", action, target_type or "", target_id, detail or ""),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"审计日志写入失败（已忽略，不影响业务）: {e}")


def list_audit_logs(
    limit: int = 200,
    action: Optional[str] = None,
    user_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """按时间倒序查询操作日志，可按动作/用户筛选。"""
    conn = _connect()
    conn.row_factory = sqlite3.Row
    try:
        conditions = []
        params: List[Any] = []
        if action:
            conditions.append("action = ?")
            params.append(action)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(max(1, min(int(limit), 1000)))

        rows = conn.execute(
            f"""SELECT id, user_id, username, action, target_type,
                       target_id, detail, created_at
                FROM audit_logs {where}
                ORDER BY id DESC LIMIT ?""",
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_all_users() -> List[Dict[str, Any]]:
    """列出所有用户（管理员用）。"""
    conn = _connect()
    conn.row_factory = sqlite3.Row
    try:
        c = conn.cursor()
        c.execute(
            "SELECT id, username, email, phone, role, is_admin, created_at "
            "FROM users ORDER BY created_at DESC"
        )
        rows = c.fetchall()
        return [
            {
                "id": row["id"],
                "username": row["username"],
                "email": row["email"],
                "phone": row["phone"],
                "role": row["role"],
                "is_admin": bool(row["is_admin"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def update_password(username: str, new_password: str) -> bool:
    """重置用户密码。"""
    import bcrypt
    password_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt())
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (password_hash.decode("utf-8"), username),
        )
        if c.rowcount == 0:
            return False
        # 改密后吊销该用户全部会话
        c.execute(
            "DELETE FROM auth_tokens WHERE user_id = (SELECT id FROM users WHERE username = ?)",
            (username,),
        )
        conn.commit()
        return True
    finally:
        conn.close()


# =====================================================================
# 客户管理 (Clients)
# =====================================================================

def create_client(name: str, phone: str = "", email: str = "") -> int:
    """创建客户，返回 client_id。"""
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO clients (name, phone, email) VALUES (?, ?, ?)",
            (name, phone, email),
        )
        conn.commit()
        return c.lastrowid
    finally:
        conn.close()


def get_client(client_id: int) -> Optional[Dict[str, Any]]:
    """获取客户信息。"""
    conn = _connect()
    conn.row_factory = sqlite3.Row
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM clients WHERE id = ?", (client_id,))
        row = c.fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        conn.close()


def list_clients(search: str = "") -> List[Dict[str, Any]]:
    """列出客户，支持按名称搜索。"""
    conn = _connect()
    conn.row_factory = sqlite3.Row
    try:
        c = conn.cursor()
        if search:
            c.execute(
                "SELECT * FROM clients WHERE name LIKE ? ORDER BY updated_at DESC",
                (f"%{search}%",),
            )
        else:
            c.execute("SELECT * FROM clients ORDER BY updated_at DESC")
        return [dict(row) for row in c.fetchall()]
    finally:
        conn.close()


# =====================================================================
# 行程需求管理 (Travel Requirements)
# =====================================================================

def create_requirement(
    client_id: int,
    consultant_id: int,
    destination: str,
    travel_days: int,
    traveler_count: int,
    total_budget: Optional[float] = None,
    travel_type: str = "亲子",
    preferences: str = "",
    special_requirements: str = "",
) -> int:
    """创建行程需求，返回 requirement_id。"""
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            """INSERT INTO travel_requirements
               (client_id, consultant_id, destination, travel_days,
                traveler_count, total_budget, travel_type,
                preferences, special_requirements)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (client_id, consultant_id, destination, travel_days,
             traveler_count, total_budget, travel_type,
             preferences, special_requirements),
        )
        conn.commit()
        return c.lastrowid
    finally:
        conn.close()


def get_requirement(requirement_id: int) -> Optional[Dict[str, Any]]:
    """获取行程需求（联表查询客户名称）。"""
    conn = _connect()
    conn.row_factory = sqlite3.Row
    try:
        c = conn.cursor()
        c.execute("""
            SELECT r.*, c.name as client_name
            FROM travel_requirements r
            LEFT JOIN clients c ON c.id = r.client_id
            WHERE r.id = ?
        """, (requirement_id,))
        row = c.fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        conn.close()


def list_requirements(consultant_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """列出需求，可按顾问筛选。"""
    conn = _connect()
    conn.row_factory = sqlite3.Row
    try:
        c = conn.cursor()
        if consultant_id:
            c.execute("""
                SELECT r.*, c.name as client_name
                FROM travel_requirements r
                LEFT JOIN clients c ON c.id = r.client_id
                WHERE r.consultant_id = ? AND r.status = 'active'
                ORDER BY r.created_at DESC
            """, (consultant_id,))
        else:
            c.execute("""
                SELECT r.*, c.name as client_name
                FROM travel_requirements r
                LEFT JOIN clients c ON c.id = r.client_id
                WHERE r.status = 'active'
                ORDER BY r.created_at DESC
            """)
        return [dict(row) for row in c.fetchall()]
    finally:
        conn.close()


# =====================================================================
# 行程方案管理 (Itineraries)
# =====================================================================

def create_itinerary(
    requirement_id: int,
    consultant_id: int,
    content_json: str,
    title: str = "",
    summary: str = "",
) -> int:
    """创建行程方案，返回 itinerary_id。"""
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            """INSERT INTO itineraries
               (requirement_id, consultant_id, content_json, title, summary)
               VALUES (?, ?, ?, ?, ?)""",
            (requirement_id, consultant_id, content_json, title, summary),
        )
        itinerary_id = c.lastrowid

        # 同时创建初始版本记录
        c.execute(
            """INSERT INTO itinerary_versions
               (itinerary_id, version, content_json, change_log, created_by)
               VALUES (?, 1, ?, '初始版本', ?)""",
            (itinerary_id, content_json, consultant_id),
        )
        conn.commit()
        return itinerary_id
    finally:
        conn.close()


def get_itinerary(itinerary_id: int) -> Optional[Dict[str, Any]]:
    """获取行程方案（联表查询需求+客户信息）。"""
    conn = _connect()
    conn.row_factory = sqlite3.Row
    try:
        c = conn.cursor()
        c.execute("""
            SELECT i.*, r.destination, r.travel_days, r.traveler_count,
                   r.total_budget, r.travel_type, r.preferences,
                   r.special_requirements, c.name as client_name
            FROM itineraries i
            LEFT JOIN travel_requirements r ON r.id = i.requirement_id
            LEFT JOIN clients c ON c.id = r.client_id
            WHERE i.id = ?
        """, (itinerary_id,))
        row = c.fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        conn.close()


def can_access_itinerary(itinerary: Dict[str, Any], user_id: int, is_admin: bool) -> bool:
    """
    判断用户是否有权访问某个方案。

    管理员可访问全部；顾问只能访问自己创建的方案。
    用于详情/修改/导出前的归属校验，避免仅凭 ID 越权。
    """
    if is_admin:
        return True
    try:
        return int(itinerary.get("consultant_id") or 0) == int(user_id)
    except (TypeError, ValueError):
        return False


def list_itineraries(
    consultant_id: Optional[int] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """列出方案，可按顾问和状态筛选。"""
    conn = _connect()
    conn.row_factory = sqlite3.Row
    try:
        c = conn.cursor()
        conditions = []
        params = []
        if consultant_id:
            conditions.append("i.consultant_id = ?")
            params.append(consultant_id)
        if status:
            conditions.append("i.status = ?")
            params.append(status)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        c.execute(f"""
            SELECT i.id, i.title, i.version, i.status, i.summary,
                   i.created_at, i.updated_at,
                   r.destination, c.name as client_name
            FROM itineraries i
            LEFT JOIN travel_requirements r ON r.id = i.requirement_id
            LEFT JOIN clients c ON c.id = r.client_id
            {where}
            ORDER BY i.updated_at DESC
        """, params)
        return [dict(row) for row in c.fetchall()]
    finally:
        conn.close()


def update_itinerary(
    itinerary_id: int,
    content_json: str,
    title: str = "",
    summary: str = "",
    change_log: str = "",
    consultant_id: int = 0,
) -> bool:
    """更新方案内容（自动递增版本号，并创建版本历史）。"""
    conn = _connect()
    try:
        c = conn.cursor()
        # 获取当前版本号与方案归属（用于版本记录的 created_by）
        c.execute("SELECT version, consultant_id FROM itineraries WHERE id = ?", (itinerary_id,))
        row = c.fetchone()
        if row is None:
            return False
        new_version = row[0] + 1
        created_by = consultant_id or row[1]  # 未传操作人时回落到方案归属人，避免外键失败

        # 更新主表
        c.execute(
            """UPDATE itineraries SET
               content_json = ?, title = ?, summary = ?,
               version = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (content_json, title, summary, new_version, itinerary_id),
        )

        # 创建版本历史
        c.execute(
            """INSERT INTO itinerary_versions
               (itinerary_id, version, content_json, change_log, created_by)
               VALUES (?, ?, ?, ?, ?)""",
            (itinerary_id, new_version, content_json, change_log, created_by),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def update_itinerary_status(itinerary_id: int, status: str) -> bool:
    """更新方案状态：draft/sent/confirmed/cancelled。"""
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE itineraries SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, itinerary_id),
        )
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


def delete_itinerary(itinerary_id: int) -> bool:
    """删除方案及其所有版本历史。"""
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM itinerary_versions WHERE itinerary_id = ?", (itinerary_id,))
        c.execute("DELETE FROM itineraries WHERE id = ?", (itinerary_id,))
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


# =====================================================================
# 方案版本历史管理
# =====================================================================

def get_version_history(itinerary_id: int) -> List[Dict[str, Any]]:
    """获取方案的所有版本历史。"""
    conn = _connect()
    conn.row_factory = sqlite3.Row
    try:
        c = conn.cursor()
        c.execute("""
            SELECT v.*, u.username as created_by_name
            FROM itinerary_versions v
            LEFT JOIN users u ON u.id = v.created_by
            WHERE v.itinerary_id = ?
            ORDER BY v.version DESC
        """, (itinerary_id,))
        return [dict(row) for row in c.fetchall()]
    finally:
        conn.close()


def get_version(itinerary_id: int, version: int) -> Optional[Dict[str, Any]]:
    """获取指定版本的方案内容。"""
    conn = _connect()
    conn.row_factory = sqlite3.Row
    try:
        c = conn.cursor()
        c.execute(
            "SELECT * FROM itinerary_versions WHERE itinerary_id = ? AND version = ?",
            (itinerary_id, version),
        )
        row = c.fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        conn.close()
