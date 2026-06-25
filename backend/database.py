"""
数据库层 - 支持 SQLite（开发）/ PostgreSQL（生产）
使用 SQLAlchemy ORM，换数据库只需改 DATABASE_URL
"""
import os
from pathlib import Path
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, ForeignKey, select
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from contextlib import contextmanager

# 数据库配置
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{Path(__file__).parent.parent / 'data' / 'provider_assist.db'}"
)

# 创建引擎
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, connect_args=connect_args, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ==================== 模型 ====================

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    provider_name = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)

    clients = relationship("Client", back_populates="user")
    knowledge = relationship("ProviderKnowledge", back_populates="user")


class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(255), nullable=False)
    industry = Column(String(255))
    initial_demand = Column(Text)
    status = Column(String(50), default="待完善")
    step1_result = Column(Text)
    step2_report = Column(Text)
    step2_todo = Column(Text)
    step2_schema = Column(Text)
    demo_url = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="clients")


class ProviderKnowledge(Base):
    __tablename__ = "provider_knowledge"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    category = Column(String(50), nullable=False)  # case/template/qa/sales_tool/industry_knowledge
    title = Column(String(255), nullable=False)
    content = Column(Text)
    industry = Column(String(255))
    tags = Column(Text)
    file_path = Column(String(255))
    file_name = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="knowledge")


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    content = Column(Text)
    sections = Column(Text)  # JSON格式存储各区块内容
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class InvitationCode(Base):
    __tablename__ = "invitation_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False)
    provider_name = Column(String(255), nullable=False)
    used = Column(Integer, default=0)
    used_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)


# ==================== 会话管理 ====================

@contextmanager
def get_session():
    """获取数据库会话（自动管理提交/回滚）"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db():
    """初始化数据库表"""
    Base.metadata.create_all(bind=engine)
    print(f"数据库初始化完成: {DATABASE_URL.split('://')[0]}")


# ==================== 兼容层（legacy raw SQL 接口）====================
# 以下函数保持向后兼容，现有代码无需改动

_connection = None

def get_db():
    """获取数据库连接（legacy raw SQL 兼容）"""
    global _connection
    if _connection is None:
        DB_PATH = Path(__file__).parent.parent / "data" / "provider_assist.db"
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        import sqlite3
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _connection = conn
    # 检查连接是否关闭，如果是则重建
    try:
        _connection.execute("SELECT 1")
    except:
        import sqlite3
        DB_PATH = Path(__file__).parent.parent / "data" / "provider_assist.db"
        _connection = sqlite3.connect(DB_PATH, check_same_thread=False)
        _connection.row_factory = sqlite3.Row
    return _connection


def init_db_legacy():
    """Legacy SQLite 初始化（向后兼容）"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            provider_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS provider_knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT,
            industry TEXT,
            tags TEXT,
            file_path TEXT,
            file_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            industry TEXT,
            initial_demand TEXT,
            status TEXT DEFAULT '待完善',
            step1_result TEXT,
            step2_report TEXT,
            step2_todo TEXT,
            step2_schema TEXT,
            demo_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # 补全 clients 表缺失的列（兼容已有数据库）
    for col_def in [
        "step2_report TEXT",
        "step2_todo TEXT",
        "step2_schema TEXT",
        "step3_summary TEXT",
        "transcript TEXT",
        "step4_report TEXT",
        "step4_presales TEXT",
        "step4_technical TEXT",
        "step4_presales_versions TEXT",
        "step4_technical_versions TEXT",
        "step5_schema TEXT",
        "step5_agent_suggestions TEXT",
        "step4_input_draft TEXT",
        "_wecom_docid TEXT",
        "_wecom_url TEXT",
        "_step1_wecom_docid TEXT",
        "_step1_wecom_url TEXT",
        "_notes_wecom_docid TEXT",
        "_notes_wecom_url TEXT",
        "is_completed INTEGER DEFAULT 0",
        "is_saved INTEGER DEFAULT 0",
        "company_type TEXT",
        "main_customers TEXT",
        "possible_focus TEXT",
        "company_intro TEXT",
        "tags TEXT",
        "scale TEXT",
        "uploaded_files TEXT",
    ]:
        col_name = col_def.split()[0]
        try:
            cursor.execute(f"ALTER TABLE clients ADD COLUMN {col_def}")
            conn.commit()
        except Exception:
            pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            content TEXT,
            sections TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (client_id) REFERENCES clients(id)
        )
    """)

    # 受邀码表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invitation_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            provider_name TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            used_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (used_by) REFERENCES users(id)
        )
    """)

    conn.commit()
    print(f"数据库初始化完成（Legacy SQLite）")


# ==================== 知识库文件管理 ====================

def init_kb_db():
    """初始化知识库文件表"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kb_files (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            original_filename TEXT NOT NULL,
            display_name TEXT NOT NULL,
            category TEXT NOT NULL,
            industry TEXT DEFAULT '',
            filepath TEXT NOT NULL,
            status TEXT DEFAULT 'uploading',
            progress INTEGER DEFAULT 0,
            char_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kb_enhancement_cache (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            default_answer TEXT NOT NULL,
            enhanced_answer TEXT NOT NULL,
            source_file_ids TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_kb_files_user_id ON kb_files(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_kb_files_category ON kb_files(category)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_kb_cache_user ON kb_enhancement_cache(user_id)")

    conn.commit()
    print("知识库文件表初始化完成")


# 为保持向后兼容，默认使用 legacy 初始化
if __name__ == "__main__":
    init_db()
    init_kb_db()