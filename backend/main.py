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
    """获取客户列表（不含大字段）"""
    conn = get_db()
    cursor = conn.cursor()
    # 只查列表页需要的字段，避免返回巨大的 uploaded_files / transcript / step4_report
    cursor.execute("""
        SELECT id, user_id, name, industry, initial_demand, status,
               step1_result, step2_report, step2_todo, step2_schema,
               step4_presales, step4_technical, step5_schema,
               created_at, updated_at, demo_url,
               COALESCE(LENGTH(uploaded_files) - LENGTH(REPLACE(uploaded_files, '[', '')), 0) AS note_count
        FROM clients WHERE user_id = ? ORDER BY updated_at DESC
    """, (user["user_id"],))
    cols = ["id", "user_id", "name", "industry", "initial_demand", "status",
            "step1_result", "step2_report", "step2_todo", "step2_schema",
            "step4_presales", "step4_technical", "step5_schema",
            "created_at", "updated_at", "demo_url", "note_count"]
    clients = [dict(zip(cols, row)) for row in cursor.fetchall()]
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

STEP4_PRESALES_PROMPT = """你是一个企业微信智能表格售前方案顾问。请基于以下客户信息，生成高质量的售前方案文档，质量对标【贝尔高林案例】——那份方案的核心特征是：客户信息极度具体（不是泛泛而谈）、表名和字段名精确到实际业务场景、每个痛点都有现状→问题→方案→价值的完整逻辑链、每个待确认问题都直接影响字段和报价。

【输入信息】
客户名称：{customer_name}
行业：{industry}
规模：{scale}
初始需求：{initial_demand}

【客户画像 - Step1输出】
{company_background}

【行业痛点 - Step1输出】
{pain_points}

【信息缺口 - Step2输出】
{gaps}

【提问清单 - Step2输出】
{must_ask}

【沟通记录 - Step3输出】
{transcript}

【输出标准 - 必须逐条遵循】

## 必须输出的完整章节结构

### 1. 客户基础信息表
- 用表格形式输出：客户名称、行业、规模、当前工具、已有系统、核心角色、建设阶段判断
- 建设阶段判断要具体：如"智能表格原型与一期落地评估"而不是"数字化转型"

### 2. 核心判断（一句话）
- 用一段话说清楚本期方案的核心判断：如"一期先搭建X张智能表，跑通项目/人力/财务三条主链路"
- 这是整份方案的主旨，后面所有内容都围绕这个判断展开

### 3. 需求洞察（4-6条）
- 每条包含：编号、洞察标题、详细说明
- 格式参考贝尔高林：① 项目主数据缺口 → 具体说明缺口是什么 ② 人力投入需要从百分比到小时 → 为什么重要 ③ ...
- 每个洞察都要有业务逻辑支撑，不是泛泛而谈

### 4. 核心痛点（P-01, P-02...）
每条痛点必须包含：
- **问题标题**：简洁明确
- **现状**：当前怎么做、数据在哪、有什么问题（具体到操作层面）
- **方案**：用企微智能表格怎么解决（具体到表名、功能、权限）
- **价值**：量化收益，如"减少50%人工录入"、"管理层看板可见率100%"
- **优先级**：P0一期重点 / P1一期 / P2二期

### 5. 智能表格架构
- 分层描述：入口层 / 核心业务层 / 配置数据层 / 自动化层
- 每层列出具体组件，不要空泛

### 6. 建议建设的智能表（核心章节）
每张表必须包含：
- **表名**：必须具体，如 Project Master、Task Schedule、Payment Tracker
- **类型**：业务主表 / 明细记录表 / 基础数据表 / 配置表
- **用途**：详细说明这张表干什么、存什么、怎么用（不少于50字）
- **使用对象**：谁维护、谁查看
- **一期必做**：是/否/待确认

至少输出5-7张表的详细设计。

### 7. 核心字段设计
每张表列出关键字段：
- 表名 / 字段名 / 字段类型 / 必填 / 可操作角色 / 填写规则
- 字段名要具体：如 Proposal Number、Project Number（双编号）而不是"项目编号"

### 8. 权限设计矩阵
按角色分：
- 全局可见（如公司高管）
- 区域隔离（如区域办公室成员）
- 敏感字段可见（如财务人员）
- 人力调度（如 Team Leader）
- 个人视图（如普通员工）
- 项目推进（如 PM）

每种角色说明：可以查看什么、可以编辑什么、哪些字段对其隐藏。

### 9. 一期/二期/不建议边界
分三个板块，每项说明具体范围和原因：
- **一期明确覆盖**：客户明确提到+企微轻量实现+不依赖接口
- **二期可扩展**：需接口/数据清洗/AI能力
- **暂不建议纳入**：替代专业系统/强监管/过于复杂

### 10. 实施路径（4-5个阶段）
每个阶段包含：
- 阶段名称（如第1阶段：需求确认）
- 主要工作内容
- 客户配合事项
- 输出物

### 11. 待确认问题（Q1-QN）
每个问题必须包含：
- 编号和具体问题（如"Project Master 中以 Proposal Number 还是 Project Number 作为主关联口径？"）
- 影响范围（影响哪些表/字段/报价）
- 建议确认负责人
- 建议确认时间（在哪个阶段前）

【关键质量要求 - 违反会导致输出不合格】
1. **表名必须具体**：不能写"项目管理表"，要写"Project Master（项目主表）"
2. **痛点必须有现状→问题→方案→价值四段**：不能只写"需要提升效率"
3. **字段名必须精确**：如"Proposal Number（项目建议书编号）"而不是"项目编号"
4. **待确认问题必须具体**：如"双编号口径确认（影响Project Master关联字段）"而不是"是否需要编号"
5. **价值必须量化**：如"减少60%人工催办"而不是"提升效率"
6. **不能泛泛而谈**：每一句话都要指向具体业务场景和具体数据

输出格式：完整JSON对象，所有字段名用中文，值根据业务情况填写。"""

