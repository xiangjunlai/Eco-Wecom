"""
Provider Assist 后端API - FastAPI
轻量化版本：SQLite + JWT认证 + 知识库管理
"""
import os
import json
import re
from pathlib import Path
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from database import get_db, init_db, init_kb_db
from auth import (
    get_password_hash, verify_password, create_access_token,
    UserRegister, UserLogin, UserResponse, require_auth,
    validate_invitation_code, mark_invitation_code_used, seed_invitation_codes, seed_dev_user
)

BASE_DIR = Path(__file__).parent.parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
KB_DIR = BASE_DIR / "data" / "kb"
KB_DIR.mkdir(parents=True, exist_ok=True)

# 企微 CLI 已配置（通过 wecom-cli init 初始化）
DEEPSEEK_API_KEY = "sk-cp-FxfZUSUHnTWn7eCtl1V-5CI1jFpfF3XLI0jxHZJ7U0p16_cea_FTQqxOaOYavdfwiS9DDN4pomf4CxLZlQYqIyvJJK_eaKR7tbh4d77_1dGK8DwQtwwjLDc"

# ==================== 通用辅助函数 ====================

def call_mcp(tool_name: str, arguments: dict) -> dict:
    """调用企微 CLI API"""
    import subprocess, json
    args_str = json.dumps(arguments, ensure_ascii=False)
    cmd = ["wecom-cli", "doc", tool_name, args_str]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return {"error": result.stderr or "CLI error"}
        output = result.stdout.strip()
        # CLI returns JSON-RPC format
        try:
            resp = json.loads(output)
            if resp.get("isError"):
                return {"error": resp.get("id", "")}
            content = resp.get("result", {}).get("content", [])
            if content and isinstance(content, list):
                text = content[0].get("text", "{}")
                return json.loads(text)
            return resp.get("result", {})
        except json.JSONDecodeError:
            return {"error": output}
    except Exception as e:
        return {"error": str(e)}


def extract_mcp(mcp_resp: dict):
    """从 MCP 响应中提取实际数据"""
    if not mcp_resp:
        return None
    result = mcp_resp.get("result", mcp_resp)
    if isinstance(result, dict):
        content = result.get("content", [])
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    try:
                        return json.loads(item["text"])
                    except:
                        return item.get("text")
        return result
    return result


DEEPSEEK_API_KEY = "sk-cp-FxfZUSUHnTWn7eCtl1V-5CI1jFpfF3XLI0jxHZJ7U0p16_cea_FTQqxOaOYavdfwiS9DDN4pomf4CxLZlQYqIyvJJK_eaKR7tbh4d77_1dGK8DwQtwwjLDc"

def call_deepseek(system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> str:
    """调用 MiniMax API"""
    import httpx
    try:
        response = httpx.post(
            "https://api.minimax.chat/v1/text/chatcompletion_v2",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
            },
            json={
                "model": "abab6.5s-chat",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "max_tokens": max_tokens,
                "temperature": 0.7
            },
            timeout=60.0
        )
        result = response.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Error: {str(e)}"


app = FastAPI(title="Provider Assist API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化数据库
init_db()
init_kb_db()

# 挂载 public 静态文件目录（用于 Agent Demo H5）
public_dir = Path(__file__).parent / "public"
public_dir.mkdir(exist_ok=True)
app.mount("/public", StaticFiles(directory=str(public_dir)), name="public")

# 初始化测试用受邀码
seed_invitation_codes()
seed_dev_user()

# ==================== 认证相关 ====================

@app.post("/api/auth/register")
async def register(user: dict):
    """用户注册 - 需要有效的受邀码"""
    import re

    provider_name = user.get("provider_name", "").strip()
    invitation_code = user.get("invitation_code", "").strip()
    username = user.get("username", "").strip()
    password = user.get("password", "")

    # 字段校验
    if not provider_name: raise HTTPException(status_code=400, detail="服务商名称不能为空")
    if not invitation_code: raise HTTPException(status_code=400, detail="受邀码不能为空")
    if not username: raise HTTPException(status_code=400, detail="用户名不能为空")
    if not password: raise HTTPException(status_code=400, detail="密码不能为空")

    # 密码格式校验
    if len(password) < 8 or len(password) > 25:
        raise HTTPException(status_code=400, detail="密码长度必须为8-25位")
    types = sum([
        bool(re.search(r'[0-9]', password)),
        bool(re.search(r'[a-z]', password)),
        bool(re.search(r'[A-Z]', password)),
        bool(re.search(r'[!@#$%^&*()_+\-=\[\]{};:\'",.<>?/\\|`~]', password))
    ])
    if types < 2:
        raise HTTPException(status_code=400, detail="密码必须包含至少2种不同字符类型")

    # 校验受邀码
    is_valid, error_msg = validate_invitation_code(invitation_code, provider_name)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    conn = get_db()
    cursor = conn.cursor()

    # 检查是否已存在
    cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
    if cursor.fetchone():
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 创建用户
    password_hash = get_password_hash(password)
    cursor.execute(
        "INSERT INTO users (username, password_hash, provider_name) VALUES (?, ?, ?)",
        (username, password_hash, provider_name)
    )
    conn.commit()

    user_id = cursor.lastrowid

    # 标记受邀码已使用
    mark_invitation_code_used(invitation_code, user_id)

    conn.close()

    # 生成token
    token = create_access_token({"sub": username, "user_id": user_id})

    return {
        "success": True,
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user_id, "username": username, "provider_name": provider_name}
    }

@app.post("/api/auth/login", response_model=dict)
async def login(user: UserLogin):
    """用户登录 - 已注册用户直接登录"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, username, password_hash, provider_name FROM users WHERE username = ?", (user.username,))
    row = cursor.fetchone()
    conn.close()

    if not row or not verify_password(user.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 再次确认服务商名称匹配
    if row["provider_name"] != user.provider_name:
        raise HTTPException(status_code=401, detail="服务商名称与受邀码不匹配")

    token = create_access_token({"sub": row["username"], "user_id": row["id"]})

    return {
        "success": True,
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": row["id"], "username": row["username"], "provider_name": row["provider_name"] or ""}
    }

@app.post("/api/test-login")
async def test_login():
    """极简测试登录 - 一键登录测试账号"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, provider_name FROM users WHERE username = 'devuser'")
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {"error": "测试用户不存在"}

    token = create_access_token({"sub": row["username"], "user_id": row["id"]})
    return {
        "success": True,
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": row["id"], "username": row["username"], "provider_name": row["provider_name"]}
    }


@app.post("/api/auth/dev-login", response_model=dict)
async def dev_login(user: dict):
    """开发者登录 - 不校验受邀码，直接登录已注册用户"""
    username = user.get("username")
    password = user.get("password")
    if not username or not password:
        raise HTTPException(status_code=400, detail="缺少用户名或密码")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, password_hash, provider_name FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()

    if not row or not verify_password(password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_access_token({"sub": row["username"], "user_id": row["id"]})
    return {
        "success": True,
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": row["id"], "username": row["username"], "provider_name": row["provider_name"] or ""}
    }

@app.post("/api/auth/auto-login")
async def auto_login(body: dict, user: dict = Depends(require_auth)):
    """自动登录 - 检查token是否有效"""
    return {
        "success": True,
        "user": {"id": user["user_id"], "username": user["sub"]}
    }

@app.get("/api/auth/me")
async def get_me(user: dict = Depends(require_auth)):
    """获取当前用户信息"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, provider_name FROM users WHERE id = ?", (user["user_id"],))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")

    return {"id": row["id"], "username": row["username"], "provider_name": row["provider_name"] or ""}

# ==================== 知识库 ====================

def load_global_knowledge():
    """加载全局知识库"""
    industries = {}
    ind_dir = KNOWLEDGE_DIR / "industries"
    if ind_dir.exists():
        for f in ind_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                industries[f.stem] = data
            except:
                pass

    cases = []
    cases_dir = KNOWLEDGE_DIR / "cases"
    if cases_dir.exists():
        for f in cases_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                cases.append(data)
            except:
                pass

    templates = []
    tpl_dir = KNOWLEDGE_DIR / "field_templates"
    if tpl_dir.exists():
        for f in tpl_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                templates.append(data)
            except:
                pass

    return {"industries": industries, "cases": cases, "templates": templates}

@app.get("/api/knowledge/global")
async def get_global_knowledge():
    """获取全局知识库摘要"""
    kb = load_global_knowledge()
    return {
        "industries_count": len(kb["industries"]),
        "cases_count": len(kb["cases"]),
        "templates_count": len(kb["templates"]),
        "industries": [
            {"key": k, "name": v.get("industry_name", k), "tags": v.get("tags", [])}
            for k, v in list(kb["industries"].items())[:10]
        ]
    }

def _do_knowledge_search(industry: str, keywords: List[str], user_id: int = None):
    """内部知识库搜索逻辑（供路由和报告生成共用）"""
    kb = load_global_knowledge()

    # 1. 匹配行业
    industry_lower = industry.lower()
    matched_industry = None
    for key, data in kb["industries"].items():
        tags = [t.lower() for t in data.get("tags", [])]
        name = data.get("industry_name", "").lower()
        if industry_lower in name or any(industry_lower in t or t in industry_lower for t in tags):
            matched_industry = data
            break

    # 2. 匹配案例
    query = industry + " " + " ".join(keywords)
    query_lower = query.lower()
    scored_cases = []
    for case in kb["cases"]:
        score = 0
        meta = case.get("meta", {})
        case_industry = meta.get("industry", "").lower()
        case_scene = meta.get("scene", "").lower()
        if case_industry in query_lower or query_lower in case_industry:
            score += 5
        else:
            for word in re.split(r'[，,、。/\s]+', query_lower):
                if len(word) >= 2 and word in case_industry:
                    score += 4
                    break
        if case_scene in query_lower:
            score += 3
        if score > 0:
            scored_cases.append((score, case))

    scored_cases.sort(key=lambda x: x[0], reverse=True)
    matched_cases = [c for _, c in scored_cases[:3]]

    # 3. 匹配模板
    scored_templates = []
    for tpl in kb["templates"]:
        score = 0
        meta = tpl.get("meta", {})
        tpl_industry = meta.get("industry", "").lower()
        applicable = meta.get("applicable_when", "").lower()
        if tpl_industry in query_lower:
            score += 5
        for word in keywords:
            if word.lower() in applicable:
                score += 2
        if score >= 4:
            scored_templates.append((score, tpl))

    scored_templates.sort(key=lambda x: x[0], reverse=True)
    matched_templates = [t for _, t in scored_templates[:2]]

    # 4. 服务商私有知识库
    conn = get_db()
    cursor = conn.cursor()
    user_kb = []
    if user_id:
        if industry:
            cursor.execute(
                "SELECT * FROM provider_knowledge WHERE user_id = ? AND (industry = ? OR category = 'industry_knowledge')",
                (user_id, industry)
            )
        else:
            cursor.execute("SELECT * FROM provider_knowledge WHERE user_id = ?", (user_id,))
        for row in cursor.fetchall():
            user_kb.append(dict(row))
    conn.close()

    return {
        "industry_knowledge": matched_industry.get("content", "")[:3000] if matched_industry else "",
        "matched_cases": matched_cases,
        "matched_templates": matched_templates,
        "user_knowledge": user_kb,
        "matched": bool(matched_industry or matched_cases or matched_templates)
    }

@app.post("/api/knowledge/search")
async def search_knowledge(body: dict, user: dict = Depends(require_auth)):
    """搜索知识库（API路由）"""
    industry = body.get("industry", "")
    keywords = body.get("keywords", [])
    return _do_knowledge_search(industry, keywords, user["user_id"])

# ==================== 服务商知识库管理 ====================

@app.post("/api/provider-knowledge")
async def add_provider_knowledge(
    body: dict,
    user: dict = Depends(require_auth)
):
    """添加服务商知识库条目"""
    category = body.get("category", "")
    title = body.get("title", "")
    content = body.get("content", "")
    industry = body.get("industry", "")
    tags = body.get("tags", "")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO provider_knowledge (user_id, category, title, content, industry, tags) VALUES (?, ?, ?, ?, ?, ?)",
        (user["user_id"], category, title, content, industry, tags)
    )
    conn.commit()
    item_id = cursor.lastrowid
    conn.close()

    return {"success": True, "id": item_id}

@app.get("/api/provider-knowledge")
async def list_provider_knowledge(category: str = "", user: dict = Depends(require_auth)):
    """获取服务商知识库列表"""
    conn = get_db()
    cursor = conn.cursor()

    if category:
        cursor.execute(
            "SELECT * FROM provider_knowledge WHERE user_id = ? AND category = ? ORDER BY created_at DESC",
            (user["user_id"], category)
        )
    else:
        cursor.execute(
            "SELECT * FROM provider_knowledge WHERE user_id = ? ORDER BY created_at DESC",
            (user["user_id"],)
        )

    items = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return items

@app.delete("/api/provider-knowledge/{item_id}")
async def delete_provider_knowledge(item_id: int, user: dict = Depends(require_auth)):
    """删除服务商知识库条目"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM provider_knowledge WHERE id = ? AND user_id = ?", (item_id, user["user_id"]))
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/api/provider-knowledge/stats")
async def get_knowledge_stats(user: dict = Depends(require_auth)):
    """获取服务商知识库统计"""
    conn = get_db()
    cursor = conn.cursor()

    stats = {}
    categories = ["case", "template", "qa", "sales_tool", "industry_knowledge"]
    for cat in categories:
        cursor.execute(
            "SELECT COUNT(*) FROM provider_knowledge WHERE user_id = ? AND category = ?",
            (user["user_id"], cat)
        )
        stats[cat] = cursor.fetchone()[0]

    conn.close()
    return stats

