"""
用户认证模块 - 简化版JWT（使用hashlib）+ 受邀码验证
"""
import hashlib
import hmac
import base64
import json
import time
import re
from datetime import datetime, timedelta
from typing import Optional
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, validator

SECRET_KEY = "provider-assist-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30

security = HTTPBearer()

class Token(BaseModel):
    access_token: str
    token_type: str

class UserRegister(BaseModel):
    invitation_code: str
    provider_name: str
    username: str
    password: str

    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8 or len(v) > 25:
            raise ValueError('密码长度必须为8-25位')
        # 检查字符类型多样性
        types = 0
        if re.search(r'[0-9]', v): types += 1
        if re.search(r'[a-z]', v): types += 1
        if re.search(r'[A-Z]', v): types += 1
        if re.search(r'[!@#$%^&*()_+\-=\[\]{};:\'",.<>?/\\|`~]', v): types += 1
        if types < 2:
            raise ValueError('密码必须包含至少2种不同字符类型（数字、大小写字母、特殊符号）')
        return v

class UserLogin(BaseModel):
    invitation_code: str
    provider_name: str
    username: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    provider_name: str

def simple_hash(password: str) -> str:
    """简单密码哈希"""
    return hashlib.sha256((password + SECRET_KEY).encode()).hexdigest()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return simple_hash(plain_password) == hashed_password

def get_password_hash(password: str) -> str:
    return simple_hash(password)

def create_token_base64(data: dict) -> str:
    """创建简单的token（不依赖jose库）"""
    payload = data.copy()
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    payload.update({"exp": int(expire.timestamp())})
    token_bytes = json.dumps(payload).encode()
    signature = hmac.new(SECRET_KEY.encode(), token_bytes, hashlib.sha256).digest()
    combined = base64.urlsafe_b64encode(token_bytes).decode() + "." + base64.urlsafe_b64encode(signature).decode()
    return combined

def decode_token(token: str) -> dict:
    """解码token"""
    try:
        parts = token.split(".")
        if len(parts) != 2:
            raise HTTPException(status_code=401, detail="无效的token格式")
        payload_bytes = base64.urlsafe_b64decode(parts[0])
        signature = base64.urlsafe_b64decode(parts[1])
        expected_sig = hmac.new(SECRET_KEY.encode(), payload_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected_sig):
            raise HTTPException(status_code=401, detail="无效的签名")
        payload = json.loads(payload_bytes)
        if payload.get("exp", 0) < int(time.time()):
            raise HTTPException(status_code=401, detail="token已过期")
        return payload
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="无效的认证凭证")

def create_access_token(data: dict) -> str:
    return create_token_base64(data)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    token = credentials.credentials
    payload = decode_token(token)
    return payload

def require_auth(user: dict = Depends(get_current_user)) -> dict:
    if not user or "sub" not in user:
        raise HTTPException(status_code=401, detail="请先登录")
    # 测试账号 devuser 可以跨用户查看所有客户
    if user.get("username") == "devuser":
        user["is_test_user"] = True
    return user

def validate_invitation_code(code: str, provider_name: str = None) -> tuple:
    """校验受邀码
    返回 (is_valid, error_message, provider_name)
    受邀码不校验企业名称（注册页企业名称已预填）
    """
    if not code:
        return False, "受邀码不能为空", None

    from database import get_db
    conn = get_db()
    cursor = conn.cursor()

    # 查找受邀码
    cursor.execute("SELECT id, provider_name, max_users FROM invitation_codes WHERE code = ?", (code,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, "受邀码无效", None

    prov_name = row['provider_name']
    max_users = row['max_users'] or 1

    # 统计该企业已有用户数
    cursor.execute("SELECT COUNT(*) FROM users WHERE provider_name = ?", (prov_name,))
    user_count = cursor.fetchone()[0]
    conn.close()

    if user_count >= max_users:
        return False, f"该企业注册名额已满（{max_users}人）", prov_name

    return True, "", prov_name

def mark_invitation_code_used(code: str, user_id: int):
    """标记受邀码已使用（人数+1）"""
    from database import get_db
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE invitation_codes SET used = used + 1, used_by = ? WHERE code = ?", (user_id, code))
    conn.commit()
    conn.close()
    # 注意：不关闭连接，因为 get_db() 返回全局单例

def seed_invitation_codes():
    """初始化测试用受邀码"""
    from database import get_db
    conn = get_db()
    cursor = conn.cursor()

    test_codes = [
        ("PROV2026001", "测试服务商A"),
        ("PROV2026002", "测试服务商B"),
        ("PROV2026003", "上海数字科技"),
        ("PROV2026004", "深圳智能服务"),
        ("PROV2026005", "北京企业服务"),
    ]

    for code, provider in test_codes:
        cursor.execute("INSERT OR IGNORE INTO invitation_codes (code, provider_name) VALUES (?, ?)", (code, provider))

    conn.commit()
    # 注意：不关闭连接，因为 get_db() 返回全局单例
    print(f"已初始化 {len(test_codes)} 个测试受邀码")

def seed_dev_user():
    """创建固定测试账号，用于 dev 免登录"""
    from database import get_db
    conn = get_db()
    cursor = conn.cursor()
    # 固定测试账号: devuser / DevTest123
    pw_hash = simple_hash("DevTest123")
    cursor.execute("INSERT OR IGNORE INTO users (username, password_hash, provider_name) VALUES (?, ?, ?)",
                   ("devuser", pw_hash, "测试服务商A"))
    conn.commit()
    print("已创建测试账号: devuser / DevTest123")