# The rest of the file replacement below
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


@app.get("/api/step4/download-html")
async def download_step4_html(filename: str, user: dict = Depends(require_auth)):
    """下载已生成的 HTML 方案文件"""
    public_dir = Path(__file__).parent / "public"
    filepath = public_dir / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="文件不存在或已过期")
    from fastapi.responses import FileResponse
    return FileResponse(filepath, media_type="text/html", filename=f"售前方案_{filename.split('_', 2)[-1]}")


@app.post("/api/step5/generate-demo")
async def generate_step5_demo(body: dict, user: dict = Depends(require_auth)):
    """基于 Step4 售前方案生成真实 Demo 数据"""
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
    for field in ("step1_result", "step4_presales", "step4_technical"):
        if client.get(field) and isinstance(client[field, str]):
            try:
                client[field] = json.loads(client[field])
            except:
                pass

    customer_name = client.get("name", "客户")
    industry = client.get("industry", "")
    presales = client.get("step4_presales") or {}
    step1 = client.get("step1_result") or {}

    # 从 step4_presales 提取表格设计
    tables = presales.get("建议建设的智能表") or presales.get("智能表格总览") or []
    pain_points = presales.get("核心痛点") or []
    phases = presales.get("实施计划") or presales.get("实施路径") or []

    system_prompt = """你是一个企业微信智能表格 Demo 数据生成专家。你的任务是根据客户的需求分析，生成真实可信的 Demo 数据。

## 输出要求
直接输出 JSON，不要任何 markdown 代码块包裹。JSON 结构如下：
{
  "doc_name": "客户名 - 智能表格Demo",
  "sheets": [
    {
      "sheet_name": "表名",
      "fields": [
        {"field_title": "字段名", "field_type": "text|number|date|select|percent"}
      ],
      "sample_records": [
        {"字段名": "值", ...}
      ]
    }
  ],
  "agent_scenarios": [
    {"type": "qa", "question": "用户问题", "answer": "AI回答", "screenshot_hint": "截图提示"},
    {"type": "auto", "task": "任务名称", "description": "任务描述", "trigger": "触发条件"}
  ]
}

## 关键要求
1. 每个 sheet 至少 10 条 sample_records
2. 数据要真实可信，字段值要符合业务逻辑
3. 项目编号要符合"景观设计项目"的命名规范（如 LND-2024-001）
4. 日期使用 YYYY-MM-DD 格式
5. 金额使用数字，不要带货币符号
6. select 类型字段提供 2-5 个选项

## 贝尔高林案例参考字段（实际按需选用）
- Project Master: 项目编号/项目名称/项目阶段/项目状态/所属区域/负责人/合同金额/已开票/已回款/风险等级
- Task Schedule: 任务名称/负责人/所属项目/计划小时/实际小时/开始日期/截止日期/任务状态/超载标识
- Payment Tracker: 项目名称/发票号码/开票日期/合同金额/已开票/已回款/回款日期/逾期天数/回款状态
- Team Roster: 姓名/职级/团队/办公室/角色/人力来源/是否组长

直接输出 JSON。"""

    user_prompt = f"""## 客户信息
客户名称：{customer_name}
行业：{industry}

## 售前方案 - 建议建设的智能表
{json.dumps(tables, ensure_ascii=False, indent=2) if tables else "暂无具体方案，请根据行业惯例生成合适的数据"}

## 核心痛点（了解客户关注什么）
{json.dumps(pain_points, ensure_ascii=False, indent=2) if pain_points else "暂无"}

## 客户画像
{json.dumps(step1.get("part1", {}), ensure_ascii=False, indent=2) if step1 else "暂无"}

请生成 4 个核心智能表的 Demo 数据（Project Master、Task Schedule、Payment Tracker、Team Roster），每个表至少 10 条真实记录。同时生成 4 个 Agent 场景（2 个问答 + 2 个自动任务）。"""

    result = call_deepseek(system_prompt, user_prompt, max_tokens=8000)

    # 解析 JSON
    demo_data = None
    try:
        json_match = re.search(r'\{[\s\S]*\}', result)
        if json_match:
            demo_data = json.loads(json_match.group())
    except:
        demo_data = None

    if not demo_data:
        # 生成 fallback 数据
        demo_data = _generate_fallback_demo(customer_name, industry)

    return {"success": True, "demo": demo_data}