# ==================== 知识库文件管理 ====================

@app.post("/api/kb/upload")
async def upload_kb_file(
    file: UploadFile = File(...),
    display_name: str = Form(...),
    category: str = Form(...),
    industry: str = Form(""),
    user: dict = Depends(require_auth)
):
    """上传知识库文件"""
    import uuid
    import shutil

    file_id = str(uuid.uuid4())
    user_kb_dir = KB_DIR / str(user["user_id"])
    user_kb_dir.mkdir(parents=True, exist_ok=True)

    # 保存文件
    ext = Path(file.filename).suffix.lower()
    safe_filename = f"{file_id}{ext}"
    filepath = user_kb_dir / safe_filename

    with open(filepath, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # 提取文本内容
    content = ""
    try:
        if ext == ".txt" or ext == ".md":
            content = filepath.read_text(encoding="utf-8")
        elif ext == ".docx":
            from docx import Document
            doc = Document(filepath)
            content = "\n".join([p.text for p in doc.paragraphs])
        elif ext == ".pdf":
            import pdfplumber
            with pdfplumber.open(filepath) as pdf:
                content = "\n".join([page.extract_text() or "" for page in pdf.pages])
        elif ext in [".xls", ".xlsx"]:
            import openpyxl
            wb = openpyxl.load_workbook(filepath)
            for sheet in wb.worksheets:
                for row in sheet.iter_rows(values_only=True):
                    content += " ".join([str(c) for c in row if c]) + "\n"
        elif ext == ".csv":
            import csv
            with open(filepath, encoding="utf-8") as cf:
                reader = csv.reader(cf)
                for row in reader:
                    content += " ".join([str(c) for c in row if c]) + "\n"
        elif ext == ".doc":
            # 先尝试用 antiword 提取文本
            import subprocess
            result = subprocess.run(["antiword", str(filepath)], capture_output=True, text=True)
            if result.returncode == 0:
                content = result.stdout
    except Exception as e:
        content = f"[解析失败: {str(e)}]"

    char_count = len(content)

    # 保存到数据库
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO kb_files (id, user_id, original_filename, display_name, category, industry, filepath, status, progress, char_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'completed', 100, ?)
    """, (file_id, user["user_id"], file.filename, display_name, category, industry, str(filepath), char_count))
    conn.commit()
    conn.close()

    return {"id": file_id, "status": "completed", "progress": 100, "char_count": char_count}


@app.get("/api/kb/files")
async def list_kb_files(category: str = "", user: dict = Depends(require_auth)):
    """获取知识库文件列表"""
    conn = get_db()
    cursor = conn.cursor()

    if category:
        cursor.execute("""
            SELECT * FROM kb_files WHERE user_id = ? AND category = ? ORDER BY created_at DESC
        """, (user["user_id"], category))
    else:
        cursor.execute("""
            SELECT * FROM kb_files WHERE user_id = ? ORDER BY created_at DESC
        """, (user["user_id"],))

    files = [dict(row) for row in cursor.fetchall()]

    # 计算完善度
    total = len(files)
    completion = min(int(total / 10 * 100), 100) if total > 0 else 0

    # 计算分类统计
    stats = {"case": 0, "template": 0, "knowledge": 0, "qa": 0, "sales": 0}
    cursor.execute("SELECT category, COUNT(*) as cnt FROM kb_files WHERE user_id = ? GROUP BY category", (user["user_id"],))
    for row in cursor.fetchall():
        if row["category"] in stats:
            stats[row["category"]] = row["cnt"]

    conn.close()
    return {"files": files, "total": total, "completion": completion, "stats": stats}


@app.get("/api/kb/enhancement")
async def get_kb_enhancement(user: dict = Depends(require_auth)):
    """获取知识库增强效果"""
    conn = get_db()
    cursor = conn.cursor()

    # 获取所有文件内容
    cursor.execute("SELECT char_count FROM kb_files WHERE user_id = ? AND status = 'completed'", (user["user_id"],))
    rows = cursor.fetchall()
    total_chars = sum(row["char_count"] for row in rows)

    if total_chars == 0:
        conn.close()
        return {"examples": []}

    # 根据内容生成3个示例
    cursor.execute("""
        SELECT original_filename, category, char_count FROM kb_files
        WHERE user_id = ? AND status = 'completed' ORDER BY char_count DESC LIMIT 5
    """, (user["user_id"],))
    kb_files = [dict(row) for row in cursor.fetchall()]
    conn.close()

    if not kb_files:
        return {"examples": []}

    # 调用AI生成示例
    kb_summary = "\n".join([
        f"- [{f['category']}] {f['original_filename']} ({f['char_count']}字)"
        for f in kb_files
    ])

    system_prompt = """你是一个售前知识库助手。根据用户上传的知识库内容，生成3个"客户问题-通用回答-增强回答"的示例。

要求：
1. 客户问题：模拟真实客户会问的问题
2. 通用回答：没有知识库时的泛泛回答
3. 增强回答：基于知识库内容的有说服力的回答，不要提到具体文件名，用"基于我们的服务经验"等表述
4. 三个示例要覆盖不同方面：行业案例、项目经验、报价方法等

输出JSON格式：
{
  "examples": [
    {"question": "问题1", "default_answer": "通用回答", "enhanced_answer": "增强回答"},
    {"question": "问题2", "default_answer": "通用回答", "enhanced_answer": "增强回答"},
    {"question": "问题3", "default_answer": "通用回答", "enhanced_answer": "增强回答"}
  ]
}"""

    user_prompt = f"知识库内容概览：\n{kb_summary}\n\n根据以上内容，生成3个有说服力的售前示例。"

    result = call_deepseek(system_prompt, user_prompt)

    # 解析JSON结果
    import json
    import re
    try:
        # 尝试提取JSON
        match = re.search(r'\{[\s\S]*\}', result)
        if match:
            data = json.loads(match.group())
            return data
    except:
        pass

    return {"examples": [
        {"question": "做过我们行业案例吗？", "default_answer": "有过一些相关案例", "enhanced_answer": "已服务过20+同行业客户，涵盖制造、零售等多个领域"},
        {"question": "项目一般多久完成？", "default_answer": "通常1-3个月", "enhanced_answer": "标准项目45天完成，最快可压缩至30天"},
        {"question": "怎么收费？", "default_answer": "根据项目复杂度定价", "enhanced_answer": "采用基础服务费+模块费+实施费的透明定价模式"}
    ]}


@app.delete("/api/kb/files/{file_id}")
async def delete_kb_file(file_id: str, user: dict = Depends(require_auth)):
    """删除知识库文件"""
    conn = get_db()
    cursor = conn.cursor()

    # 获取文件路径
    cursor.execute("SELECT filepath FROM kb_files WHERE id = ? AND user_id = ?", (file_id, user["user_id"]))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="文件不存在")

    filepath = row["filepath"]

    # 删除文件
    import os
    if os.path.exists(filepath):
        os.remove(filepath)

    # 删除数据库记录
    cursor.execute("DELETE FROM kb_files WHERE id = ? AND user_id = ?", (file_id, user["user_id"]))
    conn.commit()

    # 重新计算完善度
    cursor.execute("SELECT COUNT(*) FROM kb_files WHERE user_id = ?", (user["user_id"],))
    total = cursor.fetchone()[0]
    completion = min(int(total / 10 * 100), 100) if total > 0 else 0

    conn.close()
    return {"success": True, "completion": completion}


# ==================== 客户管理 ====================

@app.get("/api/clients")
async def list_clients(user: dict = Depends(require_auth)):
    """获取客户列表"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM clients WHERE user_id = ? ORDER BY updated_at DESC",
        (user["user_id"],)
    )
    clients = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return clients

@app.post("/api/clients")
async def create_client(body: dict, user: dict = Depends(require_auth)):
    """创建客户"""
    name = body.get("name", "")
    industry = body.get("industry", "")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO clients (user_id, name, industry) VALUES (?, ?, ?)",
        (user["user_id"], name, industry)
    )
    conn.commit()
    client_id = str(cursor.lastrowid)  # 统一返回字符串格式，与前端 ID 格式一致
    conn.close()
    return {"success": True, "id": client_id}

@app.get("/api/clients/{client_id}")
async def get_client(client_id: str, user: dict = Depends(require_auth)):
    """获取客户详情"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM clients WHERE id = ? AND user_id = ?",
        (client_id, user["user_id"])
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="客户不存在")

    result = dict(row)
    # Parse JSON fields back to objects
    for field in ("step1_result", "step2_report", "step2_todo", "step2_schema", "step3_summary", "uploaded_files", "transcript", "step4_report", "step4_presales", "step4_technical", "step5_schema"):
        if result.get(field) and isinstance(result[field], str):
            try:
                result[field] = json.loads(result[field])
            except:
                pass
    return result

@app.put("/api/clients/{client_id}")
async def update_client(client_id: str, data: dict, user: dict = Depends(require_auth)):
    """更新客户"""
    conn = get_db()
    cursor = conn.cursor()

    # 检查所有权
    cursor.execute("SELECT id FROM clients WHERE id = ? AND user_id = ?", (client_id, user["user_id"]))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="客户不存在")

    # 更新字段
    allowed_fields = ["name", "industry", "initial_demand", "status", "step1_result", "step2_report", "step2_todo", "step2_schema", "step3_summary", "uploaded_files", "transcript", "step4_report", "step4_presales", "step4_technical", "step5_schema", "demo_url", "_wecom_docid", "_wecom_url", "_step1_wecom_docid", "_step1_wecom_url"]
    updates = []
    values = []
    for field in allowed_fields:
        if field in data:
            updates.append(f"{field} = ?")
            val = data[field]
            # JSON fields must be serialized to string for SQLite
            if field in ("step1_result", "step2_report", "step2_todo", "step2_schema", "step3_summary", "uploaded_files", "transcript", "step4_report", "step4_presales", "step4_technical", "step5_schema"):
                val = json.dumps(val) if val is not None else ""
            values.append(val)

    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        values.append(client_id)
        cursor.execute(f"UPDATE clients SET {', '.join(updates)} WHERE id = ?", values)
        conn.commit()

    conn.close()
    return {"success": True}

@app.delete("/api/clients/{client_id}")
async def delete_client(client_id: str, user: dict = Depends(require_auth)):
    """删除客户"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM clients WHERE id = ? AND user_id = ?", (client_id, user["user_id"]))
    conn.commit()
    conn.close()
    return {"success": True}

# ==================== 报告生成 ====================