def _generate_fallback_demo(customer_name, industry):
    """当 AI 生成失败时返回基础 fallback 数据"""
    return {
        "doc_name": f"{customer_name} - 智能表格Demo",
        "sheets": [
            {
                "sheet_name": "Project Master",
                "fields": [
                    {"field_title": "项目编号", "field_type": "text"},
                    {"field_title": "项目名称", "field_type": "text"},
                    {"field_title": "项目阶段", "field_type": "select"},
                    {"field_title": "项目状态", "field_type": "select"},
                    {"field_title": "所属区域", "field_type": "select"},
                    {"field_title": "项目负责人", "field_type": "text"},
                    {"field_title": "合同金额(万)", "field_type": "number"},
                    {"field_title": "已开票(万)", "field_type": "number"},
                    {"field_title": "已回款(万)", "field_type": "number"},
                    {"field_title": "风险等级", "field_type": "select"}
                ],
                "sample_records": [
                    {"项目编号": "LND-2024-001", "项目名称": "Urban Plaza 景观设计", "项目阶段": "施工图", "项目状态": "进行中", "所属区域": "香港", "项目负责人": "陈志强", "合同金额(万)": 85, "已开票(万)": 51, "已回款(万)": 42, "风险等级": "低"},
                    {"项目编号": "LND-2024-002", "项目名称": "Seaside Residence 海滨住宅", "项目阶段": "方案设计", "项目状态": "进行中", "所属区域": "越南", "项目负责人": "黎英俊", "合同金额(万)": 120, "已开票(万)": 36, "已回款(万)": 24, "风险等级": "中"},
                    {"项目编号": "LND-2024-003", "项目名称": "Metro Mall 商业综合体", "项目阶段": "概念设计", "项目状态": "待启动", "所属区域": "大陆", "项目负责人": "张明华", "合同金额(万)": 200, "已开票(万)": 0, "已回款(万)": 0, "风险等级": "低"},
                    {"项目编号": "LND-2023-015", "项目名称": "Hilltop Villa 山顶别墅", "项目阶段": "施工图", "项目状态": "已完成", "所属区域": "香港", "项目负责人": "陈志强", "合同金额(万)": 65, "已开票(万)": 65, "已回款(万)": 65, "风险等级": "低"},
                    {"项目编号": "LND-2024-004", "项目名称": "Tech Park 科技园", "项目阶段": "扩初设计", "项目状态": "进行中", "所属区域": "大陆", "项目负责人": "王晓东", "合同金额(万)": 150, "已开票(万)": 75, "已回款(万)": 60, "风险等级": "高"},
                    {"项目编号": "LND-2024-005", "项目名称": "Lakeside Hotel 湖滨酒店", "项目阶段": "方案设计", "项目状态": "进行中", "所属区域": "泰国", "项目负责人": "颂猜", "合同金额(万)": 95, "已开票(万)": 28.5, "已回款(万)": 19, "风险等级": "中"},
                    {"项目编号": "LND-2023-018", "项目名称": "Central Park 城市公园", "项目阶段": "施工图", "项目状态": "已完成", "所属区域": "越南", "项目负责人": "黎英俊", "合同金额(万)": 180, "已开票(万)": 180, "已回款(万)": 162, "风险等级": "低"},
                    {"项目编号": "LND-2024-006", "项目名称": "Harbor View 海港景观", "项目阶段": "概念设计", "项目状态": "待启动", "所属区域": "香港", "项目负责人": "陈志强", "合同金额(万)": 55, "已开票(万)": 0, "已回款(万)": 0, "风险等级": "低"},
                    {"项目编号": "LND-2024-007", "项目名称": "Eco Resort 生态度假村", "项目阶段": "扩初设计", "项目状态": "进行中", "所属区域": "越南", "项目负责人": "阮氏华", "合同金额(万)": 110, "已开票(万)": 55, "已回款(万)": 44, "风险等级": "中"},
                    {"项目编号": "LND-2024-008", "项目名称": "Downtown Plaza 市中心广场", "项目阶段": "施工图", "项目状态": "进行中", "所属区域": "大陆", "项目负责人": "张明华", "合同金额(万)": 75, "已开票(万)": 60, "已回款(万)": 45, "风险等级": "高"},
                    {"项目编号": "LND-2024-009", "项目名称": "Residential Complex 住宅小区", "项目阶段": "方案设计", "项目状态": "待启动", "所属区域": "泰国", "项目负责人": "巴育", "合同金额(万)": 88, "已开票(万)": 0, "已回款(万)": 0, "风险等级": "低"},
                    {"项目编号": "LND-2023-020", "项目名称": "Waterfront Park 滨水公园", "项目阶段": "已完成", "项目状态": "已完成", "所属区域": "香港", "项目负责人": "陈志强", "合同金额(万)": 42, "已开票(万)": 42, "已回款(万)": 42, "风险等级": "低"}
                ]
            },
            {
                "sheet_name": "Task Schedule",
                "fields": [
                    {"field_title": "任务名称", "field_type": "text"},
                    {"field_title": "所属项目", "field_type": "text"},
                    {"field_title": "负责人", "field_type": "text"},
                    {"field_title": "计划小时", "field_type": "number"},
                    {"field_title": "实际小时", "field_type": "number"},
                    {"field_title": "开始日期", "field_type": "date"},
                    {"field_title": "截止日期", "field_type": "date"},
                    {"field_title": "任务状态", "field_type": "select"},
                    {"field_title": "超载标识", "field_type": "select"}
                ],
                "sample_records": [
                    {"任务名称": "方案文本撰写", "所属项目": "Urban Plaza 景观设计", "负责人": "陈志强", "计划小时": 40, "实际小时": 38, "开始日期": "2024-03-01", "截止日期": "2024-03-15", "任务状态": "已完成", "超载标识": "正常"},
                    {"任务名称": "植物配置设计", "所属项目": "Urban Plaza 景观设计", "负责人": "李美琪", "计划小时": 60, "实际小时": 72, "开始日期": "2024-03-05", "截止日期": "2024-03-28", "任务状态": "进行中", "超载标识": "超载"},
                    {"任务名称": "施工图绘制", "所属项目": "Urban Plaza 景观设计", "负责人": "张伟", "计划小时": 80, "实际小时": 65, "开始日期": "2024-03-10", "截止日期": "2024-04-20", "任务状态": "进行中", "超载标识": "正常"},
                    {"任务名称": "扩初文本撰写", "所属项目": "Tech Park 科技园", "负责人": "王晓东", "计划小时": 50, "实际小时": 55, "开始日期": "2024-03-01", "截止日期": "2024-03-20", "任务状态": "已完成", "超载标识": "正常"},
                    {"任务名称": "水电配合", "所属项目": "Tech Park 科技园", "负责人": "赵强", "计划小时": 30, "实际小时": 28, "开始日期": "2024-03-15", "截止日期": "2024-03-30", "任务状态": "进行中", "超载标识": "正常"},
                    {"任务名称": "方案概念设计", "所属项目": "Eco Resort 生态度假村", "负责人": "阮氏华", "计划小时": 80, "实际小时": 95, "开始日期": "2024-02-20", "截止日期": "2024-03-25", "任务状态": "进行中", "超载标识": "超载"},
                    {"任务名称": "结构计算", "所属项目": "Eco Resort 生态度假村", "负责人": "黎明", "计划小时": 40, "实际小时": 42, "开始日期": "2024-03-01", "截止日期": "2024-03-18", "任务状态": "已完成", "超载标识": "正常"},
                    {"任务名称": "夜景灯光设计", "所属项目": "Harbor View 海港景观", "负责人": "陈志强", "计划小时": 35, "实际小时": 0, "开始日期": "2024-04-01", "截止日期": "2024-04-15", "任务状态": "待启动", "超载标识": "正常"},
                    {"任务名称": "施工图审核", "所属项目": "Hilltop Villa 山顶别墅", "负责人": "张伟", "计划小时": 20, "实际小时": 22, "开始日期": "2024-03-10", "截止日期": "2024-03-20", "任务状态": "已完成", "超载标识": "正常"},
                    {"任务名称": "变更洽商", "所属项目": "Downtown Plaza 市中心广场", "负责人": "张明华", "计划小时": 15, "实际小时": 28, "开始日期": "2024-03-05", "截止日期": "2024-03-15", "任务状态": "进行中", "超载标识": "超载"},
                    {"任务名称": "材料样板确认", "所属项目": "Lakeside Hotel 湖滨酒店", "负责人": "颂猜", "计划小时": 25, "实际小时": 20, "开始日期": "2024-03-08", "截止日期": "2024-03-20", "任务状态": "已完成", "超载标识": "正常"},
                    {"任务名称": "项目汇报PPT", "所属项目": "Metro Mall 商业综合体", "负责人": "张明华", "计划小时": 16, "实际小时": 0, "开始日期": "2024-04-10", "截止日期": "2024-04-15", "任务状态": "待启动", "超载标识": "正常"}
                ]
            },
            {
                "sheet_name": "Payment Tracker",
                "fields": [
                    {"field_title": "项目名称", "field_type": "text"},
                    {"field_title": "发票号码", "field_type": "text"},
                    {"field_title": "开票日期", "field_type": "date"},
                    {"field_title": "合同金额(万)", "field_type": "number"},
                    {"field_title": "已开票(万)", "field_type": "number"},
                    {"field_title": "已回款(万)", "field_type": "number"},
                    {"field_title": "回款日期", "field_type": "date"},
                    {"field_title": "逾期天数", "field_type": "number"},
                    {"field_title": "回款状态", "field_type": "select"}
                ],
                "sample_records": [
                    {"项目名称": "Urban Plaza 景观设计", "发票号码": "INV-2024-001", "开票日期": "2024-01-15", "合同金额(万)": 85, "已开票(万)": 51, "已回款(万)": 42, "回款日期": "2024-02-20", "逾期天数": 0, "回款状态": "已回款"},
                    {"项目名称": "Urban Plaza 景观设计", "发票号码": "INV-2024-002", "开票日期": "2024-02-28", "合同金额(万)": 85, "已开票(万)": 51, "已回款(万)": 0, "回款日期": "", "逾期天数": 35, "回款状态": "逾期"},
                    {"项目名称": "Seaside Residence 海滨住宅", "发票号码": "INV-2024-003", "开票日期": "2024-02-10", "合同金额(万)": 120, "已开票(万)": 36, "已回款(万)": 24, "回款日期": "2024-03-15", "逾期天数": 0, "回款状态": "部分回款"},
                    {"项目名称": "Hilltop Villa 山顶别墅", "发票号码": "INV-2023-015", "开票日期": "2023-10-01", "合同金额(万)": 65, "已开票(万)": 65, "已回款(万)": 65, "回款日期": "2023-11-15", "逾期天数": 0, "回款状态": "已回款"},
                    {"项目名称": "Tech Park 科技园", "发票号码": "INV-2024-004", "开票日期": "2024-01-20", "合同金额(万)": 150, "已开票(万)": 75, "已回款(万)": 60, "回款日期": "2024-03-01", "逾期天数": 0, "回款状态": "部分回款"},
                    {"项目名称": "Tech Park 科技园", "发票号码": "INV-2024-005", "开票日期": "2024-03-10", "合同金额(万)": 150, "已开票(万)": 75, "已回款(万)": 0, "回款日期": "", "逾期天数": 15, "回款状态": "逾期"},
                    {"项目名称": "Lakeside Hotel 湖滨酒店", "发票号码": "INV-2024-006", "开票日期": "2024-02-25", "合同金额(万)": 95, "已开票(万)": 28.5, "已回款(万)": 19, "回款日期": "2024-03-20", "逾期天数": 0, "回款状态": "部分回款"},
                    {"项目名称": "Central Park 城市公园", "发票号码": "INV-2023-018", "开票日期": "2023-08-01", "合同金额(万)": 180, "已开票(万)": 180, "已回款(万)": 162, "回款日期": "2023-12-01", "逾期天数": 0, "回款状态": "部分回款"},
                    {"项目名称": "Eco Resort 生态度假村", "发票号码": "INV-2024-007", "开票日期": "2024-03-05", "合同金额(万)": 110, "已开票(万)": 55, "已回款(万)": 44, "回款日期": "", "逾期天数": 10, "回款状态": "逾期"},
                    {"项目名称": "Downtown Plaza 市中心广场", "发票号码": "INV-2024-008", "开票日期": "2024-02-01", "合同金额(万)": 75, "已开票(万)": 60, "已回款(万)": 45, "回款日期": "2024-03-10", "逾期天数": 0, "回款状态": "部分回款"},
                    {"项目名称": "Waterfront Park 滨水公园", "发票号码": "INV-2023-020", "开票日期": "2023-06-01", "合同金额(万)": 42, "已开票(万)": 42, "已回款(万)": 42, "回款日期": "2023-08-01", "逾期天数": 0, "回款状态": "已回款"},
                    {"项目名称": "Metro Mall 商业综合体", "发票号码": "INV-2024-009", "开票日期": "2024-03-15", "合同金额(万)": 200, "已开票(万)": 0, "已回款(万)": 0, "回款日期": "", "逾期天数": 0, "回款状态": "待开票"}
                ]
            },
            {
                "sheet_name": "Team Roster",
                "fields": [
                    {"field_title": "姓名", "field_type": "text"},
                    {"field_title": "职级", "field_type": "select"},
                    {"field_title": "团队", "field_type": "select"},
                    {"field_title": "办公室", "field_type": "select"},
                    {"field_title": "角色", "field_type": "select"},
                    {"field_title": "人力来源", "field_type": "select"},
                    {"field_title": "是否组长", "field_type": "select"}
                ],
                "sample_records": [
                    {"姓名": "陈志强", "职级": "高级设计师", "团队": "设计A组", "办公室": "香港", "角色": "设计师", "人力来源": "全职", "是否组长": "是"},
                    {"姓名": "李美琪", "职级": "设计师", "团队": "设计A组", "办公室": "香港", "角色": "设计师", "人力来源": "全职", "是否组长": "否"},
                    {"姓名": "张伟", "职级": "高级设计师", "团队": "设计B组", "办公室": "香港", "角色": "设计师", "人力来源": "全职", "是否组长": "是"},
                    {"姓名": "黎英俊", "职级": "设计总监", "团队": "设计部", "办公室": "越南", "角色": "设计总监", "人力来源": "全职", "是否组长": "是"},
                    {"姓名": "阮氏华", "职级": "设计师", "团队": "越南组", "办公室": "越南", "角色": "设计师", "人力来源": "全职", "是否组长": "否"},
                    {"姓名": "王晓东", "职级": "项目总监", "团队": "项目部", "办公室": "大陆", "角色": "项目总监", "人力来源": "全职", "是否组长": "是"},
                    {"姓名": "张明华", "职级": "高级设计师", "团队": "大陆组", "办公室": "大陆", "角色": "设计师", "人力来源": "全职", "是否组长": "是"},
                    {"姓名": "赵强", "职级": "助理设计师", "团队": "大陆组", "办公室": "大陆", "角色": "设计师", "人力来源": "全职", "是否组长": "否"},
                    {"姓名": "颂猜", "职级": "设计师", "团队": "东南亚组", "办公室": "泰国", "角色": "设计师", "人力来源": "全职", "是否组长": "否"},
                    {"姓名": "巴育", "职级": "项目负责人", "团队": "东南亚组", "办公室": "泰国", "角色": "项目经理", "人力来源": "全职", "是否组长": "是"},
                    {"姓名": "黎明", "职级": "结构设计师", "团队": "结构组", "办公室": "香港", "角色": "结构设计师", "人力来源": "全职", "是否组长": "否"},
                    {"姓名": "吴静", "职级": "财务经理", "团队": "财务部", "办公室": "香港", "角色": "财务", "人力来源": "全职", "是否组长": "是"},
                    {"姓名": "黄丽", "职级": "人事主管", "团队": "人事部", "办公室": "大陆", "角色": "人事", "人力来源": "全职", "是否组长": "是"},
                    {"姓名": "外包景观团队", "职级": "外部团队", "团队": "外包组", "办公室": "大陆", "角色": "设计师", "人力来源": "外包", "是否组长": "是"}
                ]
            }
        ],
        "agent_scenarios": [
            {"type": "qa", "question": "Landscape A 项目的当前进度和回款情况？", "answer": "Landscape A 项目（编号 LND-2024-001）位于香港，目前处于施工图阶段，项目状态为进行中。合同金额85万，已开票51万，已回款42万。回款进度正常，无逾期。", "screenshot_hint": "Project Master 表格中筛选 Landscape A 项目"},
            {"type": "qa", "question": "目前哪些项目存在回款逾期风险？", "answer": "目前有3个项目存在回款逾期风险：1) Urban Plaza 景观设计 - 逾期35天；2) Tech Park 科技园 - 逾期15天；3) Eco Resort 生态度假村 - 逾期10天。建议优先跟进催款。", "screenshot_hint": "Payment Tracker 中筛选逾期状态的项目"},
            {"type": "auto", "task": "生成周报", "description": "汇总本周所有项目进度和回款情况，生成项目经理周报", "trigger": "每周五下午自动触发"},
            {"type": "auto", "task": "超时任务提醒", "description": "扫描所有进行中任务，对超载任务（实际小时>计划小时110%）发送提醒给项目总监", "trigger": "每天上午9点自动触发"}
        ]
    }



def _safe_get(obj, *keys, default=''):
    for k in keys:
        if isinstance(obj, dict):
            obj = obj.get(k, None)
        else:
            return default
        if obj is None:
            return default
    return obj or default

def _render_insight(item, i):
    title = _safe_get(item, '标题', default=f'洞察 {i}')
    desc = _safe_get(item, '详细说明', default=str(item) if not isinstance(item, dict) else '')
    return f'<div class="insight-item"><div class="insight-num">{i}</div><div><b>{title}</b><span>{desc}</span></div></div>'

def _render_pain(item, i):
    title = _safe_get(item, '问题标题', default=f'P-{i:02d}')
    现状 = _safe_get(item, '现状', default='-')
    方案 = _safe_get(item, '方案', default='-')
    价值 = _safe_get(item, '价值', default='-')
    prio = _safe_get(item, '优先级', default='P0')
    prio_cls = 'p0' if 'P0' in prio else 'p1' if 'P1' in prio else 'p2'
    return f'<div class="scenario"><div class="scenario-side"><div class="num">{i:02d}</div><h3>{title}</h3><span class="badge {prio_cls}">{prio}</span></div><div class="scenario-body"><div class="point-grid"><div class="point"><b>现状</b>{现状}</div><div class="point"><b>方案</b>{方案}</div><div class="point"><b>价值</b>{价值}</div></div></div></div>'