REPORTS_SYSTEM_PROMPT = """你是一个专业的企业微信智能表格售前方案顾问。根据服务商与客户的沟通记录，生成结构化的需求洞察报告。

## 输出格式（严格遵守，直接输出，不要开场白/总结语/注意事项）

## 客户信息
- 行业：
- 规模：
- 需求方向：

## 核心痛点
逐条列出客户提到的痛点，每条用客户原话引用，并简要分析该痛点的业务影响：
1. **痛点名称**："客户原话引用"
   - 影响：xxx

## 业务场景
- 核心流程：用箭头描述完整业务链路（如：业务员提交 → 中台复审 → 后台归档）
- 涉及角色：列出每个环节对应的角色/部门
- 数据流向：数据从哪里产生、在哪里流转、最终在哪里使用

## 详细规格
- 数据规模：预估数据量（条/月）、使用人数
- 权限需求：按角色说明（谁能看什么、谁能改什么）
- 提醒/通知：需要哪些自动通知场景
- 对接需求：是否有外部系统需要对接

## 智能表格搭建方案

### 子表结构
按表格形式列出每张子表：
| 子表名称 | 用途 | 核心字段（6-8个） | 使用者 |
|---------|------|------------------|--------|

### 自动化规则
逐条列出关键自动化（触发条件 → 执行动作）：
1. 当xxx时 → 自动xxx
2. ...

### 推荐视图
- 表格视图：用于xxx
- 看板视图：用于xxx
- 仪表盘：管理层看xxx指标

### 权限设计
按角色说明数据隔离策略

## 预估交付周期
- 第一期（x周）：xxx
- 第二期（x周）：xxx

## 待确认事项

AI 自动识别沟通记录中客户没有讲清楚的地方，列出需要服务商后续跟进确认的事项：
- ❓ 具体问题描述（例如"是否需要与ERP对接？客户提到了用友但没说是否要数据同步"）
- ❓ ...
- ❓ ...
列出所有需要二次确认的事项，帮服务商知道哪些信息还没拿到。

## 原则
1. 基于沟通记录中客户明确说到的内容，不要臆测
2. 痛点必须用客户原话引用（加引号），这是报告最有说服力的部分
3. 方案要细致到字段级别，服务商看了就知道要搭什么
4. 不要输出开场白、总结语或"请注意"之类的废话
5. 报告要有层次感：痛点用加粗、流程用箭头、方案用表格
6. 待确认事项是关键产出：分析客户话语中的模糊地带和遗漏"""

DEMO_SYSTEM_PROMPT = """你是一个专业的企业微信智能表格架构师。根据客户需求设计智能表格Demo结构。

## 输出格式（严格JSON，不要markdown代码块包裹，直接输出JSON）

{"doc_name":"表格名称","sheets":[{"sheet_name":"子表名称","fields":[{"field_title":"字段名","field_type":"字段类型"}],"sample_records":[{"字段名":"示例值"}]}]}

## 字段类型只能用
FIELD_TYPE_TEXT, FIELD_TYPE_NUMBER, FIELD_TYPE_SINGLE_SELECT, FIELD_TYPE_DATE_TIME, FIELD_TYPE_CURRENCY, FIELD_TYPE_PERCENTAGE, FIELD_TYPE_PROGRESS, FIELD_TYPE_PHONE_NUMBER, FIELD_TYPE_EMAIL, FIELD_TYPE_URL, FIELD_TYPE_CHECKBOX

## 设计原则
1. 如果有字段经验池，根据客户实际需求从中挑选合适的表和字段组合，不要照搬全部
2. 客户没提到的需求对应的表可以不给
3. 客户提了经验池中没有的需求，自行补充合理字段
4. 子表数量根据客户实际需求复杂度确定
5. 每个子表给6-10个核心字段
6. 每个子表给2-3条示例数据（数据要真实可信，贴合行业）
7. 字段命名要专业、贴合行业术语
8. 一张表聚焦一个业务对象"""


@app.post("/api/reports/generate")
async def generate_report(body: dict, user: dict = Depends(require_auth)):
    """生成需求分析报告或Demo方案"""
    transcript = body.get("transcript", "")
    industry = body.get("industry", "")
    output_type = body.get("output_type", "report")  # report or schema

    if not industry:
        raise HTTPException(status_code=400, detail="industry is required")

    # 构建知识库上下文
    kb = load_global_knowledge()
    query = f"{industry} {transcript[:200]}".strip()

    # 匹配行业知识
    industry_lower = industry.lower()
    industry_text = ""
    for key, data in kb["industries"].items():
        tags = [t.lower() for t in data.get("tags", [])]
        name = data.get("industry_name", "").lower()
        if industry_lower in name or any(industry_lower in t or t in industry_lower for t in tags):
            content = data.get("content", "")
            industry_text = content[:2000] if len(content) > 2000 else content
            break

    # 匹配案例
    query_lower = query.lower()
    scored_cases = []
    for case in kb["cases"]:
        score = 0
        meta = case.get("meta", {})
        case_industry = meta.get("industry", "").lower()
        case_scene = meta.get("scene", "").lower()
        if case_industry in query_lower or query_lower in case_industry:
            score += 5
        if case_scene in query_lower:
            score += 3
        if score > 0:
            scored_cases.append((score, case))
    scored_cases.sort(key=lambda x: x[0], reverse=True)
    matched_cases = scored_cases[:2]

    case_context = ""
    for score, case in matched_cases:
        meta = case.get("meta", {})
        solution = case.get("solution", {})
        case_context += f"【案例：{meta.get('industry', '')} - {meta.get('scene', '')}】\n"
        case_context += f"  架构：{solution.get('architecture', '')}\n"
        tables = solution.get("tables", [])
        if tables:
            for t in tables[:5]:
                case_context += f"  - {t.get('table_name', '')}\n"
        case_context += "\n"

    kb_context = ""
    if industry_text:
        kb_context += f"## 行业知识\n{industry_text}\n\n"
    if case_context:
        kb_context += f"## 相关交付案例\n{case_context}\n\n"

    if output_type == "schema":
        # 生成Demo方案
        system_prompt = DEMO_SYSTEM_PROMPT
        user_prompt = f"{kb_context}## 客户沟通记录\n\n{transcript}\n\n请基于以上沟通记录设计智能表格的表和字段结构，输出JSON。"
        max_tokens = 2000
    else:
        # 生成需求报告
        system_prompt = REPORTS_SYSTEM_PROMPT
        user_prompt = f"{kb_context}## 客户沟通记录\n\n{transcript}\n\n请基于以上沟通记录，生成结构化的需求分析报告。"
        max_tokens = 4000

    result = call_deepseek(system_prompt, user_prompt, max_tokens=max_tokens)

    # 解析JSON（如果是schema）
    demo_json = None
    if output_type == "schema":
        import re, json
        try:
            json_match = re.search(r'```json\s*(.*?)\s*```', result, re.DOTALL)
            if json_match:
                demo_json = json.loads(json_match.group(1))
            else:
                demo_json = json.loads(result)
        except:
            demo_json = None

    # 解析报告Markdown为JSON（report类型）
    parsed_report = None
    if output_type != "schema":
        parsed_report = parse_report_markdown_to_json(result)

    return {
        "result": parsed_report if parsed_report else result,
        "demo_json": demo_json,
        "context_used": {
            "industry_matched": bool(industry_text),
            "cases_matched": bool(case_context)
        }
    }

# ==================== Step4 方案生成 ====================

STEP4_PRESALES_PROMPT = """你是一个企业微信智能表格售前方案顾问。请基于以下客户信息，生成《需求确认 & 方案设计表》的完整内容。

【输入信息】
客户名称：{customer_name}
行业：{industry}
规模：{scale}
初始需求表达：{initial_demand}

【Step1 - 客户画像】
{company_background}

【Step1 - 行业痛点】
{pain_points}

【Step2 - 信息缺口】
{gaps}

【Step2 - 提问清单】
{must_ask}

【Step3 - 沟通记录汇总】
{transcript}

【生成规则】
1. 区分「客户已确认事实」vs「AI推断建议」：客户原话明确说过的才能写「客户已确认」，推断内容写「建议」「待确认」「二期评估」
2. 一期边界：客户明确提到 + 当前痛点强 + 可用企微/智能表格轻量实现 + 不依赖复杂接口/数据清洗
3. 二期边界：外部系统对接、复杂数据回写、AI自动判断、高级分析、历史数据清洗
4. 暂不纳入：替代专业ERP/CRM、强监管实时风控、客户未提出但想强行卖的模块
5. 方案定位：企业微信入口+智能表格数据底座+审批/自动化/权限/看板的轻量定制方案
6. 客户原话必须翻译成业务语言

请直接输出 JSON，不要输出其他内容。"""

STEP4_TECHNICAL_PROMPT = """你是一个企业微信智能表格技术方案顾问（内部评估用）。请基于以下客户信息，生成技术路线及报价方案。

【输入信息】
客户名称：{customer_name}
行业：{industry}
规模：{scale}
初始需求表达：{initial_demand}

【Step1 - 客户画像】
{company_background}

【Step1 - 行业痛点】
{pain_points}

【Step2 - 信息缺口】
{gaps}

【Step3 - 沟通记录汇总】
{transcript}

【生成规则】
1. 这是内部评估用，不是给客户看的正式汇报版
2. 智能表格设计要具体：表名、字段名、字段类型、必填/选填、权限角色、填写规则
3. 审批和自动化要写触发条件、审批节点、同步动作
4. 一期边界：企微原生能力可实现、不依赖外部系统对接、不需要复杂数据清洗
5. 二期评估：需要API对接、数据回写、外部系统集成的部分
6. 不确定的地方一律写「待确认」或「二期评估」，不要瞎猜
7. 报价相关：复杂度评估、交付工作量评估、风险点

请直接输出 JSON，不要输出其他内容。"""

@app.post("/api/step4/generate")
async def generate_step4_artifacts(body: dict, user: dict = Depends(require_auth)):
    """生成 Step4 售前方案和技术路线方案"""
    client_id = body.get("client_id")
    artifact_type = body.get("type", "both")  # both, presales, technical

    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required")

    # 获取客户数据
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clients WHERE id = ? AND user_id = ?", (client_id, user["user_id"]))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="客户不存在")

    client = dict(row)
    # 解析 JSON 字段
    for field in ("step1_result", "step2_report", "step2_todo", "step2_schema", "step3_summary", "uploaded_files"):
        if client.get(field) and isinstance(client[field], str):
            try:
                client[field] = json.loads(client[field])
            except:
                pass

    # 构建输入上下文
    customer_name = client.get("name", "")
    industry = client.get("industry", "")
    scale = client.get("scale", "")
    initial_demand = client.get("initial_demand", "")

    step1 = client.get("step1_result", {}) or {}
    company_background = step1.get("part1", {}).get("company_background", "") or ""
    pain_points = "\n".join(step1.get("part1", {}).get("pain_points", []) or [])
    gaps = "\n".join([f"- {g.get('gap', '')}" for g in (step1.get("part2") or [])])

    must_ask = step1.get("part3", {}).get("must_ask", []) or []
    must_ask_text = "\n".join([f"{i+1}. {q.get('question', '')}" for i, q in enumerate(must_ask)])

    # 沟通记录汇总
    uploaded_files = client.get("uploaded_files") or []
    if isinstance(uploaded_files, str):
        try:
            uploaded_files = json.loads(uploaded_files)
        except:
            uploaded_files = []
    transcript = "\n\n".join([f"【{f.get('name', '记录')}】{f.get('text', '')}" for f in uploaded_files if f.get('text')])

    # 替换 prompt 中的变量
    def build_context(prompt_template):
        return prompt_template.format(
            customer_name=customer_name,
            industry=industry,
            scale=scale,
            initial_demand=initial_demand,
            company_background=company_background,
            pain_points=pain_points,
            gaps=gaps,
            must_ask=must_ask_text,
            transcript=transcript or "暂无沟通记录"
        )

    result = {}

    if artifact_type in ("both", "presales"):
        user_prompt = build_context(STEP4_PRESALES_PROMPT)
        presales_result = call_deepseek(STEP4_PRESALES_PROMPT, user_prompt, max_tokens=4000)
        # 尝试解析 JSON
        try:
            # 提取 JSON
            json_match = re.search(r'\{[\s\S]*\}', presales_result)
            if json_match:
                result["presales"] = json.loads(json_match.group())
            else:
                result["presales"] = {"raw": presales_result}
        except:
            result["presales"] = {"raw": presales_result}

    if artifact_type in ("both", "technical"):
        user_prompt = build_context(STEP4_TECHNICAL_PROMPT)
        technical_result = call_deepseek(STEP4_TECHNICAL_PROMPT, user_prompt, max_tokens=4000)
        try:
            json_match = re.search(r'\{[\s\S]*\}', technical_result)
            if json_match:
                result["technical"] = json.loads(json_match.group())
            else:
                result["technical"] = {"raw": technical_result}
        except:
            result["technical"] = {"raw": technical_result}

    return result