def _render_table_row(item):
    name = _safe_get(item, '表名', default='-')
    tbl_type = _safe_get(item, '类型', default='-')
    usage = _safe_get(item, '用途', default='-')
    users = _safe_get(item, '使用对象', default='-')
    phase1 = _safe_get(item, '一期必做', default='-')
    cls = 'green' if phase1 in ('是','Yes','yes') else 'orange' if '待确认' in phase1 else ''
    return f'<tr><td><b>{name}</b></td><td>{tbl_type}</td><td>{usage}</td><td>{users}</td><td><span class="tag-mini {cls}">{phase1}</span></td></tr>'

def _render_permission(item):
    role = _safe_get(item, '角色', default='-')
    access = _safe_get(item, '可查看', default='-')
    edit = _safe_get(item, '可编辑', default='-')
    hidden = _safe_get(item, '隐藏字段', default='-')
    return f'<tr><td><b>{role}</b></td><td>{access}</td><td>{edit}</td><td>{hidden}</td></tr>'

def _render_confirm(item, i):
    q = _safe_get(item, '问题', default=str(item) if not isinstance(item, dict) else f'Q{i}')
    impact = _safe_get(item, '影响范围', default='-')
    owner = _safe_get(item, '建议确认负责人', default='-')
    timing = _safe_get(item, '建议确认时间', default='-')
    return f'<tr><td><b>Q{i}</b></td><td>{q}</td><td>{impact}</td><td>{owner}</td><td>{timing}</td></tr>'