@app.post("/api/step4/preview-html")
async def generate_step4_preview_html(body: dict, user: dict = Depends(require_auth)):
    """生成售前方案可视化 HTML"""
    import uuid
    client_id = body.get("client_id")

    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clients WHERE id = ? AND user_id = ?", (client_id, user["user_id"]))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="客户不存在")

    client = dict(row)
    for field in ("step1_result", "step2_report", "step2_todo", "step2_schema", "step4_presales", "step4_technical"):
        if client.get(field) and isinstance(client[field], str):
            try:
                client[field] = json.loads(client[field])
            except:
                pass

    customer_name = client.get("name", "客户")
    industry = client.get("industry", "")
    scale = client.get("scale", "")
    initial_demand = client.get("initial_demand", "")

    presales = client.get("step4_presales") or {}
    technical = client.get("step4_technical") or {}

    html_content = generate_solution_html(customer_name, industry, scale, initial_demand, presales, technical)

    public_dir = Path(__file__).parent / "public"
    public_dir.mkdir(exist_ok=True)
    filename = "solution_{}_{}.html".format(client_id, uuid.uuid4().hex[:8])
    filepath = public_dir / filename
    filepath.write_text(html_content, encoding="utf-8")

    return {"success": True, "url": "/public/{}".format(filename), "filename": filename}


def generate_solution_html(customer_name, industry, scale, initial_demand, presales, technical):
    positioning = presales.get('方案定位') or ''
    phase1 = presales.get('一期边界') or []
    phase2 = presales.get('二期边界') or []
    customer_confirm = presales.get('客户需求确认') or {}

    phase1_html = ''
    for i, item in enumerate(phase1[:4], 1):
        if isinstance(item, dict):
            item_name = item.get('模块名称', str(item))
            item_desc = item.get('模块描述', '')
        else:
            item_name = str(item)
            item_desc = ''
        phase1_html += '<div class="scenario"><div class="scenario-side"><div class="num">{:02d}</div><h3>{}</h3><div class="prio"><span class="badge p0">P0 一期重点</span></div></div><div class="scenario-body"><h3>建设内容</h3><p>{}</p></div></div>'.format(i, item_name, item_desc)

    phase2_html = ''
    for item in phase2:
        if isinstance(item, dict):
            item_name = item.get('模块名称', str(item))
            item_desc = item.get('说明', '')
        else:
            item_name = str(item)
            item_desc = ''
        phase2_html += '<div class="qa-card"><b>二期：{}</b><span>{}</span></div>'.format(item_name, item_desc)

    confirm_html = ''
    for q in customer_confirm.get('待确认问题', []):
        q_text = q.get('问题', str(q)) if isinstance(q, dict) else str(q)
        q_desc = q.get('说明', '') if isinstance(q, dict) else ''
        confirm_html += '<div class="qa-card"><b>{}</b><span>{}</span></div>'.format(q_text, q_desc)

    return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{customer_name}｜企业微信智能表格方案</title>
  <style>
    :root{{--wx-blue:#1677ff;--ink:#101828;--text:#344054;--muted:#667085;--line:#e6edf7;--bg:#f5f8fc;--card:#fff;--radius:20px}}
    *{{box-sizing:border-box}}body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:var(--text);background:var(--bg);line-height:1.65}}
    .page{{max-width:1240px;margin:0 auto;padding:26px 24px 76px}}
    .topbar{{height:58px;display:flex;align-items:center;margin-bottom:18px}}
    .brand{{display:flex;align-items:center;gap:12px;font-weight:800;color:var(--ink)}}
    .brand-mark{{width:34px;height:34px;border-radius:12px;background:linear-gradient(135deg,#1677ff,#1ec7f4)}}
    .hero{{position:relative;border-radius:32px;background:linear-gradient(135deg,rgba(255,255,255,.97),rgba(235,246,255,.96));min-height:280px;padding:48px}}
    .hero h1{{margin:0;color:var(--ink);font-size:40px}}
    .hero p{{margin:16px 0;color:var(--muted);font-size:18px}}
    .chips{{display:flex;gap:10px;flex-wrap:wrap}}
    .chip{{padding:8px 16px;background:#fff;border:1px solid #e2edf9;border-radius:999px;font-size:13px}}
    section{{margin-top:38px}}
    .section-head{{margin-bottom:18px}}
    .kicker{{color:var(--wx-blue);font-size:12px;font-weight:900}}
    .section-title h2{{font-size:28px;color:var(--ink);margin:5px 0 0}}
    .summary-strip{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:18px}}
    .summary-item{{background:#fff;border:1px solid var(--line);border-radius:18px;padding:18px}}
    .summary-item strong{{display:block;color:#14213d;font-size:16px}}
    .summary-item span{{font-size:13px;color:var(--muted)}}
    .scenario-list{{display:grid;gap:16px}}
    .scenario{{display:grid;grid-template-columns:220px 1fr;gap:18px;padding:22px;border-radius:20px;background:#fff;border:1px solid var(--line)}}
    .scenario-side{{border-radius:16px;background:linear-gradient(180deg,#f1f8ff,#fff);padding:18px}}
    .scenario-side .num{{font-size:34px;font-weight:950;color:var(--wx-blue)}}
    .scenario-side h3{{margin:8px 0 0;font-size:16px}}
    .scenario-body h3{{margin:0 0 8px;font-size:18px}}
    .scenario-body p{{margin:0;color:var(--muted)}}
    .badge{{display:inline-flex;padding:4px 10px;border-radius:999px;font-size:12px;font-weight:800}}
    .p0{{background:#fff1f0;color:#b42318}}
    .qa{{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}}
    .qa-card{{background:#fff;border:1px solid var(--line);border-radius:16px;padding:18px}}
    .qa-card b{{display:block;color:#1f3f70;margin-bottom:6px}}
    .qa-card span{{color:var(--muted);font-size:14px}}
    .cta{{margin-top:42px;border-radius:24px;padding:34px;background:linear-gradient(135deg,#1267e8,#22b8ff);color:#fff}}
    .cta h2{{margin:0 0 8px;color:#fff;font-size:24px}}
    .cta p{{margin:0;color:rgba(255,255,255,.86)}}
    @media(max-width:768px){{.summary-strip,.scenario{{grid-template-columns:1fr}}.qa{{grid-template-columns:1fr}}}}
  </style>
</head>
<body>
  <div class="page">
    <header class="topbar"><div class="brand"><span class="brand-mark"></span><span>企业微信生态服务方案</span></div></header>
    <section class="hero">
      <h1>{customer_name}<br>需求整理方案</h1>
      <p>{positioning}</p>
      <div class="chips"><span class="chip">{industry}</span><span class="chip">{scale}</span><span class="chip">一期重点建设</span></div>
    </section>
    <section><div class="section-head"><div class="kicker">01 / Background</div><div class="section-title"><h2>客户现状</h2></div></div>
      <div class="summary-strip">
        <div class="summary-item"><strong>客户名称</strong><span>{customer_name}</span></div>
        <div class="summary-item"><strong>所属行业</strong><span>{industry}</span></div>
        <div class="summary-item"><strong>企业规模</strong><span>{scale}</span></div>
        <div class="summary-item"><strong>需求方向</strong><span>{initial_demand}</span></div>
      </div>
    </section>
    <section><div class="section-head"><div class="kicker">02 / Phase 1</div><div class="section-title"><h2>一期建设范围</h2></div></div>
      <div class="scenario-list">{phase1_html}</div>
    </section>
    <section><div class="section-head"><div class="kicker">03 / Phase 2</div><div class="section-title"><h2>二期评估范围</h2></div></div>
      <div class="qa">{phase2_html}</div>
    </section>
    <section><div class="section-head"><div class="kicker">04 / Confirm</div><div class="section-title"><h2>待确认问题</h2></div></div>
      <div class="qa">{confirm_html}</div>
    </section>
    <section class="cta"><div><h2>建议以一期建设范围作为起步</h2><p>先解决核心业务诉求，再基于实际使用情况迭代二期能力</p></div></section>
  </div>
</body>
</html>'''.format(
        customer_name=customer_name,
        industry=industry,
        scale=scale or '规模待确认',
        initial_demand=initial_demand or '待沟通',
        positioning=positioning or '基于企业微信智能表格的轻量定制方案',
        phase1_html=phase1_html or '<p style="color:var(--muted)">一期范围待生成</p>',
        phase2_html=phase2_html or '<div class="qa-card"><b>暂无二期评估内容</b><span>待后续沟通确认</span></div>',
        confirm_html=confirm_html or '<div class="qa-card"><b>暂无待确认问题</b><span>请在方案确认时补充</span></div>'
    )


# ==================== 企业微信智能表格 ====================

import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

@app.post("/api/wecom/create_smarttable")
async def create_wecom_smarttable(body: dict, user: dict = Depends(require_auth)):
    """创建企业微信智能表格"""
    doc_name = body.get("doc_name", "智能表格Demo")
    sheets = body.get("sheets", [])
    need_dashboard = body.get("need_dashboard", False)
    need_gantt = body.get("need_gantt", False)

    try:
        # 构建方案JSON
        schema = {
            "doc_name": doc_name,
            "sheets": sheets,
            "need_dashboard": need_dashboard,
            "need_gantt": need_gantt
        }

        # 调用Node.js脚本
        result = subprocess.run(
            ["node", str(SCRIPT_DIR / "wecom_creator.mjs"), json.dumps(schema, ensure_ascii=False)],
            capture_output=True, text=True, timeout=120
        )

        if result.returncode != 0:
            return {"success": False, "error": result.stderr or "创建失败"}

        output = json.loads(result.stdout)
        return output

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "创建超时，请重试"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ==================== 智能提问清单生成 ====================

QUESTION_LIST_SYSTEM_PROMPT = """你是一个资深的企业微信智能表格定制开发售前顾问。

你的任务:根据客户行业和初始需求,为服务商输出一份**简洁清晰**的调研准备材料。

## ⚠️ 核心原则
- 问题要短,一句话能说清就不写两句
- 像面对面聊天,不要书面语
- 整体排版清爽,服务商一眼看清该问什么
- 不要在各部分之间加横线(---)

## 输出结构(严格3个部分,不要开场白/结尾总结,不要加横线分隔)

### PART1: 客户画像

**公司与需求背景**

先用一段自然的话介绍这家公司(基于客户提供的公司名称和行业信息,结合你对该行业的认知去描述):这家公司是做什么的、大概什么规模、主营业务是什么、客户群体是谁。写得像一个了解这个行业的人在给服务商介绍客户一样,不要像填表。

然后用几个要点补充服务商需要提前了解的信息:
- 这个行业目前的情况(市场环境、竞争压力、数字化程度等)
- 这个业务场景一般涉及哪些角色、哪些环节
- 客户这次的需求可能属于哪个业务板块
- 做这类项目需要考虑什么(基于行业经验)

❗ 重要:这段内容的目的是让服务商在联系客户前就对客户有基本了解,不要写得像填表或列清单。要像一个有经验的人在给你介绍情况一样自然。

**行业常见痛点**
- 🔥 痛点1
- 🔥 痛点2
- 🔥 痛点3

### PART2: 信息缺口

客户描述中明显缺失的关键信息,列3-5条,每条一句话:
- ❓ 缺失点

### PART3: 提问清单

❗❗❗ 这部分分为两个表格:「必问问题」和「深挖问题」

**必问问题**（严格11个）

| 序号 | 维度 | 提问 |
|------|------|------|
| 1 | 痛点收敛 | 问题正文(一句话)<br>*行业常见情况描述。可以进一步问客户:"XXX?""YYY?"* |
| 2 | 业务流程 | 问题正文(一句话)<br>*行业常见情况描述。可以进一步问客户:"XXX?""YYY?"* |
| ... | ... | ... |

**深挖问题**(可选3-5个,服务商想深入了解时使用)

| 序号 | 维度 | 提问 |
|------|------|------|
| 1 | 某维度 | 问题正文(一句话)<br>*行业常见情况描述。可以进一步问客户:"XXX?""YYY?"* |
| ... | ... | ... |

注意:每行的"提问"列内容格式两个表格相同:
- 第一行:问题正文(简短定性,一句话)
- 第二行(用 <br> 换行):*斜体小字*,先说行业常见情况,再说可以进一步问客户什么
- ❗不要出现"话术参考:""可追问:"这种前缀标签,直接写内容

## 提问维度(必问11个 + 深挖可选3-5个)

**必问问题维度(严格11个):**

| # | 维度 | 核心意图 |
|---|------|----------|
| 1 | 痛点收敛 | 哪个环节最头疼/最常出错/最花时间?收敛为P0、P1、P2 |
| 2 | 业务流转+角色 | 围绕痛点的业务链流程,流程上有哪些角色/部门/外部方 |
| 3 | 现状工具链+瓶颈 | 现在用什么工具,为什么无法解决问题(这决定了新方案要规避的坑) |
| 4 | 数据现状 | 数据来源、存储位置、数量级、更新频次 |
| 5 | 自动化诉求 | 希望自动化实现什么、在什么场景下触发 |
| 6 | 数据接入方式 | 数据进入新表格的方式(手动录入/系统打通同步/导入/表单填报) |
| 7 | 使用者清单 | 谁来用智能表格,是否有外部人(客户、经销商、供应商) |
| 8 | 权限隔离 | 数据是否要隔离(如A销售只看自己的客户,B部门只看自己的数据) |
| 9 | 仪表盘 | 希望重点展示什么业务指标,以什么维度展示 |
| 10 | 交付预期 | 期望上线时间、上线节奏、预算范围 |
| 11 | 开放补充 | 还有什么想补充的 |

**深挖问题维度(可选3-5个,必须与智能表格交付相关):**
- 字段细节(某个环节需要记录哪些字段)
- 关联关系(表与表之间的关联,如订单关联客户、关联产品)
- 流转规则(什么条件下数据流转到下一步,是否要审批)
- 通知规则(什么情况下通知谁、通过什么方式)
- 数据迁移(现有数据是否需要导入、格式是否统一)
- 多表协同(是否需要多张表联动,如订单表+库存表+客户表)

## 提问规则

**必问问题:**
1. 严格11个问题,不多不少
2. 问题正文必须**简短定性**(一句话),用大白话,像聊天一样
3. 问题必须结合客户的行业特点来设计,不能泛泛地问
4. 每个问题后用 <br> 换行,紧跟 *斜体小字*,内容结构:
   - 先说行业常见情况(如"该行业常见痛点是XXX""典型流程是XXX")
   - 再说可以进一步问客户什么(直接写问句,不要加"话术参考:""可追问:"等前缀)
   - 如有常见选项,直接列举
5. 参考知识库中的案例和字段经验池

**深挖问题:**
1. 3-5个问题,是服务商想更深入了解时可以问的
2. 格式要求和必问问题完全一样(表格 + 斜体小字)
3. 内容必须与智能表格交付相关:字段细节、表间关联、流转规则、通知规则、数据迁移、多表协同等
4. 不要和必问问题重复,要是更深入一层的内容
5. 不要出现跟智能表格交付无关的问题(如团队管理、商业模式等)

## 输出格式示例(仅示意,实际内容需结合客户行业)

### PART1: 客户画像

**公司与需求背景**

XX公司是一家专做欧美市场女装出口的外贸企业,主要业务是接海外客户订单然后分发给国内多家工厂生产。团队规模大概在几十人,业务员负责对接客户和跟单,这次主要是想解决订单管理和多工厂协同的问题。

- 服装外贸行业目前竞争激烈,客户订单小单快反趋势明显,对交付效率和跟单精细度要求越来越高
- 这个场景一般涉及:业务员、设计师、工厂联系人、货代;环节包括接单→打样→确认→排产→质检→发货
- 客户这次需求属于订单管理+生产协同板块,核心是解决从接单到交货的全流程跟踪
- 做这类项目需要考虑:多工厂分单的协同机制、交期预警、外部协作方权限控制、历史订单数据迁移

**行业常见痛点**
- 🔥 订单状态分散在微信群和Excel,无法实时查看进度
- 🔥 多工厂分单后信息同步滞后,导致交期延误
- 🔥 样品确认流程繁琐,客户反复修改无记录

### PART2: 信息缺口

- ❓ 未说明目前管理订单用什么工具
- ❓ 未描述团队规模和分工方式
- ❓ 未说明是否有外部协作方需要查看数据

### PART3: 提问清单

**必问问题**

| 序号 | 维度 | 提问 |
|------|------|------|
| 1 | 痛点收敛 | 目前哪个环节最让你头疼、最常出错或最花时间?<br>*服装外贸常见痛点:订单变更后生产计划调整不及时、多工厂分单信息同步滞后、样品确认反复无记录。"哪个步骤经常卡住?""有没有因信息没同步导致返工或客诉?"* |
| 2 | 业务流转+角色 | 一个订单从接单到交货,中间经过哪些环节和人?<br>*服装外贸典型流程:接单→打样→确认→生产→质检→发货,涉及业务员、设计、工厂、货代。"每个环节谁推进?信息怎么传?哪里容易断?"* |
| 3 | 现状工具链+瓶颈 | 现在用什么工具管,为什么觉得不够用?<br>*服装外贸常见工具:Excel、微信群、ERP(用友/金蝶)、丝路通。"是功能缺、太复杂没人用、还是数据打不通?""为什么现有工具解决不了这个问题?"* |
| 4 | 数据现状 | 相关数据现在存在哪里?大概多少条?多久更新一次?<br>*服装外贸企业数据通常分散在各业务员电脑和微信聊天中。"是每个人各管各的还是有统一地方?每天都有新数据还是周期性的?"* |
| 5 | 自动化诉求 | 有没有希望系统自动帮你做的事?在什么场景下触发?<br>*服装外贸常见自动化:订单状态变更自动通知、交货期临近提醒、生产进度自动汇总。"具体在什么条件下触发?触发后希望做什么?"* |
| 6 | 数据接入方式 | 数据怎么进到新表格里?<br>*常见方式:手动录入、表单填报、从现有系统自动同步、定期导入Excel。"是希望和现有系统打通自动同步,还是人工录入就行?"* |
| 7 | 使用者清单 | 谁来用这个表格?有没有外部人也要用?<br>*服装外贸常有外部协作方(工厂、货代、客户)需要查看或填写。"除了内部同事,工厂/客户/经销商需要看或填吗?"* |
| 8 | 权限隔离 | 数据需要按什么维度隔离?<br>*常见隔离方式:按人(销售只看自己的客户)、按部门、按区域、按角色。"具体谁不能看到谁的数据?"* |
| 9 | 仪表盘 | 最想看到什么业务指标?希望以什么维度展示?<br>*服装外贸常见指标:订单完成率、交货准时率、各工厂在制量、客户返单率。常见维度:按时间/按工厂/按业务员。"老板最关心哪个数字?"* |
| 10 | 交付预期 | 希望多久能用上?先上哪部分?预算大概多少?<br>*服装外贸客户通常希望1-2周内看到初版。"是一次性全部上线还是分阶段?有没有硬性时间节点?"* |
| 11 | 开放补充 | 还有什么想补充的吗?<br>*开放性问题,让客户补充前面没覆盖到的需求或顾虑。* |

**深挖问题**

| 序号 | 维度 | 提问 |
|------|------|------|
| 1 | 字段细节 | 核心环节需要记录哪些信息?<br>*服装外贸订单常见字段:客户名、款号、数量、交期、工厂、状态、备注。"每个环节需要填哪些信息?现在的表里有哪些列?"* |
| 2 | 表间关联 | 订单需不需要关联其他信息(客户、产品、工厂)?<br>*服装外贸常见关联:订单⇄客户、订单⇄款号/产品、订单⇄工厂。"是否需要分表管理还是全在一张表里?"* |
| 3 | 流转规则 | 数据从一个状态到下一个状态,有什么条件吗?<br>*服装外贸常见流转:客户确认后才能排产、质检通过才能发货。"是否需要审批?谁来审批?"* |
| 4 | 通知规则 | 什么情况下需要自动通知谁?<br>*服装外贸常见通知:交期临近提醒业务员、客户确认后通知工厂、异常告警通知主管。"通过企微消息还是其他方式?"* |

❗❗❗ 重要:以上是示例,实际输出必须根据客户的具体行业和需求来写,不要照抄示例。
"""


def _build_question_context(industry: str, initial_demand: str, direction: str):
    """构建知识库上下文供AI生成提问清单"""
    kb = load_global_knowledge()
    query = f"{industry} {direction} {initial_demand}".strip()

    # 1. 行业知识
    industry_lower = industry.lower()
    industry_text = ""
    for key, data in kb["industries"].items():
        tags = [t.lower() for t in data.get("tags", [])]
        name = data.get("industry_name", "").lower()
        if industry_lower in name or any(industry_lower in t or t in industry_lower for t in tags):
            content = data.get("content", "")
            industry_text = content[:500] if len(content) > 500 else content
            break

    # 2. 案例
    query_lower = query.lower()
    scored_cases = []
    for case in kb["cases"]:
        score = 0
        meta = case.get("meta", {})
        case_industry = meta.get("industry", "").lower()
        case_scene = meta.get("scene", "").lower()
        if case_industry in query_lower or query_lower in case_industry:
            score += 5
        if case_scene in query_lower:
            score += 3
        summary = case.get("demand_summary", "").lower()
        for word in re.split(r'[，,、。\s]+', query_lower):
            if len(word) >= 2 and word in summary:
                score += 2
        if score > 0:
            scored_cases.append((score, case))
    scored_cases.sort(key=lambda x: x[0], reverse=True)
    matched_cases = scored_cases[:3]

    case_context = ""
    for score, case in matched_cases:
        meta = case.get("meta", {})
        pain = case.get("pain_points", [])
        solution = case.get("solution", {})
        tables = solution.get("tables", [])
        comm_record = case.get("communication_record", "")
        comm_highlights = case.get("communication_highlights", [])

        case_context += f"### 真实交付案例:{meta.get('industry', '')} - {meta.get('scene', '')}\n"
        if pain:
            case_context += "客户原始痛点:\n"
            for p in pain:
                case_context += f"  - {p}\n"
        if solution.get("architecture"):
            case_context += f"最终方案:{solution['architecture']}\n"
        if tables:
            case_context += "方案包含的子表和字段:\n"
            for t in tables[:6]:
                tname = t.get("table_name", "")
                fields = t.get("fields", [])
                field_names = []
                for f in fields[:15]:
                    if isinstance(f, str):
                        field_names.append(f)
                    elif isinstance(f, dict):
                        field_names.append(f.get("field_title", f.get("title", "")))
                case_context += f"  表「{tname}」: {', '.join(field_names)}\n"
        if solution.get("automation_rules"):
            case_context += f"自动化规则: {', '.join(solution['automation_rules'][:5])}\n"
        if comm_record:
            case_context += f"沟通记录:{comm_record}\n"
        if comm_highlights:
            case_context += "沟通确认关键点:\n"
            for h in comm_highlights[:5]:
                case_context += f"  - {h}\n"
        case_context += "\n"

    # 3. 字段模板
    tpl_context = ""
    scored_templates = []
    for tpl in kb["templates"]:
        score = 0
        meta = tpl.get("meta", {})
        tpl_industry = meta.get("industry", "").lower()
        applicable = meta.get("applicable_when", "").lower()
        if tpl_industry in query_lower:
            score += 5
        for word in re.split(r'[，,、。/\s]+', applicable):
            if len(word) >= 2 and word in query_lower:
                score += 2
        if score >= 4:
            scored_templates.append((score, tpl))
    scored_templates.sort(key=lambda x: x[0], reverse=True)
    if scored_templates:
        tpl = scored_templates[0][1]
        meta = tpl.get("meta", {})
        tpl_context = f"### 字段经验池:{meta.get('industry', '')} - {meta.get('scene', '')}\n"
        tpl_context += f"该行业真实交付过{meta.get('total_tables', '?')}张表,{meta.get('total_fields', '?')}个字段\n"
        if meta.get("design_principle"):
            tpl_context += f"设计原则:{meta['design_principle']}\n"
        for table in tpl.get("tables", [])[:8]:
            tpl_context += f"  表「{table.get('table_name', '')}」:\n"
            for g in table.get("field_groups", [])[:5]:
                gname = g.get("group_name", "")
                fields = [f.get("title", "") for f in g.get("fields", [])[:8]]
                tpl_context += f"    [{gname}] {', '.join(fields)}\n"

    return {
        "industry_knowledge": industry_text,
        "case_context": case_context.strip(),
        "template_context": tpl_context.strip()
    }


@app.post("/api/question_list")
async def generate_question_list(body: dict, user: dict = Depends(require_auth)):
    """生成智能提问清单"""
    industry = body.get("industry", "")
    initial_demand = body.get("initial_demand", "")
    company_intro = body.get("company_intro", "")
    direction = body.get("direction", "")

    if not industry:
        raise HTTPException(status_code=400, detail="industry is required")

    # 构建上下文
    context = _build_question_context(industry, initial_demand, direction)

    # 组装用户prompt
    user_prompt = "## 客户信息\n"
    user_prompt += f"- 行业:{industry}\n"
    if company_intro:
        user_prompt += f"- 公司简介:{company_intro}\n"
    if initial_demand:
        user_prompt += f"- 客户初始需求表达:{initial_demand}\n"

    if context["industry_knowledge"]:
        user_prompt += f"\n## 行业背景知识\n{context['industry_knowledge']}\n"
    if context["case_context"]:
        user_prompt += f"\n## 相关交付案例\n{context['case_context']}\n"
    if context["template_context"]:
        user_prompt += f"\n## 字段经验池参考\n{context['template_context']}\n"

    user_prompt += "\n请严格按PART1-PART3的结构输出调研准备材料。PART1公司背景要先用一段自然的话介绍这家公司(基于客户提供的信息和你对该行业的认知来描述,像给服务商介绍客户一样,不要像填表),然后用几个要点补充行业现状、涉及角色和环节、需要考虑的事项。PART2简洁。PART3提问清单严格11个必问问题+3-5个深挖问题,用Markdown表格格式(序号|维度|提问),每个问题后用<br>换行加斜体小字(先说行业常见情况,再给追问句子,不要加任何前缀标签)。"

    result = call_deepseek(QUESTION_LIST_SYSTEM_PROMPT, user_prompt, max_tokens=3000)
    # 解析Markdown格式的回复,转换为JSON
    import json, re
    parsed = parse_markdown_to_json(result)
    return {
        "result": parsed,
        "context_used": {
            "industry_matched": bool(context["industry_knowledge"]),
            "cases_matched": bool(context["case_context"]),
            "template_matched": bool(context["template_context"])
        }
    }


def parse_markdown_to_json(markdown_text):
    """解析Markdown格式的调研准备材料为JSON"""
    import re
    result = {
        "part1": {
            "company_background": "",
            "pain_points": []
        },
        "part2": [],
        "part3": {
            "must_ask": [],
            "deep_dive": [],
            "industry_experience": []
        }
    }

    # 解析 PART1 公司背景
    part1_match = re.search(r'\*\*公司与需求背景\*\*(.*?)(?=\*\*行业常见痛点|\*\*PART2|\- 🔥)', markdown_text, re.DOTALL)
    if part1_match:
        bg_text = part1_match.group(1).strip()
        # 提取 bullet points
        bullets = re.findall(r'^- (.+)$', bg_text, re.MULTILINE)
        if bullets:
            result["part1"]["company_background"] = '\n'.join(['- ' + b for b in bullets])
        else:
            result["part1"]["company_background"] = bg_text

    # 解析行业痛点
    pain_match = re.search(r'\*\*行业常见痛点\*\*(.*?)(?=\*\*PART2|\*\*PART3|### |\Z)', markdown_text, re.DOTALL)
    if pain_match:
        pain_text = pain_match.group(1)
        pains = re.findall(r'- 🔥 (.+)', pain_text)
        if not pains:
            pains = re.findall(r'- (.+)', pain_text)
        # 去除末尾标点符号（。．.）
        pains = [re.sub(r'[。．.。]+$', '', p).strip() for p in pains]
        result["part1"]["pain_points"] = pains

    # 解析 PART2 信息缺口（支持 ### PART2 和 **PART2 两种格式）
    part2_match = re.search(r'(?:### PART2.*?信息缺口|\*\*PART2.*?信息缺口\*\*)\s*(.*?)(?=\n### |\n\*\*PART3|## 三、|\Z)', markdown_text, re.DOTALL)
    if part2_match:
        gap_text = part2_match.group(1)
        gaps = re.findall(r'- ❓ (.+)', gap_text)
        if not gaps:
            gaps = re.findall(r'❓ (.+)', gap_text)
        for g in gaps:
            result["part2"].append({"gap": g.strip(), "priority": "高"})

    # 解析必问问题表格
    must_section = re.search(r'\*\*必问问题\*\*.*?(?=\*\*深挖问题|\*\*PART3|### |\Z)', markdown_text, re.DOTALL)
    if must_section:
        must_text = must_section.group(0)
        # 解析表格行
        rows = re.findall(r'\|[^|]+\|[^|]+\|[^|]+\|', must_text)
        for row in rows:
            cols = [c.strip() for c in row.split('|')[1:-1]]
            if len(cols) >= 3 and cols[0].isdigit():
                # 提取问题(第一行)和斜体部分(第二行,<br>后)
                q_text = cols[2].split('<br>')[0].strip() if '<br>' in cols[2] else cols[2].strip()
                note_text = ''
                if '<br>' in cols[2]:
                    note_match = re.search(r'<br>\*(.+?)\*', cols[2])
                    if note_match:
                        note_text = note_match.group(1).strip()
                result["part3"]["must_ask"].append({
                    "dimension": cols[1],
                    "question": q_text,
                    "note": note_text
                })

    # 解析深挖问题表格
    deep_section = re.search(r'\*\*深挖问题\*\*.*?(?=\*\*行业经验|### |\Z)', markdown_text, re.DOTALL | re.IGNORECASE)
    if deep_section:
        deep_text = deep_section.group(0)
        rows = re.findall(r'\|[^|]+\|[^|]+\|[^|]+\|', deep_text)
        for row in rows:
            cols = [c.strip() for c in row.split('|')[1:-1]]
            if len(cols) >= 3 and cols[0].isdigit():
                q_text = cols[2].split('<br>')[0].strip() if '<br>' in cols[2] else cols[2].strip()
                note_text = ''
                if '<br>' in cols[2]:
                    note_match = re.search(r'<br>\*(.+?)\*', cols[2])
                    if note_match:
                        note_text = note_match.group(1).strip()
                result["part3"]["deep_dive"].append({
                    "dimension": cols[1],
                    "question": q_text,
                    "note": note_text
                })

    return result


def parse_report_markdown_to_json(markdown_text):
    """解析Markdown格式的需求分析报告为JSON"""
    import re
    result = {
        "customer_info": {
            "industry": "",
            "scale": "",
            "direction": ""
        },
        "core_pain_points": [],
        "business_scenario": {
            "core_flow": "",
            "roles": [],
            "data_flow": ""
        },
        "solution": {
            "sub_tables": [],
            "automation_rules": [],
            "views": [],
            "permissions": []
        },
        "delivery_schedule": "",
        "pending_items": []
    }

    # 解析客户信息
    info_section = re.search(r'## 客户信息\s*\n(.*?)(?=\n## |\n# |\Z)', markdown_text, re.DOTALL)
    if info_section:
        info_text = info_section.group(1)
        industry_match = re.search(r'- 行业：(.+)', info_text)
        if industry_match:
            result["customer_info"]["industry"] = industry_match.group(1).strip()
        scale_match = re.search(r'- 规模：(.+)', info_text)
        if scale_match:
            result["customer_info"]["scale"] = scale_match.group(1).strip()
        dir_match = re.search(r'- 需求方向：(.+)', info_text)
        if dir_match:
            result["customer_info"]["direction"] = dir_match.group(1).strip()

    # 解析核心痛点
    pain_section = re.search(r'## 核心痛点\s*\n(.*?)(?=\n## |\n# |\Z)', markdown_text, re.DOTALL)
    if pain_section:
        pain_text = pain_section.group(1)
        # 匹配 1. **痛点名称**："客户原话引用" 格式
        pain_blocks = re.findall(r'\d+\.\s*\*\*(.+?)\*\*[："](.+?)["\s]', pain_text)
        for name, quote in pain_blocks:
            result["core_pain_points"].append({
                "point": f"{name.strip()}：{quote.strip()}",
                "priority": "高"
            })
        # 备选：匹配 - xxx 格式
        if not result["core_pain_points"]:
            pains = re.findall(r'- (.+)', pain_text)
            for p in pains:
                p = p.strip()
                if p:
                    result["core_pain_points"].append({
                        "point": re.sub(r'[。．.。]+$', '', p).strip(),
                        "priority": "高"
                    })

    # 解析业务场景
    scene_section = re.search(r'## 业务场景\s*\n(.*?)(?=\n## |\n# |\Z)', markdown_text, re.DOTALL)
    if scene_section:
        scene_text = scene_section.group(1)
        flow_match = re.search(r'- 核心流程：(.+)', scene_text)
        if flow_match:
            result["business_scenario"]["core_flow"] = flow_match.group(1).strip()
        roles_match = re.search(r'- 涉及角色：(.+)', scene_text)
        if roles_match:
            roles_text = roles_match.group(1).strip()
            # 分割角色列表
            roles = re.split(r'[、，,]', roles_text)
            result["business_scenario"]["roles"] = [r.strip() for r in roles if r.strip()]
        data_match = re.search(r'- 数据流向：(.+)', scene_text)
        if data_match:
            result["business_scenario"]["data_flow"] = data_match.group(1).strip()

    # 解析智能表格搭建方案 - 子表结构
    solution_section = re.search(r'## 智能表格搭建方案\s*\n(.*?)(?=\n## |\n# |\Z)', markdown_text, re.DOTALL)
    if solution_section:
        sol_text = solution_section.group(1)

        # 解析子表表格
        table_match = re.search(r'\| 子表名称[ |\-]+\|.*?\n\|[-| ]+\|.*?\n((?:\|.+\|[\n]?)+)', sol_text, re.DOTALL)
        if table_match:
            table_lines = table_match.group(1).strip().split('\n')
            for line in table_lines:
                cols = [c.strip() for c in line.split('|')[1:-1]]
                if len(cols) >= 4 and cols[0]:
                    fields_str = re.sub(r'[`*]', '', cols[2]) if len(cols) > 2 else ''
                    fields = [f.strip() for f in re.split(r'[、，]', fields_str) if f.strip()]
                    result["solution"]["sub_tables"].append({
                        "name": cols[0],
                        "purpose": cols[1] if len(cols) > 1 else '',
                        "fields": fields[:8],
                        "primary_role": cols[3] if len(cols) > 3 else ''
                    })

        # 解析自动化规则
        rules_section = re.search(r'### 自动化规则\s*\n(.*?)(?=\n### |\n## |\Z)', sol_text, re.DOTALL)
        if rules_section:
            rules_text = rules_section.group(1)
            rules = re.findall(r'\d+\.\s*(?:当.+?时\s*→\s*.+|.+)', rules_text)
            for r in rules:
                r = r.strip()
                if r:
                    clean = re.sub(r'^\d+\.\s*', '', r)
                    result["solution"]["automation_rules"].append(clean)

        # 解析推荐视图
        views_section = re.search(r'### 推荐视图\s*\n(.*?)(?=\n### |\n## |\Z)', sol_text, re.DOTALL)
        if views_section:
            views_text = views_section.group(1)
            views = re.findall(r'- .+?：.+', views_text)
            for v in views:
                v = v.strip()
                if v:
                    result["solution"]["views"].append(re.sub(r'^[^-]+-\s*', '', v))

        # 解析权限设计
        perms_section = re.search(r'### 权限设计\s*\n(.*?)(?=\n### |\n## |\Z)', sol_text, re.DOTALL)
        if perms_section:
            perms_text = perms_section.group(1)
            perms = re.findall(r'- .+', perms_text)
            for p in perms:
                p = p.strip()
                if p:
                    result["solution"]["permissions"].append(re.sub(r'^[^-]+-\s*', '', p))

    # 解析预估交付周期
    schedule_section = re.search(r'## 预估交付周期\s*\n(.*?)(?=\n## |\n# |\Z)', markdown_text, re.DOTALL)
    if schedule_section:
        result["delivery_schedule"] = schedule_section.group(1).strip()

    # 解析待确认事项
    pending_section = re.search(r'## 待确认事项\s*\n(.*?)(?=\n## |\n# |\Z)', markdown_text, re.DOTALL)
    if pending_section:
        pending_text = pending_section.group(1)
        items = re.findall(r'[❓\?•\-]\s*(.+)', pending_text)
        for item in items:
            item = item.strip()
            if item:
                result["pending_items"].append(item)

    return result


@app.post("/api/deepseek")
async def deepseek_proxy(body: dict, user: dict = Depends(require_auth)):
    """DeepSeek API 代理 - 统一调用入口"""
    system_prompt = body.get("system_prompt", "")
    user_prompt = body.get("user_prompt", "")
    max_tokens = body.get("max_tokens", 4000)

    if not system_prompt or not user_prompt:
        raise HTTPException(status_code=400, detail="system_prompt and user_prompt are required")

    result = call_deepseek(system_prompt, user_prompt, max_tokens=max_tokens)
    return {"result": result}


# ==================== 知识库匹配 ====================

@app.post("/api/match")
async def match_knowledge(body: dict, user: dict = Depends(require_auth)):
    """知识库匹配（Step2报告生成用）"""
    industry = body.get("industry", "")
    direction = body.get("direction", "")
    query = f"{industry} {direction}".strip()

    kb = load_global_knowledge()

    # 匹配行业
    industry_lower = industry.lower()
    industry_text = ""
    for key, data in kb["industries"].items():
        tags = [t.lower() for t in data.get("tags", [])]
        name = data.get("industry_name", "").lower()
        if industry_lower in name or any(industry_lower in t or t in industry_lower for t in tags):
            content = data.get("content", "")
            industry_text = content[:3000] if len(content) > 3000 else content
            break

    # 匹配案例
    query_lower = query.lower()
    scored_cases = []
    for case in kb["cases"]:
        score = 0
        meta = case.get("meta", {})
        case_industry = meta.get("industry", "").lower()
        case_scene = meta.get("scene", "").lower()
        if case_industry in query_lower or query_lower in case_industry:
            score += 5
        else:
            for word in re.split(r'[，,、。/\s]+', query_lower):
                if len(word) >= 2 and word in case_industry:
                    score += 4
                    break
        if case_scene in query_lower:
            score += 3
        if score > 0:
            scored_cases.append((score, case))
    scored_cases.sort(key=lambda x: x[0], reverse=True)
    matched_cases = [c for _, c in scored_cases[:3]]

    # 匹配模板
    scored_templates = []
    for tpl in kb["templates"]:
        score = 0
        meta = tpl.get("meta", {})
        tpl_industry = meta.get("industry", "").lower()
        applicable = meta.get("applicable_when", "").lower()
        if tpl_industry in query_lower:
            score += 5
        for word in re.split(r'[，,、。/\s]+', applicable):
            if len(word) >= 2 and word in query_lower:
                score += 2
        if score >= 4:
            scored_templates.append((score, tpl))
    scored_templates.sort(key=lambda x: x[0], reverse=True)
    matched_templates = [t for _, t in scored_templates[:2]]

    return {
        "industry_knowledge": industry_text,
        "matched_cases": matched_cases,
        "matched_templates": matched_templates,
        "matched": bool(industry_text or matched_cases or matched_templates)
    }


# ==================== 企微文档导出 ====================

@app.post("/api/export_doc")
async def export_wecom_doc(body: dict, user: dict = Depends(require_auth)):
    """创建企微文档"""
    title = body.get("title", "服务商助手文档")
    content = body.get("content", "")

    if not content:
        raise HTTPException(status_code=400, detail="content is required")

    # 1. 创建文档
    r = extract_mcp(call_mcp("create_doc", {"doc_type": 3, "doc_name": title}))
    if not r or (isinstance(r, dict) and r.get("errcode", 0) != 0):
        return {"success": False, "error": f"创建文档失败: {r.get('errmsg', '') if isinstance(r, dict) else str(r)}"}

    docid = r.get("docid") if isinstance(r, dict) else None
    url = r.get("url") if isinstance(r, dict) else None

    if not docid:
        return {"success": False, "error": "未获取到文档ID"}

    # 2. 写入内容
    try:
        call_mcp("edit_doc_content", {
            "docid": docid,
            "content": content,
            "content_type": 1
        })
    except Exception:
        pass  # 文档已创建,忽略写入失败

    return {"success": True, "docid": docid, "url": url, "title": title}


# ==================== 文件上传解析 ====================

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), user: dict = Depends(require_auth)):
    """解析上传的文件(.docx/.txt)"""
    import base64
    import zipfile
    import io

    filename = file.filename
    content = await file.read()

    extracted_text = ""

    if filename.endswith(".docx"):
        try:
            zf = zipfile.ZipFile(io.BytesIO(content))
            xml_content = zf.read("word/document.xml").decode("utf-8")
            texts = re.findall(r'<w:t[^>]*>(.*?)</w:t>', xml_content)
            paragraphs = re.findall(r'<w:p[^>]*>(.*?)</w:p>', xml_content, re.DOTALL)
            result = []
            for para in paragraphs:
                para_texts = re.findall(r'<w:t[^>]*>(.*?)</w:t>', para)
                if para_texts:
                    result.append("".join(para_texts))
            extracted_text = "\n".join(result) if result else "\n".join(texts)
        except Exception as e:
            extracted_text = f"[docx解析失败: {str(e)}]"
    elif filename.endswith(".txt"):
        try:
            extracted_text = content.decode("utf-8")
        except:
            try:
                extracted_text = content.decode("gbk")
            except:
                extracted_text = content.decode("utf-8", errors="ignore")
    else:
        extracted_text = content.decode("utf-8", errors="ignore")

    if not extracted_text:
        raise HTTPException(status_code=400, detail="无法解析文件内容")

    return {
        "text": extracted_text,
        "filename": filename,
        "char_count": len(extracted_text)
    }

ADMIN_DOC_ID = "dc_bZyjyIOKIjKHoMi-VenuLgp7VE_ewIkFQAkKchu23cPN2eGaM6Rjs3dpnZSFPg93IEeXW8ucr4Ee7NBXv7SvQ"
SHEET_CLIENTS = "q979lj"
SHEET_RECORDS = "1abkq2"


@app.post("/api/report")
async def report_to_admin(body: dict, user: dict = Depends(require_auth)):
    """上报数据到平台管理表"""
    action = body.get("action", "report_client")

    if action == "report_client":
        provider = body.get("provider_name", "")
        client = body.get("client_name", "")
        record_id = body.get("record_id", "")

        values = {
            "服务商": [{"type": "text", "text": provider}],
            "客户名称": [{"type": "text", "text": client}],
            "客户行业": [{"type": "text", "text": body.get("industry", "")}],
            "本次定制开发业务概述": [{"type": "text", "text": body.get("business_desc", "")[:500]}],
            "本次定制开发需要智能表格解决的痛点": [{"type": "text", "text": body.get("pain_points", "")[:500]}],
        }
        status = body.get("status", "")
        if status:
            values["当前状态"] = [{"text": status}]

        def clean_url(url):
            if not url:
                return ""
            if "?scode=" in url:
                url = url.split("?scode=")[0]
            elif "&scode=" in url:
                url = url.split("&scode=")[0]
            return url

        step1_url = clean_url(body.get("step1_doc_url", ""))
        if step1_url:
            values["提问清单链接"] = [{"type": "url", "link": step1_url, "text": "提问清单"}]
        report_url = clean_url(body.get("report_doc_url", ""))
        if report_url:
            values["需求报告链接"] = [{"type": "url", "link": report_url, "text": "需求报告"}]
        demo_url = clean_url(body.get("demo_url", ""))
        if demo_url:
            values["Demo链接"] = [{"type": "url", "link": demo_url, "text": "Demo"}]

        try:
            if record_id:
                r = extract_mcp(call_mcp("smartsheet_update_records", {
                    "docid": ADMIN_DOC_ID,
                    "sheet_id": SHEET_CLIENTS,
                    "records": [{"record_id": record_id, "values": values}]
                }))
            else:
                r = extract_mcp(call_mcp("smartsheet_add_records", {
                    "docid": ADMIN_DOC_ID,
                    "sheet_id": SHEET_CLIENTS,
                    "records": [{"values": values}]
                }))
                if isinstance(r, dict) and r.get("records"):
                    record_id = r["records"][0].get("record_id", "")
            return {"success": True, "record_id": record_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif action == "report_transcript":
        transcript = body.get("transcript", "")
        provider_name = body.get("provider_name", "")
        client_name = body.get("client_name", "")
        industry = body.get("industry", "")
        doc_url = ""

        if transcript:
            try:
                doc_title = f"{client_name} - 沟通记录"
                r = extract_mcp(call_mcp("create_doc", {"doc_type": 3, "doc_name": doc_title}))
                if r and isinstance(r, dict) and r.get("errcode", 0) == 0:
                    docid = r.get("docid", "")
                    doc_url = r.get("url", "")
                    content = f"# {client_name} 沟通记录\n\n- 服务商：{provider_name}\n- 行业：{industry}\n\n---\n\n" + transcript
                    call_mcp("edit_doc_content", {"docid": docid, "content": content, "content_type": 1})
            except:
                pass

        values = {
            "服务商": [{"type": "text", "text": provider_name}],
            "客户名称": [{"type": "text", "text": client_name}],
            "客户行业": [{"type": "text", "text": industry}],
            "沟通内容": [{"type": "text", "text": transcript[:500] + ("..." if len(transcript) > 500 else "")}],
            "内容长度": len(transcript) if transcript else 0
        }
        if doc_url:
            values["文档链接"] = [{"type": "url", "link": doc_url, "text": "查看文档"}]

        try:
            call_mcp("smartsheet_add_records", {
                "docid": ADMIN_DOC_ID,
                "sheet_id": SHEET_RECORDS,
                "records": [{"values": values}]
            })
            return {"success": True, "doc_url": doc_url}
        except Exception as e:
            return {"success": False, "error": str(e), "doc_url": doc_url}

    else:
        return {"error": "Unknown action"}


# ==================== 公司信息搜索 ====================

@app.post("/api/company_search")
async def search_company(body: dict, user: dict = Depends(require_auth)):
    """通过AI生成公司简介"""
    company_name = body.get("company_name", "").strip()
    industry = body.get("industry", "").strip()

    if not company_name:
        raise HTTPException(status_code=400, detail="company_name is required")

    system_prompt = """你是一个企业信息助手。根据公司名称和行业，输出一段JSON格式的信息。

## 输出格式（直接输出JSON，不要任何Markdown包裹）
{
  "company_type": "客户类型，如：金融通讯技术服务商、B2B工业品贸易商、制造业中小企业等",
  "main_customers": "主要客户群体，用 / 分隔，如：银行/证券/保险、制造型企业/中间商",
  "possible_focus": "可能关注的重点，用 / 分隔，如：合规留痕、审批协同、项目进度管理",
  "company_intro": "公司简介段落，3-5句话，保持客观简洁"
}

## 规则
- company_type 控制在10字以内，简短定性
- main_customers 列出该行业客户最典型的2-4类，不要罗列太多
- possible_focus 列出该行业客户最可能关心的2-4个需求点
- company_intro 3-5句话，像了解这个行业的人在介绍客户
"""
    user_prompt = f"公司名称:{company_name}\n行业:{industry}\n\n请输出JSON格式的客户信息分析:"
    import json, re
    result = call_deepseek(system_prompt, user_prompt, max_tokens=300)
    try:
        # 尝试从 markdown 代码块中提取 JSON
        json_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', result)
        if json_match:
            result = json_match.group(1)
        parsed = json.loads(result.strip())
    except Exception:
        parsed = {"company_intro": result.strip()}
    return parsed


# ==================== 创建企微智能表格(增强版) ====================

def _normalize_field_type(ft: str) -> str:
    """确保 field_type 带有 FIELD_TYPE_ 前缀"""
    if not ft:
        return "FIELD_TYPE_TEXT"
    ft = ft.strip().upper()
    if not ft.startswith("FIELD_TYPE_"):
        ft = "FIELD_TYPE_" + ft
    alias_map = {
        "FIELD_TYPE_DATE": "FIELD_TYPE_DATE_TIME",
        "FIELD_TYPE_DATETIME": "FIELD_TYPE_DATE_TIME",
        "FIELD_TYPE_SELECT": "FIELD_TYPE_SINGLE_SELECT",
        "FIELD_TYPE_MULTISELECT": "FIELD_TYPE_MULTI_SELECT",
        "FIELD_TYPE_MULTI": "FIELD_TYPE_MULTI_SELECT",
        "FIELD_TYPE_PHONE": "FIELD_TYPE_PHONE_NUMBER",
        "FIELD_TYPE_TEL": "FIELD_TYPE_PHONE_NUMBER",
        "FIELD_TYPE_LINK": "FIELD_TYPE_URL",
        "FIELD_TYPE_MONEY": "FIELD_TYPE_CURRENCY",
        "FIELD_TYPE_AMOUNT": "FIELD_TYPE_CURRENCY",
        "FIELD_TYPE_PERCENT": "FIELD_TYPE_PERCENTAGE",
        "FIELD_TYPE_NUM": "FIELD_TYPE_NUMBER",
        "FIELD_TYPE_INT": "FIELD_TYPE_NUMBER",
        "FIELD_TYPE_BOOL": "FIELD_TYPE_CHECKBOX",
        "FIELD_TYPE_BOOLEAN": "FIELD_TYPE_CHECKBOX",
    }
    ft = alias_map.get(ft, ft)
    valid_types = {
        "FIELD_TYPE_TEXT", "FIELD_TYPE_NUMBER", "FIELD_TYPE_SINGLE_SELECT",
        "FIELD_TYPE_MULTI_SELECT", "FIELD_TYPE_DATE_TIME", "FIELD_TYPE_CHECKBOX",
        "FIELD_TYPE_USER", "FIELD_TYPE_PHONE_NUMBER", "FIELD_TYPE_EMAIL",
        "FIELD_TYPE_URL", "FIELD_TYPE_CURRENCY", "FIELD_TYPE_PERCENTAGE",
        "FIELD_TYPE_PROGRESS", "FIELD_TYPE_AUTO_NUMBER", "FIELD_TYPE_LOCATION",
        "FIELD_TYPE_CREATED_TIME", "FIELD_TYPE_MODIFIED_TIME",
        "FIELD_TYPE_CREATED_USER", "FIELD_TYPE_MODIFIED_USER",
        "FIELD_TYPE_BARCODE", "FIELD_TYPE_RATING",
    }
    if ft not in valid_types:
        return "FIELD_TYPE_TEXT"
    return ft


@app.post("/api/create")
async def create_wecom_doc(body: dict, user: dict = Depends(require_auth)):
    """创建企微智能表格或文档"""
    # 分流：如果有 docid + sheet，是追加子表；否则是创建新文档
    docid = body.get("docid")
    sheet = body.get("sheet")

    if docid and sheet:
        # 追加子表
        sname = sheet.get("sheet_name", "子表")
        fields = sheet.get("fields", [])
        records = sheet.get("sample_records", [])

        sr2 = extract_mcp(call_mcp("smartsheet_add_sheet", {"docid": docid, "title": sname}))
        sid = None
        if isinstance(sr2, dict):
            sid = sr2.get("sheet_id") or (sr2.get("properties", {}) or {}).get("sheet_id")
        if not sid:
            return {"success": False, "error": f"子表「{sname}」创建失败"}

        call_mcp("smartsheet_update_sheet", {
            "docid": docid, "sheet_id": sid,
            "properties": {"sheet_id": sid, "title": sname}
        })

        # 配置字段
        fr = extract_mcp(call_mcp("smartsheet_get_fields", {"docid": docid, "sheet_id": sid}))
        dfid = None
        if isinstance(fr, dict):
            fl = fr.get("fields", [])
            if fl:
                dfid = fl[0].get("field_id")

        if fields and dfid:
            call_mcp("smartsheet_update_fields", {
                "docid": docid, "sheet_id": sid,
                "fields": [{"field_id": dfid, "field_title": fields[0]["field_title"], "field_type": _normalize_field_type(fields[0].get("field_type", "TEXT"))}]
            })
            remaining = fields[1:]
            if remaining:
                call_mcp("smartsheet_add_fields", {
                    "docid": docid, "sheet_id": sid,
                    "fields": [{"field_title": f["field_title"], "field_type": _normalize_field_type(f.get("field_type", "TEXT"))} for f in remaining]
                })

        # 添加记录
        if records:
            cf = extract_mcp(call_mcp("smartsheet_get_fields", {"docid": docid, "sheet_id": sid}))
            fmap = {}
            if isinstance(cf, dict):
                for f in cf.get("fields", []):
                    fmap[f["field_title"]] = f

            fmtd = []
            for rec in records:
                vals = {}
                for k, v in rec.items():
                    if k not in fmap:
                        continue
                    ft = fmap[k].get("field_type", "FIELD_TYPE_TEXT")
                    if ft == "FIELD_TYPE_TEXT":
                        vals[k] = [{"type": "text", "text": str(v)}]
                    elif ft in ("FIELD_TYPE_NUMBER", "FIELD_TYPE_CURRENCY", "FIELD_TYPE_PERCENTAGE", "FIELD_TYPE_PROGRESS"):
                        try:
                            vals[k] = float(v)
                        except:
                            vals[k] = [{"type": "text", "text": str(v)}]
                    elif ft == "FIELD_TYPE_SINGLE_SELECT":
                        vals[k] = [{"text": str(v)}]
                    elif ft == "FIELD_TYPE_DATE_TIME":
                        vals[k] = str(v)
                    elif ft == "FIELD_TYPE_CHECKBOX":
                        vals[k] = bool(v)
                    else:
                        vals[k] = [{"type": "text", "text": str(v)}]
                fmtd.append({"values": vals})

            if fmtd:
                call_mcp("smartsheet_add_records", {"docid": docid, "sheet_id": sid, "records": fmtd})

        return {"success": True, "sheet_name": sname, "sheet_id": sid}

    else:
        # 创建智能文档（smartpage）
        doc_name = body.get("doc_name", "需求调研文档")
        # 如果直接提供了 content，直接使用；否则从 sheets 构建
        content = body.get("content", "")
        if not content:
            sheets = body.get("sheets", [])
            content_lines = ["# " + doc_name, "## 客户画像"]
            for s in sheets:
                sname = s.get("sheet_name", "子表")
                content_lines.append("### " + sname)
                fields = s.get("fields", [])
                records = s.get("sample_records", [])
                if fields:
                    field_titles = [f.get("field_title", "") for f in fields]
                    content_lines.append("字段: " + "、".join(field_titles))
                if records:
                    for rec in records:
                        row_vals = []
                        for f in fields:
                            val = rec.get(f.get("field_title", ""), "-")
                            row_vals.append(val)
                        content_lines.append("| " + " | ".join(row_vals) + " |")
            content = "\n\n".join(content_lines)

        # 记录 content 长度用于调试
        import logging
        logging.warning(f"[smartpage_create] doc_name={doc_name}, content_len={len(content)}, content_preview={content[:200]}")

        # 使用 smartpage_create 创建智能文档
        r = extract_mcp(call_mcp("smartpage_create", {
            "title": doc_name,
            "pages": [{"title": "客户画像", "content": content}]
        }))
        if not r or (isinstance(r, dict) and r.get("errcode", 0) != 0):
            return {"success": False, "error": "创建文档失败", "detail": str(r)}

        docid = r.get("docid") if isinstance(r, dict) else None
        url = r.get("url") if isinstance(r, dict) else None
        if not docid:
            return {"success": False, "error": "未获取 docid"}

        return {"success": True, "doc_name": doc_name, "docid": docid, "url": url, "sheets": []}


# ==================== Step3 沟通摘要生成 ====================

SUMMARY_SYSTEM_PROMPT = """你是一个专业的售前沟通记录分析助手。根据服务商的多次沟通记录，生成结构化的摘要报告。

## 输出格式（严格按以下结构输出，直接输出 JSON，不要任何开场白）

{
  "key_requirements": ["要点1", "要点2", ...],        // 关键需求汇总
  "roles_and_responsibilities": [                    // 角色和职责
    {"role": "角色名", "responsibility": "职责描述", "concern": "关心什么"}
  ],
  "decision_chain": {                                // 决策链
    "decision_maker": "拍板人",
    "influencer": "影响者",
    "executor": "执行者"
  },
  "progress_and_stages": {                           // 进度和阶段
    "current_stage": "当前阶段",
    "next_steps": ["下一步1", "下一步2"],
    "milestones": ["里程碑1", "里程碑2"]
  },
  "risk_points": [                                   // 风险点
    {"risk": "风险描述", "status": "待确认/已明确"}
  }
}

## 要求
1. 从沟通记录中提取所有关键需求，每个需求用一句话描述
2. 角色要明确区分：决策者（拍板）、影响者（提意见）、执行者（具体干活）
3. 风险点必须是客户提到但没说清楚的地方
4. 直接输出有效 JSON，不要 markdown 代码块包裹"""


@app.post("/api/summary/generate")
async def generate_summary(body: dict, user: dict = Depends(require_auth)):
    """生成沟通记录摘要"""
    records = body.get("records", [])  # 沟通记录列表，每条包含 text, source, stage, date

    if not records:
        raise HTTPException(status_code=400, detail="沟通记录不能为空")

    # 构建用户 prompt
    records_text = "\n\n".join([
        f"【记录{i+1}】来源：{r.get('source','未知')} | 阶段：{r.get('stage','未知')} | 日期：{r.get('date','')}\n{r.get('text','')}"
        for i, r in enumerate(records)
    ])

    user_prompt = f"""## 沟通记录（共 {len(records)} 条）

{records_text}

请分析以上沟通记录，生成结构化的摘要报告。"""

    result = call_deepseek(SUMMARY_SYSTEM_PROMPT, user_prompt, max_tokens=3000)

    # 解析 JSON
    import json, re
    try:
        # 尝试直接解析
        summary = json.loads(result)
    except:
        # 尝试从 markdown 代码块中提取
        m = re.search(r'```(?:json)?\s*([\s\S]*?)```', result)
        if m:
            try:
                summary = json.loads(m.group(1).strip())
            except:
                summary = None
        else:
            summary = None

    if not summary:
        return {"success": False, "error": "AI 返回格式异常", "raw": result[:500]}

    return {"success": True, "summary": summary}


# ==================== Step5 Agent Demo H5 生成 ====================

AGENT_DEMO_SYSTEM_PROMPT = """你是一个专业的 H5 页面生成助手。根据客户需求分析报告，生成一个独立的、可直接在浏览器中运行的 HTML5 页面。

## 输出要求
1. 生成完整的 HTML 文件，包含所有 CSS/JS 内联代码
2. 页面必须是响应式的，支持手机和 PC
3. 页面内容要基于客户真实需求定制
4. 直接输出 HTML 代码，不要 markdown 代码块包裹

## 页面结构要求
- 顶部：客户名称 + Logo
- 主要内容区：根据需求分析展示关键信息（角色卡片、流程步骤、风险点等）
- 对话模拟区：模拟 AI 助手与用户的对话场景
- 底部：服务商信息

## 技术要求
- 使用纯 HTML + CSS + JavaScript（无外部依赖）
- 使用 CSS 变量管理颜色主题
- 页面加载后有基础的动画效果
- 支持滚动和基础交互"""


@app.post("/api/agent-demo/create")
async def create_agent_demo(body: dict, user: dict = Depends(require_auth)):
    """生成 Agent Demo H5 页面"""
    client_data = body.get("client_data", {})

    # 构建用户 prompt
    client_name = client_data.get("name", "未知客户")
    industry = client_data.get("industry", "")
    step4_report = client_data.get("step4_report", {})
    step1_result = client_data.get("step1_result", {})

    user_prompt = f"""## 客户信息
- 客户名称：{client_name}
- 行业：{industry}

## 需求分析报告摘要
{json.dumps(step4_report, ensure_ascii=False, indent=2) if step4_report else '暂无'}

## 客户画像摘要
{json.dumps(step1_result, ensure_ascii=False, indent=2) if step1_result else '暂无'}

请基于以上信息，生成一个展示 AI 售前助手能力的 H5 页面。"""

    result = call_deepseek(AGENT_DEMO_SYSTEM_PROMPT, user_prompt, max_tokens=8000)

    # 保存到 public 目录
    import uuid, os
    from pathlib import Path

    # 确保 public 目录存在
    public_dir = Path(__file__).parent / "public"
    public_dir.mkdir(exist_ok=True)

    # 生成文件名
    filename = f"agent_demo_{client_name}_{uuid.uuid4().hex[:8]}.html"
    filepath = public_dir / filename

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(result)

    # 返回访问 URL
    url = f"/public/{filename}"

    return {"success": True, "url": url, "filename": filename}


# ==================== 健康检查 ====================

@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

@app.get("/")
async def root():
    """根路径"""
    return {"message": "Provider Assist API", "version": "1.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