def _render_phase(item, i):
    name = _safe_get(item, '阶段名称', default=f'第{i}阶段')
    work = _safe_get(item, '主要工作内容', default='-')
    coop = _safe_get(item, '客户配合', default='-')
    output = _safe_get(item, '输出物', default='-')
    return f'<div class="phase"><div class="phase-num">{i}</div><h3>{name}</h3><p><b>工作：</b>{work}</p><p><b>配合：</b>{coop}</p><p><b>输出：</b>{output}</p></div>'

def _render_boundary_item(item, tag_cls, tag_text):
    scope = str(item.get('具体范围', item) if isinstance(item, dict) else item)
    reason = item.get('原因', '') if isinstance(item, dict) else ''
    extra = f'<br><small style="color:#667085">原因：{reason}</small>' if reason else ''
    return f'<div class="qa-card"><b class="{tag_cls}">{tag_text}</b><span>{scope}</span>{extra}</div>'

def generate_solution_html(customer_name, industry, scale, initial_demand, presales, technical):
    positioning = _safe_get(presales, '方案定位') or _safe_get(presales, '核心判断', default='')
    insight_list = presales.get('需求洞察') or presales.get('核心判断列表') or []
    pain_points = presales.get('核心痛点') or []
    tables = presales.get('建议建设的智能表') or presales.get('智能表格总览') or []
    permissions = presales.get('权限设计矩阵') or presales.get('权限设计') or []
    confirms = presales.get('待确认问题') or []
    phases = presales.get('实施计划') or presales.get('实施路径') or []
    phase1 = presales.get('一期边界') or presales.get('一期明确覆盖') or []
    phase2 = presales.get('二期边界') or presales.get('二期可扩展') or []
    not_included = presales.get('暂不纳入') or presales.get('不建议纳入') or []

    insight_main = positioning or '一期先搭建核心智能表，跑通业务主链路。'
    insight_html = ''.join([_render_insight(it, i+1) for i, it in enumerate(insight_list[:6])])
    pain_html = ''.join([_render_pain(it, i+1) for i, it in enumerate(pain_points[:6])])

    table_rows = ''.join([_render_table_row(it) for it in tables])
    table_section = f'<section id="tables"><div class="section-head"><div><div class="kicker">04 / Tables</div><h2>建议建设的智能表</h2></div></div><div class="table-wrap"><table><thead><tr><th>表名</th><th>类型</th><th>用途</th><th>使用对象</th><th>一期</th></tr></thead><tbody>{table_rows}</tbody></table></div></section>' if table_rows else ''

    perm_rows = ''.join([_render_permission(it) for it in permissions])
    perm_section = f'<section id="permission"><div class="section-head"><div><div class="kicker">05 / Permission</div><h2>权限设计</h2></div></div><div class="table-wrap"><table><thead><tr><th>角色</th><th>可查看</th><th>可编辑</th><th>隐藏字段</th></tr></thead><tbody>{perm_rows}</tbody></table></div></section>' if perm_rows else ''

    phase1_html = ''.join([_render_boundary_item(it, 'tag-p0', '一期') for it in phase1])
    phase2_html = ''.join([_render_boundary_item(it, 'tag-p1', '二期') for it in phase2])
    not_html = ''.join([_render_boundary_item(it, 'tag-p2', '不建议') for it in not_included])

    phases_html = ''.join([_render_phase(it, i+1) for i, it in enumerate(phases[:5])])
    roadmap_section = f'<section id="roadmap"><div class="section-head"><div><div class="kicker">07 / Roadmap</div><h2>实施路径</h2></div></div><div class="timeline">{phases_html}</div></section>' if phases_html else ''

    confirm_rows = ''.join([_render_confirm(it, i+1) for i, it in enumerate(confirms)])
    confirm_section = f'<section id="confirm"><div class="section-head"><div><div class="kicker">08 / Confirm</div><h2>待确认问题</h2></div></div><div class="table-wrap"><table><thead><tr><th>编号</th><th>问题</th><th>影响范围</th><th>负责人</th><th>时间</th></tr></thead><tbody>{confirm_rows}</tbody></table></div></section>' if confirm_rows else ''

    # Build CSS with double braces for Python format strings
    css = (
        ":root{--blue:#1677ff;--cyan:#21c8f6;--green:#17b26a;--orange:#f79009;--ink:#101828;--text:#344054;--muted:#667085;--line:#e6edf7;--bg:#f5f8fc}"
        "*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,\"Segoe UI\",\"PingFang SC\",\"Microsoft YaHei\",sans-serif;color:var(--text);background:radial-gradient(circle at 12% -6%,rgba(22,119,255,.10),transparent 28%),radial-gradient(circle at 94% 0%,rgba(33,200,246,.08),transparent 26%),linear-gradient(180deg,#f7fbff 0%,#f5f8fc 42%,#f6f8fb 100%);line-height:1.65}"
        ".page{max-width:1240px;margin:0 auto;padding:26px 24px 76px}"
        ".topbar{height:58px;display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;padding:0 4px}.brand{display:flex;align-items:center;gap:12px;font-weight:900;color:var(--ink)}.brand-mark{width:34px;height:34px;border-radius:12px;background:linear-gradient(135deg,#1677ff,#1ec7f4);box-shadow:0 12px 24px rgba(22,119,255,.25);display:grid;place-items:center;color:#fff;font-weight:900}.doc-meta{font-size:13px;color:var(--muted)}"
        ".hero{position:relative;overflow:hidden;border:1px solid rgba(22,119,255,.13);border-radius:32px;background:linear-gradient(135deg,rgba(255,255,255,.98),rgba(235,246,255,.96) 58%,rgba(244,250,255,.96));box-shadow:0 18px 48px rgba(22,119,255,.10);padding:48px}.eyebrow{display:inline-flex;gap:9px;padding:7px 12px;border:1px solid #d8eaff;background:#edf6ff;color:#0f67d6;border-radius:999px;font-size:13px;font-weight:900;margin-bottom:18px}h1{margin:0;color:var(--ink);font-size:42px;line-height:1.14;letter-spacing:-1px}.hero-sub{margin:16px 0 20px;max-width:620px;font-size:17px;color:#475467}.chips{display:flex;gap:10px;flex-wrap:wrap}.chip{padding:8px 14px;background:rgba(255,255,255,.82);border:1px solid #e2edf9;border-radius:999px;color:#456074;font-size:13px;box-shadow:0 8px 18px rgba(16,24,40,.04)}"
        "section{margin-top:38px}.section-head{display:flex;justify-content:space-between;gap:24px;align-items:flex-end;margin-bottom:18px}.kicker{color:var(--blue);font-size:12px;font-weight:900;letter-spacing:.08em;text-transform:uppercase}h2{font-size:28px;color:var(--ink);line-height:1.24;margin:5px 0 0}"
        ".summary-strip{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:18px}.summary-item{background:#fff;border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:0 8px 24px rgba(16,24,40,.05)}.summary-item strong{display:block;color:#14213d;font-size:15px}.summary-item span{font-size:13px;color:var(--muted)}"
        ".insight{display:grid;grid-template-columns:1.1fr 1fr;gap:16px;align-items:stretch}.insight-main{border-radius:22px;background:linear-gradient(135deg,#1677ff,#25bdf3);color:#fff;padding:26px;box-shadow:0 20px 44px rgba(22,119,255,.20)}.insight-main h3{font-size:22px;line-height:1.3;margin:0 0 10px;color:#fff}.insight-main p{color:rgba(255,255,255,.85);margin:0}.insight-list{display:grid;gap:10px}.insight-item{display:grid;grid-template-columns:40px 1fr;gap:12px;background:#fff;border:1px solid var(--line);border-radius:16px;padding:15px;box-shadow:0 8px 24px rgba(16,24,40,.05)}.insight-num{width:40px;height:40px;border-radius:13px;background:#eef7ff;color:#1677ff;display:grid;place-items:center;font-weight:900;font-size:16px}.insight-item b{display:block;color:var(--ink);margin-bottom:3px}.insight-item span{color:var(--muted);font-size:13px;line-height:1.5}"
        ".scenario-list{display:grid;gap:14px}.scenario{display:grid;grid-template-columns:220px 1fr;gap:16px;padding:20px;border-radius:22px;background:#fff;border:1px solid var(--line);box-shadow:0 14px 38px rgba(16,24,40,.06)}.scenario-side{border-radius:16px;background:linear-gradient(180deg,#f1f8ff,#fff);border:1px solid #deecff;padding:16px}.scenario-side .num{font-size:32px;font-weight:950;color:#1677ff;line-height:1}.scenario-side h3{margin:6px 0 0;font-size:15px;color:var(--ink)}.badge{display:inline-flex;border-radius:999px;padding:3px 8px;font-size:11px;font-weight:900;margin-top:6px}.p0{background:#fff1f0;color:#b42318}.p1{background:#fff7e8;color:#b54708}.p2{background:#f2f4f7;color:#667085}"
        ".scenario-body{padding-top:4px}.point-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:8px}.point{background:#f8fbff;border:1px solid #e7f1ff;border-radius:12px;padding:10px;font-size:12px;color:#52677d;line-height:1.5}.point b{display:block;color:#203c5e;margin-bottom:4px;font-size:12px}"
        ".table-wrap{overflow:hidden;border:1px solid var(--line);border-radius:22px;background:#fff;box-shadow:0 14px 38px rgba(16,24,40,.06)}table{width:100%;border-collapse:collapse}th,td{padding:13px 14px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}th{background:#f1f8ff;color:#1e477d;font-size:12px;white-space:nowrap;font-weight:900}td{font-size:13px;color:#475467}tr:last-child td{border-bottom:0}"
        ".timeline{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}.phase{position:relative;background:#fff;border:1px solid var(--line);border-radius:20px;padding:18px;box-shadow:0 14px 38px rgba(16,24,40,.06)}.phase-num{width:36px;height:36px;border-radius:13px;background:linear-gradient(135deg,#1677ff,#21c8f6);color:#fff;display:grid;place-items:center;font-weight:900;margin-bottom:10px}.phase h3{margin:0 0 6px;color:var(--ink);font-size:16px}.phase p{margin:4px 0;font-size:12px;color:var(--muted);line-height:1.5}"
        ".qa{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}.qa-card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:16px}.qa-card b{display:block;margin-bottom:5px}.qa-card span{color:var(--muted);font-size:13px;line-height:1.5}.tag-p0{color:#b42318}.tag-p1{color:#b54708}.tag-p2{color:#667085}"
        ".tag-mini{display:inline-flex;border-radius:999px;padding:3px 8px;font-weight:900;font-size:11px}.green{background:#ecfdf3;color:#079455}.orange{background:#fff7ed;color:#dc6803}"
        ".cta{margin-top:42px;border-radius:28px;padding:32px;background:linear-gradient(135deg,#1267e8,#22b8ff);color:#fff;box-shadow:0 20px 46px rgba(22,119,255,.22);display:grid;grid-template-columns:1fr auto;gap:24px;align-items:center}.cta h2{margin:0 0 6px;color:#fff;font-size:26px}.cta p{margin:0;color:rgba(255,255,255,.85)}.cta-chip{background:#fff;color:#1263d1;font-weight:900;padding:10px 18px;border-radius:999px;font-size:13px}"
        "@media(max-width:1000px){.hero,.insight,.scenario{grid-template-columns:1fr}.timeline{grid-template-columns:repeat(2,1fr)}}.table-wrap{overflow-x:auto}table{min-width:700px}"
    )

    html = (
        '<!DOCTYPE html>\n'
        '<html lang="zh-CN">\n'
        '<head>\n'
        '<meta charset="UTF-8" />\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
        '<title>' + customer_name + '｜企业微信智能表格方案</title>\n'
        '<style>\n' + css + '\n</style>\n'
        '</head>\n'
        '<body>\n'
        '<div class="page">\n'
        '<header class="topbar"><div class="brand"><span class="brand-mark">企</span><span>企业微信生态服务方案</span></div><div class="doc-meta">售前方案 · 需求整理</div></header>\n\n'
        '<section class="hero">\n'
        '<div class="eyebrow">企业微信智能表格 · 售前方案</div>\n'
        '<h1>' + customer_name + '<br>需求整理方案</h1>\n'
        '<p class="hero-sub">' + insight_main + '</p>\n'
        '<div class="chips">\n'
        '<span class="chip">' + (industry or '行业待确认') + '</span>\n'
        '<span class="chip">' + (scale or '规模待确认') + '</span>\n'
        '<span class="chip">一期重点建设</span>\n'
        '</div>\n'
        '</section>\n\n'
        '<section><div class="section-head"><div><div class="kicker">01 / Background</div><h2>客户基础信息</h2></div></div>\n'
        '<div class="summary-strip">\n'
        '<div class="summary-item"><strong>客户名称</strong><span>' + customer_name + '</span></div>\n'
        '<div class="summary-item"><strong>所属行业</strong><span>' + (industry or '-') + '</span></div>\n'
        '<div class="summary-item"><strong>企业规模</strong><span>' + (scale or '-') + '</span></div>\n'
        '<div class="summary-item"><strong>需求方向</strong><span>' + (initial_demand or '-') + '</span></div>\n'
        '</div>\n'
        '</section>\n\n'
        '<section><div class="section-head"><div><div class="kicker">02 / Insight</div><h2>需求洞察</h2></div></div>\n'
        '<div class="insight">\n'
        '<div class="insight-main"><h3>' + insight_main + '</h3><p>基于客户现状与核心诉求，梳理本期数字化建设的主线与优先顺序。</p></div>\n'
        '<div class="insight-list">' + (insight_html or '') + '</div>\n'
        '</div>\n'
        '</section>\n\n'
        '<section><div class="section-head"><div><div class="kicker">03 / Pain Points</div><h2>核心痛点</h2></div></div>\n'
        '<div class="scenario-list">' + (pain_html or '<p style="color:var(--muted)">核心痛点待生成</p>') + '</div>\n'
        '</section>\n\n'
        + table_section + '\n'
        + perm_section + '\n\n'
        '<section><div class="section-head"><div><div class="kicker">06 / Boundary</div><h2>一期/二期/不建议边界</h2></div></div>\n'
        '<div class="qa">\n'
        + (phase1_html or '<div class="qa-card"><b class="tag-p0">一期</b><span>一期范围待生成</span></div>') + '\n'
        + (phase2_html or '<div class="qa-card"><b class="tag-p1">二期</b><span>二期范围待评估</span></div>') + '\n'
        + not_html + '\n'
        '</div>\n'
        '</section>\n\n'
        + roadmap_section + '\n'
        + confirm_section + '\n\n'
        '<section class="cta">\n'
        '<div><h2>建议下一步：确认字段、阶段字典与权限矩阵</h2><p>字段与权限确认后即可进入智能表原型搭建；接口和 AI 能力建议作为二期专项评估。</p></div>\n'
        '<div class="cta-chip">企业微信入口 + 智能表格数据底座</div>\n'
        '</section>\n'
        '</div>\n'
        '</body>\n'
        '</html>'
    )
    return html


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
