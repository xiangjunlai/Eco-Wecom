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
MINIMAX_API_KEY = "sk-cp-FxfZUSUHnTWn7eCtl1V-5CI1jFpfF3XLI0jxHZJ7U0p16_cea_FTQqxOaOYavdfwiS9DDN4pomf4CxLZlQYqIyvJJK_eaKR7tbh4d77_1dGK8DwQtwwjLDc"

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


MINIMAX_API_KEY = "sk-cp-FxfZUSUHnTWn7eCtl1V-5CI1jFpfF3XLI0jxHZJ7U0p16_cea_FTQqxOaOYavdfwiS9DDN4pomf4CxLZlQYqIyvJJK_eaKR7tbh4d77_1dGK8DwQtwwjLDc"

def call_minimax(system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> str:
    """调用 MiniMax API，300秒超时，最多一次重试"""
    import httpx

    def _do_request():
        response = httpx.post(
            "https://api.minimax.chat/v1/text/chatcompletion_v2",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {MINIMAX_API_KEY}"
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
            timeout=httpx.Timeout(300.0, connect=15.0)
        )
        result = response.json()
        return result["choices"][0]["message"]["content"]

    try:
        return _do_request()
    except httpx.TimeoutException:
        # 重试一次
        try:
            return _do_request()
        except httpx.TimeoutException:
            return "Error: MiniMax API 请求超时（300秒），请稍后重试"
        except Exception as e:
            return f"Error: {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"


app = FastAPI(title="Provider Assist API", version="1.0.0")

# 所有 OPTIONS 请求直接返回 200（处理 preflight）
@app.middleware("http")
async def cors_options_middleware(request, call_next):
    if request.method == "OPTIONS":
        from starlette.responses import JSONResponse
        return JSONResponse(
            {"status": "ok"},
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Max-Age": "600",
            },
        )
    return await call_next(request)

# CORS 允许所有来源（含 localhost:9090）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
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

@app.get("/api/debug-saved")
async def debug_saved(user: dict = Depends(require_auth)):
    """Debug: 检查 _saved 列"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, _completed, _saved FROM clients WHERE id = 71")
    row = cursor.fetchone()
    conn.close()
    d = dict(row)
    # 直接返回确认有 _saved
    import sys
    print(f"_saved in d: {'_saved' in d}, value: {d.get('_saved')}", file=sys.stderr)
    return {"_saved_val": d.get("_saved"), "completed_val": d.get("_completed"), "raw": d}

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

    result = call_minimax(system_prompt, user_prompt)

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
               created_at, updated_at, demo_url, _completed, _saved,
               COALESCE(LENGTH(uploaded_files) - LENGTH(REPLACE(uploaded_files, '[', '')), 0) AS note_count
        FROM clients WHERE user_id = ? ORDER BY updated_at DESC
    """, (user["user_id"],))
    cols = ["id", "user_id", "name", "industry", "initial_demand", "status",
            "step1_result", "step2_report", "step2_todo", "step2_schema",
            "step4_presales", "step4_technical", "step5_schema",
            "created_at", "updated_at", "demo_url", "_completed", "_saved", "note_count"]
    clients = []
    for row in cursor.fetchall():
        d = dict(zip(cols, row))
        d["is_completed"] = int(d.pop("_completed", 0) or 0)
        d["is_saved"] = int(d.pop("_saved", 0) or 0)
        clients.append(d)
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
    # FastAPI JSON 序列化会丢弃下划线开头的 key，强制 pop 后重命名
    _saved_v = result.pop("_saved", 0)
    result["is_saved"] = int(_saved_v) if _saved_v else 0
    _completed_v = result.pop("_completed", 0)
    result["is_completed"] = int(_completed_v) if _completed_v else 0
    # Parse JSON fields back to objects
    for field in ("step1_result", "step2_report", "step2_todo", "step2_schema", "step3_summary", "uploaded_files", "transcript", "step4_report", "step4_presales", "step4_technical", "step4_presales_versions", "step4_technical_versions", "step5_schema", "step5_agent_suggestions"):
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

    # 更新字段（前端发 is_completed/is_saved，数据库列名是 _completed/_saved）
    FIELD_MAP = {"is_completed": "_completed", "is_saved": "_saved"}
    allowed_fields = ["name", "industry", "initial_demand", "status", "step1_result", "step2_report", "step2_todo", "step2_schema", "step3_summary", "uploaded_files", "transcript", "step4_report", "step4_presales", "step4_technical", "step4_presales_versions", "step4_technical_versions", "step5_schema", "step5_agent_suggestions", "step4_input_draft", "demo_url", "_wecom_docid", "_wecom_url", "_step1_wecom_docid", "_step1_wecom_url", "is_completed", "is_saved", "company_type", "main_customers", "possible_focus", "company_intro"]
    updates = []
    values = []
    for field in allowed_fields:
        if field in data:
            db_field = FIELD_MAP.get(field, field)  # 前端名→数据库列名
            updates.append(f"{db_field} = ?")
            val = data[field]
            # JSON fields must be serialized to string for SQLite
            if field in ("step1_result", "step2_report", "step2_todo", "step2_schema", "step3_summary", "uploaded_files", "transcript", "step4_report", "step4_presales", "step4_technical", "step4_presales_versions", "step4_technical_versions", "step5_schema", "step5_agent_suggestions", "step4_input_draft"):
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

请严格输出以下 JSON 结构（直接输出 JSON，不要任何开场白，不要 markdown 代码块）：

{
  "customerCurrentState": "描述客户当前的业务状态、规模、已有系统、现状做法（50字以内）",
  "painPoints": [
    {
      "title": "痛点标题",
      "description": "痛点的详细描述",
      "evidence": "客户原话引用（精确到具体说法）"
    }
  ],
  "confirmedNeeds": [
    {
      "title": "需求名称",
      "description": "客户明确表达的具体需求",
      "evidence": "客户原话引用"
    }
  ],
  "involvedRoles": [
    {
      "role": "角色名称（例：销售负责人）",
      "responsibility": "该角色在项目中的职责"
    }
  ],
  "currentProcess": "客户当前业务流程是怎么跑的（30字以内）",
  "expectedOutcome": "客户期望达到的效果（30字以内）",
  "phaseOneScope": [
    {
      "item": "一期交付项名称",
      "description": "具体做什么"
    }
  ],
  "phaseTwoScope": [
    {
      "item": "二期评估项名称",
      "description": "为什么放二期（依赖条件或复杂度）"
    }
  ],
  "pendingQuestions": [
    {
      "question": "待确认的问题",
      "whyAsk": "为什么需要确认这个问题",
      "impactIfUnknown": "如果不知道会影响什么"
    }
  ]
}

## 填写规则
1. 只填写沟通记录中客户**明确说过**的内容，没说的字段填空数组或空字符串
2. painPoints 必须有客户原话引用（evidence 字段）
3. 一期只放客户明确说要做、且企业微信轻量可实现的
4. ERP对接/AI自动判断/历史数据清洗等默认放二期
5. pendingQuestions 要具体，不要泛泛而问
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

    result = call_minimax(system_prompt, user_prompt, max_tokens=max_tokens)

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

    # 解析报告 JSON（report类型，输出格式已经是JSON）
    parsed_report = None
    if output_type != "schema":
        try:
            parsed_report = json.loads(result)
        except Exception:
            # 降级：尝试从 markdown 中提取
            try:
                import re as re2
                m = re2.search(r'\{.*\}', result, re2.DOTALL)
                if m:
                    parsed_report = json.loads(m.group())
            except Exception:
                parsed_report = None
        if not parsed_report:
            parsed_report = {"_raw": result}  # 降级为含原始文本的对象

    return {
        "summary": parsed_report,  # 前端读取 data.summary
        "demo_json": demo_json,
        "context_used": {
            "industry_matched": bool(industry_text),
            "cases_matched": bool(case_context)
        }
    }

# ==================== Step4 方案生成（Prompt 3+4+5）====================

# Prompt 3: 需求结构化 → 生成 requirementSolutionData
STEP4_REQUIREMENT_PROMPT = """你是「企业微信服务商需求调研助手」中的需求结构化引擎。

你的任务不是直接写 Word，也不是直接写 HTML，也不是直接写智能表格搭建 Prompt。

你的任务是把 Step1、Step2、Step3、用户编辑后的 Step4 输入、知识库、xlsx 交付物，统一整理成一个稳定的中间结构 requirementSolutionData。

后续三个产物都必须基于这个结构生成：
1. Step4 产物1：Word 版《需求确认 & 方案设计表》
2. Step4 产物2：可视化方案 HTML
3. Step5 产物3：企业微信智能表格搭建 Prompt

====================
【输入信息】
====================

客户基础信息：
- 客户名称：{customer_name}
- 行业：{industry}
- 规模：{scale}
- 初始需求：{initial_demand}

Step1 客户画像：
{company_background}

Step1 行业痛点 / AI智搜辅助信息：
{pain_points}

Step2 信息缺口：
{gaps}

Step2 调研问题清单：
{must_ask}

Step3 原始沟通记录全文：
{transcript}

Step3 AI 摘要：
{step3_summary}

用户在 Step4「方案输入确认」中编辑并保存后的内容：
{step4_input_draft}

知识库匹配结果：
{kb_match_result}

智能表格交付物 xlsx 的 sheet 名和字段摘要：
{xlsx_sheet_summary}

服务商对客户需求总结：
{service_provider_summary}

====================
【材料使用优先级】
====================

请严格按以下优先级使用材料：
1. 用户编辑后的 step4_input_draft
2. Step3 AI 摘要 step3_summary
3. Step3 原始沟通记录 transcript 中客户明确表达的内容
4. 服务商对客户需求总结 service_provider_summary
5. xlsx sheet 名和字段摘要 xlsx_sheet_summary
6. Step1 / Step2 背景信息
7. 知识库 / 行业模板 / 历史方案

注意：
- **行业和场景（mainScenario）必须优先从 step4_input_draft 或 step3_summary 的对应字段读取，不得被 step1 industry 覆盖。**例如：客户是"设计/景观建筑-跨国多区域项目管理"，不得识别为"家居定制装修"。
- **xlsx sheet 名和字段摘要必须完整进入 smartTableSpec.confirmedTables，不得遗漏。**
- **如果 step3_summary 中的字段为空（如 confirmedNeeds、phaseOneScope 等），必须从 transcript 原始沟通记录中自行推理提取并填入，不得留空。**
- 知识库只能补充，不得覆盖客户事实。
- 客户没明确说过的内容，不得写成"客户已确认"。
- 多轮沟通中，如果后续收敛了范围，以后续范围为准。
- 客户只是提到 AI、ERP、系统对接、复杂财务核算、机器人自动填报时，默认写入二期评估，不得写入一期承诺，更不能写成 P0。
- 沟通记录里出现但没有进入 xlsx 或服务商总结的扩展需求，不能默认进入一期。
- **以下内容严禁写入一期 P0**：AI 智能填报、机器人自动写表、OA 系统 API 对接、复杂多区域独立阶段/财务追踪规则。

====================
【输出要求】
====================

请输出严格 JSON，不要输出 Markdown，不要输出解释文字。

JSON 结构如下：

{
  "meta": {
    "customerName": "",
    "industry": "",
    "companyScale": "",
    "mainScenario": "",
    "serviceProvider": "",
    "outputDate": "",
    "version": "v1"
  },

  "sourceTrace": {
    "confirmedByCustomer": [],
    "fromStep3Summary": [],
    "fromUserEditedInput": [],
    "fromServiceProviderSummary": [],
    "fromXlsxOrDeliveryFile": [],
    "fromKnowledgeBase": [],
    "inferredByAI": [],
    "pendingConfirmation": []
  },

  "customerFacts": {
    "customerCurrentState": "",
    "existingTools": [],
    "currentProcess": [
      {
        "stepName": "",
        "role": "",
        "currentMethod": "",
        "problem": "",
        "evidenceQuote": ""
      }
    ],
    "involvedRoles": [],
    "explicitNeeds": []
  },

  "painPoints": [
    {
      "title": "",
      "description": "",
      "businessImpact": "",
      "evidence": "客户原话/Step3摘要/用户编辑输入/服务商总结/知识库推断",
      "priority": "P0/P1/P2"
    }
  ],

  "requirements": [
    {
      "requirementName": "",
      "customerExpression": "",
      "businessTranslation": "",
      "priority": "P0/P1/P2",
      "phase": "一期/二期评估/暂不建议",
      "reasonForPhase": "",
      "confirmedStatus": "客户已确认/用户编辑确认/AI推断/待确认"
    }
  ],

  "scope": {
    "phaseOne": [
      {
        "item": "",
        "reason": "",
        "deliveryForm": ""
      }
    ],
    "phaseTwo": [
      {
        "item": "",
        "reason": "",
        "prerequisites": []
      }
    ],
    "notRecommended": [
      {
        "item": "",
        "reason": ""
      }
    ]
  },

  "businessProcess": {
    "currentFlow": [],
    "targetFlow": [],
    "processNodes": [
      {
        "nodeName": "",
        "responsibleRole": "",
        "input": "",
        "output": "",
        "systemAction": "",
        "reminderNeeded": true
      }
    ]
  },

  "moduleRecommendation": [
    {
      "moduleName": "",
      "moduleType": "智能表格/审批/自动化/权限/看板/机器人AI/系统对接",
      "solvedProblem": "",
      "phase": "一期/二期评估/暂不建议",
      "notes": ""
    }
  ],

  "smartTableSpec": {
    "scenarioComplexity": "简单流程型/跨部门协同型/多表主数据型/看板同步型/系统对接型",
    "confirmedTables": [
      {
        "tableName": "",
        "tablePurpose": "",
        "source": "xlsx/客户确认/服务商总结/知识库建议",
        "phase": "一期/二期评估",
        "roles": []
      }
    ],
    "suggestedTables": [],
    "phaseTwoTables": [],
    "fieldsByTable": [
      {
        "tableName": "",
        "fields": [
          {
            "fieldName": "",
            "fieldType": "文本/多行文本/单选/多选/数字/金额/日期/日期时间/人员/附件/图片/关联记录/公式/自动编号/进度/勾选/URL",
            "required": true,
            "rule": "",
            "source": "xlsx/客户确认/知识库建议/AI推断"
          }
        ]
      }
    ],
    "relations": [],
    "views": [],
    "automations": [],
    "permissions": [],
    "dashboards": [],
    "warnings": []
  },

  "openQuestions": [
    {
      "question": "",
      "whyAsk": "",
      "impactIfUnknown": "",
      "priority": "高/中/低"
    }
  ]
}

====================
【范围判断规则】
====================

一期只包含：
- 客户明确表达的核心需求
- 当前痛点强
- 可用企业微信入口 + 智能表格 + 审批 + 自动化 + 权限 + 看板轻量实现
- 不依赖复杂接口
- 不依赖复杂 AI 判断
- 不依赖大量历史数据清洗

二期评估默认包含：
- ERP / OA / CRM / 财务系统对接
- 数据回写
- AI 自动判断
- 复杂财务核算
- 历史数据清洗
- 多系统权限联动
- 机器人自动填报
- 高级经营分析

暂不建议默认包含：
- 替代完整 ERP / CRM / 财务系统
- 客户没明确提出但模板里有的模块
- 强监管实时决策
- 超出企业微信智能表格轻量交付边界的复杂系统

直接输出有效 JSON，不要 markdown 代码块包裹。"""

# Prompt 4: Word 内容生成
STEP4_WORD_PROMPT = """你是一个企业微信智能表格售前方案顾问。请基于以下结构化需求数据，生成《需求确认 & 方案设计表》Word 正文内容。

【requirementSolutionData】
{requirement_data}

请严格按以下 JSON 结构输出（直接输出 JSON，不要任何开场白，不要 markdown 代码块）：

{
  "docTitle": "需求确认 & 方案设计表",
  "subtitle": "企业微信定制开发",
  "version": "v1.0",
  "introNotice": "本文件用于服务商与客户共同确认需求范围、一期边界、智能表格搭建口径、权限与待确认问题。客户未确认内容不得写入一期交付承诺。",

  "customerInfoTable": [
    { "field": "客户名称", "value": "" },
    { "field": "行业", "value": "" },
    { "field": "规模", "value": "" },
    { "field": "办公区域/使用范围", "value": "" },
    { "field": "主场景", "value": "" },
    { "field": "方案口径", "value": "" }
  ],

  "currentPainTable": [
    { "businessArea": "", "currentStateOrPain": "" }
  ],

  "scenarioBoundary": {
    "scenarioJudgement": "",
    "phaseOne": [""],
    "phaseTwo": [""],
    "notRecommended": [""]
  },

  "requirementPriorityTable": [
    {
      "requirement": "",
      "priority": "P0/P1/P2",
      "phase": "一期/二期评估/暂不建议",
      "implementationApproach": ""
    }
  ],

  "processDesignTable": [
    {
      "item": "",
      "description": ""
    }
  ],

  "wecomArchitectureTable": [
    {
      "layer": "企业微信入口层/智能表格数据层/自动化与提醒层/权限与看板层",
      "designDescription": ""
    }
  ],

  "smartTableDeliveryTable": [
    {
      "tableName": "",
      "type": "主表/业务表/辅助表",
      "purpose": "",
      "roles": "",
      "phaseOne": "是/否"
    }
  ],

  "keyFieldsByTable": [
    {
      "tableName": "",
      "fields": [""]
    }
  ],

  "automationTable": [
    {
      "ruleName": "",
      "trigger": "",
      "action": "",
      "priority": "P0/P1/P2"
    }
  ],

  "permissionTable": [
    {
      "role": "",
      "viewScope": "",
      "operation": "",
      "sensitiveFields": ""
    }
  ],

  "dashboardTable": [
    {
      "dashboard": "",
      "users": "",
      "metrics": "",
      "filters": ""
    }
  ],

  "dataBoundaryTable": [
    {
      "dataObject": "",
      "phaseOneMethod": "",
      "phaseTwoEvaluation": "",
      "boundaryNote": ""
    }
  ],

  "implementationPlanTable": [
    {
      "phase": "",
      "workContent": "",
      "customerCooperation": "",
      "output": ""
    }
  ],

  "pendingQuestions": [""],

  "confirmationItems": [
    "一期范围是否按本文件定义执行 □ 确认 □ 调整",
    "字段与权限是否允许按试运行反馈微调 □ 确认 □ 调整",
    "OA/机器人/AI 能力是否作为二期评估 □ 确认 □ 调整",
    "客户签字/盖章：________________"
  ]
}

## 填写规则
1. customerInfoTable：value 全部从 requirementSolutionData.meta 和 customerFacts 读取，不得留空
2. currentPainTable：businessArea 为业务面（如"项目立项"/"开票回款"），currentStateOrPain 描述现状或痛点
3. scenarioBoundary.scenarioJudgement：必填，写明场景判断（如"设计/景观建筑-跨国多区域项目管理"）
4. requirementPriorityTable：**严禁**将 AI 能力、机器人自动写表、OA 对接写成 P0；requirements 为空时本章填写"【待补充】需求列表为空，请返回 Step3 补充沟通记录"
5. smartTableDeliveryTable：phaseOne="是"的表必须全部来自 smartTableSpec.confirmedTables，且 phase="一期"
6. keyFieldsByTable：每张表的字段列表，字段数量 5-15 个
7. pendingQuestions：每个问题必须是字符串，不得出现 [object Object]
8. 所有表格的每个单元格都必须是字符串，不得留空字符串（用"待确认"填充）

直接输出有效 JSON，不要 markdown 代码块包裹。"""

# Prompt 5: 可视化 HTML 内容生成
STEP4_HTML_PROMPT = """你是一个企业微信智能表格可视化方案顾问。请基于结构化需求数据，生成客户友好的可视化方案 HTML 内容。

【requirementSolutionData】
{requirement_data}

请按以下 JSON 结构输出（直接输出 JSON，不要任何开场白）：

{
  "pageTitle": "",
  "hero": {
    "title": "",
    "subtitle": "",
    "tags": [],
    "summary": ""
  },
  "customerStageJudgement": {
    "title": "",
    "description": "",
    "keyFacts": []
  },
  "insightSection": {
    "mainInsight": "",
    "painCards": [
      {
        "title": "",
        "description": "",
        "impact": ""
      }
    ]
  },
  "scenarioBreakdown": [
    {
      "scenarioName": "",
      "currentProblem": "",
      "targetState": "",
      "wecomSolution": "",
      "value": ""
    }
  ],
  "architecture": {
    "positioning": "",
    "layers": [
      {
        "layerName": "",
        "capability": "",
        "usage": ""
      }
    ]
  },
  "recommendedModules": [
    {
      "moduleName": "",
      "description": "",
      "phase": "一期/二期评估/暂不建议",
      "value": ""
    }
  ],
  "roadmap": [
    {
      "phaseName": "",
      "workContent": "",
      "customerCooperation": "",
      "output": ""
    }
  ],
  "valuePoints": [
    {
      "title": "",
      "description": ""
    }
  ],
  "pendingQuestions": []
}

内容要求：少字高信息密度、不堆砌字段、突出客户现状和核心痛点、不确定内容写"待确认"或"二期评估"。直接输出 JSON。"""

def parse_json_response(raw):
    """解析 MiniMax 返回的 JSON，处理各种异常情况"""
    import re, json
    if not raw:
        return None
    try:
        return json.loads(raw)
    except:
        pass
    # 尝试从 markdown 代码块中提取
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except:
            pass
    # 尝试找 JSON 对象
    m = re.search(r'\{[\s\S]*\}', raw)
    if m:
        try:
            return json.loads(m.group())
        except:
            pass
    return None

def _safe(v):
    """将任意值转为安全字符串，用于质检检测 [object Object]"""
    if v is None or v == "":
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float, bool)):
        return str(v)
    if isinstance(v, list):
        return "|||".join(_safe(x) for x in v)
    if isinstance(v, dict):
        for k in ("question", "whyAsk", "impactIfUnknown", "title", "description",
                  "item", "reason", "name", "requirement", "priority",
                  "phase", "tableName", "fieldName"):
            if k in v and v[k]:
                return _safe(v[k])
        return json.dumps(v, ensure_ascii=False)
    return str(v)

def db_get_client(client_id):
    """同步获取客户字典（用于非 async 函数）"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clients WHERE id = ?", (client_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    # JSON 字段反序列化
    for k in JSON_FIELDS:
        if k in d and d[k]:
            try:
                d[k] = json.loads(d[k])
            except Exception:
                pass
    return d


JSON_FIELDS = {"step1_result", "step2_report", "step2_todo", "step2_schema", "step3_summary",
                "uploaded_files", "transcript", "step4_report", "step4_presales", "step4_technical",
                "step4_presales_versions", "step4_technical_versions", "step5_schema",
                "step5_agent_suggestions", "step4_input_draft", "_completed", "_saved"}

def db_update_client(client_id, updates):
    """同步更新客户字段"""
    if not updates:
        return
    conn = get_db()
    cursor = conn.cursor()
    sets = []
    vals = []
    for k, v in updates.items():
        if k in JSON_FIELDS and v is not None:
            v = json.dumps(v, ensure_ascii=False)
        sets.append(f"{k} = ?")
        vals.append(v if v is not None else "")
    vals.append(client_id)
    cursor.execute(f"UPDATE clients SET {', '.join(sets)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", vals)
    conn.commit()
    conn.close()


def validate_requirement_doc(word_content, requirement_data=None):
    """质检生成的 Word 内容 JSON，不通过返回 errors"""
    errors = []
    warnings = []

    if not word_content or not isinstance(word_content, dict):
        errors.append("wordContent 为空或非对象")
        return {"pass": False, "errors": errors, "warnings": warnings}

    raw_str = json.dumps(word_content, ensure_ascii=False)

    # 1. 检查 [object Object]
    if "[object Object]" in raw_str:
        errors.append("出现 [object Object]，字段映射错误（对象未展开）")

    # 2. 检查 docTitle
    if not _safe(word_content.get("docTitle", "")):
        errors.append("docTitle 为空")

    # 3. 检查 11 个章节是否存在（容许某些章节为空列表但不允许多段落字符串空值）
    required_sections = [
        "customerInfoTable", "currentPainTable", "scenarioBoundary",
        "requirementPriorityTable", "processDesignTable", "wecomArchitectureTable",
        "smartTableDeliveryTable", "keyFieldsByTable", "automationTable",
        "permissionTable", "dashboardTable",
        "dataBoundaryTable", "implementationPlanTable",
        "pendingQuestions", "confirmationItems"
    ]
    for sec in required_sections:
        if sec not in word_content:
            errors.append(f"缺少章节：{sec}")

    # 4. 检查 requirements 是否为空（来自 requirementData）
    if requirement_data:
        reqs = requirement_data.get("requirements") or []
        if not reqs:
            errors.append("requirements 为空，请补充 Step3 沟通记录后重新生成")
        smart = requirement_data.get("smartTableSpec") or {}
        tables = smart.get("confirmedTables") or []
        if not tables:
            errors.append("confirmedTables 为空，请补充 xlsx 或 Step3 后重新生成")

    # 5. 检查空 table（数组为空，或数组每项全空字符串）
    def check_table(name, arr):
        if not isinstance(arr, list):
            errors.append(f"{name} 不是数组")
            return
        if len(arr) == 0:
            errors.append(f"{name} 为空表格")
            return
        for i, row in enumerate(arr):
            row_str = _safe(row)
            if not row_str.strip(" |"):
                errors.append(f"{name}[{i}] 所有字段为空")

    check_table("customerInfoTable", word_content.get("customerInfoTable"))
    check_table("requirementPriorityTable", word_content.get("requirementPriorityTable"))
    check_table("smartTableDeliveryTable", word_content.get("smartTableDeliveryTable"))

    # 6. 检查行业/场景识别错误
    industry_wrong = ["家居定制装修", "家居装修", "装修", "全屋定制"]
    scenario = _safe(word_content.get("scenarioBoundary", {}).get("scenarioJudgement", ""))
    cust_info = word_content.get("customerInfoTable", [])
    industry_val = ""
    for row in cust_info:
        if _safe(row.get("field", "")) == "行业":
            industry_val = _safe(row.get("value", ""))
            break
    if any(w in industry_val for w in industry_wrong):
        errors.append(f"行业识别错误：'{industry_val}'（应为设计/景观建筑-跨国多区域项目管理）")
    if "家居" in scenario or "家居定制" in scenario:
        errors.append(f"场景判断错误：'{scenario}'")

    # 7. 检查把 AI/机器人/OA/ERP 写成 P0 一期
    p0_phase_one = []
    for row in (word_content.get("requirementPriorityTable") or []):
        priority = _safe(row.get("priority", ""))
        phase = _safe(row.get("phase", ""))
        req_text = _safe(row.get("requirement", ""))
        if priority == "P0" and phase == "一期":
            for keyword in ["AI", "机器人", "OA", "ERP", "系统对接", "智能填报", "自动写表"]:
                if keyword in req_text:
                    p0_phase_one.append(f"P0 一期不能包含：{req_text}")
    p0_phase_one and errors.extend(p0_phase_one)

    # 8. 检查章节内容是否为泛泛段落而非表格
    for sec, has_table in [
        ("requirementPriorityTable", True),
        ("smartTableDeliveryTable", True),
        ("automationTable", True),
        ("permissionTable", True),
    ]:
        arr = word_content.get(sec, [])
        if has_table and isinstance(arr, list) and len(arr) > 0:
            first_row_str = _safe(arr[0])
            if first_row_str.count("|||") < 2 and len(first_row_str) > 200:
                warnings.append(f"{sec} 可能只是泛泛段落，建议改为结构化表格")

    return {"pass": len(errors) == 0, "errors": errors, "warnings": warnings}


# ==================== Step1 调研问题生成 ====================

STEP1_SYSTEM_PROMPT = """你是一个售前调研顾问。根据客户背景信息，生成结构化的售前准备材料 JSON。"""

STEP1_USER_PROMPT = """## 客户基本信息
- 客户名称：{company_name}
- 行业：{industry}
- 规模：{scale}
- 需求标签：{tags}
- 原始需求：{initial_demand}
- AI 补充简介：{company_intro}

## 生成要求

请生成结构化 JSON，直接输出 JSON，不要 markdown 代码块。

### part1（客户画像）
在客户填写的背景信息基础上，AI 扩展推理，生成：
- company_background：公司背景描述，150字以内，条理清晰
- pain_points：核心痛点数组，精确 5 条，每条 30 字以内
- customer_type：客户类型描述，如"制造业民营中小企业"
- main_customers：主要客户群体，1 句话

### part2（待确认信息清单）
在客户需求和痛点基础上，推理出 5-8 条最关键的信息缺口：
- gaps：数组，每项包含：
  - gap：缺口描述，40 字以内，表述清晰
  - priority：高/中/低
  - whyNeed：为什么需要知道这条信息，30 字以内

### part3（访谈提纲）

**must_ask（必问问题）：生成 10-12 条**
每条包含：
- question：问题正文
- dimension：所属维度（如：痛点收敛/业务流转+角色/现状工具链/数据现状/自动化诉求）
- note：提问提示和背景说明，帮助销售更好理解和追问，50字以内
- needRole：谁来回答这个问题

**deep_dive（深挖问题）：生成 5-8 条**
在 must_ask 基础上继续深挖，每条包含 question/dimension/note/needRole。

**industry_experience（行业经验）：生成 2-3 条**
基于该行业知识，给出 2-3 条行业常见坑或经验，每条包含 question 和 note。

直接输出 JSON，不要 markdown 代码块。"""


@app.post("/api/question_list")
async def question_list(body: dict, user: dict = Depends(require_auth)):
    """生成 Step1 调研问题（客户画像 + 信息缺口 + 调研清单）"""
    company_name = body.get("company_name", "")
    industry = body.get("industry", "")
    scale = body.get("scale", "")
    tags = body.get("tags", "")
    initial_demand = body.get("initial_demand", "")
    company_intro = body.get("company_intro", "")

    user_prompt = STEP1_USER_PROMPT.format(
        company_name=company_name,
        industry=industry,
        scale=scale or "未填写",
        tags=tags or "未填写",
        initial_demand=initial_demand or "未填写",
        company_intro=company_intro or "暂无"
    )

    raw = call_minimax(STEP1_SYSTEM_PROMPT, user_prompt, max_tokens=6000)
    if raw.startswith("Error:"):
        return {"success": False, "error": raw}

    # 解析 JSON
    result = parse_json_response(raw)
    if not result:
        return {"success": False, "error": "AI 返回格式异常，请重试"}

    return {
        "success": True,
        "result": result,   # 前端 updateClient({ step1_result: data.result })
        "summary": result   # 兼容前端 data.summary 判断
    }


@app.post("/api/step4/generate")
async def generate_step4_artifacts(body: dict, user: dict = Depends(require_auth)):
    """生成 Step4 售前方案和技术路线方案（Prompt 3→4→5 三步）"""
    client_id = body.get("client_id")
    artifact_type = body.get("type", "both")

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
    for field in ("step1_result", "step2_report", "step2_todo", "step2_schema", "step3_summary", "uploaded_files", "step4_input_draft"):
        if client.get(field) and isinstance(client[field], str):
            try:
                client[field] = json.loads(client[field])
            except:
                pass

    # 构建通用上下文
    customer_name = client.get("name", "")
    industry = client.get("industry", "")
    scale = client.get("scale", "")
    initial_demand = client.get("initial_demand", "")

    step1 = client.get("step1_result", {}) or {}
    company_background = step1.get("part1", {}).get("company_background", "") or ""
    pain_points = "\n".join(step1.get("part1", {}).get("pain_points", []) or [])
    gaps = "\n".join([f"- {g.get('gap', '')}" for g in (step1.get("part2") or [])])
    must_ask = step1.get("part3", {}) or {}
    must_ask_text = "\n".join([f"{i+1}. {q.get('question', '')}" for i, q in enumerate(must_ask.get("must_ask", []) or [])])

    uploaded_files = client.get("uploaded_files") or []
    transcript = "\n\n".join([f"【{f.get('name', '记录')}】{f.get('content', '') or f.get('text', '')}" for f in uploaded_files if f.get('content') or f.get('text')])

    # 知识库匹配结果
    kb_match_result = ""
    # 预留字段，后续接入知识库时填充

    # xlsx sheet 名和字段摘要
    xlsx_sheet_summary = ""
    step2_schema = client.get("step2_schema") or {}
    if step2_schema:
        sheets = step2_schema.get("sheets") or []
        if sheets:
            lines = []
            for s in sheets:
                name = s.get("name", "")
                cols = [c.get("name", "") for c in (s.get("columns") or []) if c.get("name")]
                lines.append(f"表名：{name}，字段：{', '.join(cols)}")
            xlsx_sheet_summary = "\n".join(lines)

    # 服务商对客户需求总结
    service_provider_summary = ""
    step2_report = client.get("step2_report") or {}
    if isinstance(step2_report, dict):
        summary = step2_report.get("summary", "") or step2_report.get("service_summary", "") or step2_report.get("demand_summary", "")
        if summary:
            service_provider_summary = summary
        else:
            # 尝试从其他常见字段提取
            for key in ("demand_analysis", "provider_summary", "needs_summary"):
                if step2_report.get(key):
                    service_provider_summary = step2_report.get(key)
                    break

    # 用户输入摘要（方案输入确认内容）— step4_input_draft 9字段结构
    step4_input_draft = client.get("step4_input_draft") or {}
    if isinstance(step4_input_draft, str):
        try:
            step4_input_draft = json.loads(step4_input_draft)
        except:
            step4_input_draft = {}
    input_summary = ""
    if step4_input_draft:
        def field_to_text(label, val):
            if not val:
                return ""
            if isinstance(val, list):
                val = "、".join(val)
            return f"{label}：{val}"
        lines = [
            field_to_text("客户现状", step4_input_draft.get("customerCurrentState")),
            field_to_text("核心问题", step4_input_draft.get("painPoints")),
            field_to_text("已确认需求", step4_input_draft.get("confirmedNeeds")),
            field_to_text("涉及角色", step4_input_draft.get("involvedRoles")),
            field_to_text("当前流程", step4_input_draft.get("currentProcess")),
            field_to_text("期望效果", step4_input_draft.get("expectedOutcome")),
            field_to_text("一期范围", step4_input_draft.get("phaseOneScope")),
            field_to_text("二期评估", step4_input_draft.get("phaseTwoScope")),
            field_to_text("待确认问题", step4_input_draft.get("pendingQuestions")),
        ]
        input_summary = "\n".join([l for l in lines if l])

    # step4_input_draft JSON 字符串
    step4_input_draft_str = json.dumps(step4_input_draft, ensure_ascii=False, indent=2) if step4_input_draft else "暂无用户已编辑输入"

    # step4_report.requirementData（历史草稿）
    step4_report = client.get("step4_report") or {}
    if isinstance(step4_report, str):
        try:
            step4_report = json.loads(step4_report)
        except:
            step4_report = {}
    step4_report_str = ""
    if step4_report.get("requirementData"):
        step4_report_str = json.dumps(step4_report.get("requirementData"), ensure_ascii=False, indent=2)

    # step3_summary（第三优先级）
    step3_summary = client.get("step3_summary") or {}
    if isinstance(step3_summary, str):
        try:
            step3_summary = json.loads(step3_summary)
        except:
            step3_summary = {}
    # 渲染 step3_summary 为可读文本（兼容新旧格式）
    step3_summary_text = ""
    if isinstance(step3_summary, dict):
        parts = []
        # ---- 新格式优先 ----
        if step3_summary.get("customerCurrentState"):
            parts.append("客户现状：" + str(step3_summary["customerCurrentState"]))
        if step3_summary.get("painPoints"):
            pains = step3_summary["painPoints"]
            if isinstance(pains, list):
                for p in pains:
                    if isinstance(p, dict):
                        parts.append(f"核心问题：{p.get('title','')}")
                    elif isinstance(p, str):
                        parts.append(f"核心问题：{p}")
        if step3_summary.get("confirmedNeeds"):
            needs = step3_summary["confirmedNeeds"]
            if isinstance(needs, list):
                for n in needs:
                    if isinstance(n, dict):
                        parts.append(f"已确认需求：{n.get('title','')}")
                    elif isinstance(n, str):
                        parts.append(f"已确认需求：{n}")
        if step3_summary.get("involvedRoles"):
            roles = step3_summary["involvedRoles"]
            if isinstance(roles, list):
                for r in roles:
                    if isinstance(r, dict):
                        parts.append(f"涉及角色：{r.get('role','')}（{r.get('responsibility','')}）")
                    elif isinstance(r, str):
                        parts.append(f"涉及角色：{r}")
        if step3_summary.get("currentProcess"):
            parts.append("当前流程：" + str(step3_summary["currentProcess"]))
        if step3_summary.get("expectedOutcome"):
            parts.append("期望效果：" + str(step3_summary["expectedOutcome"]))
        if step3_summary.get("phaseOneScope"):
            scope = step3_summary["phaseOneScope"]
            if isinstance(scope, list):
                for s in scope:
                    if isinstance(s, dict):
                        parts.append(f"一期范围：{s.get('item','')}")
                    elif isinstance(s, str):
                        parts.append(f"一期范围：{s}")
        if step3_summary.get("pendingQuestions"):
            qs = step3_summary["pendingQuestions"]
            if isinstance(qs, list):
                for q in qs:
                    if isinstance(q, dict):
                        parts.append(f"待确认问题：{q.get('question','')}")
                    elif isinstance(q, str):
                        parts.append(f"待确认问题：{q}")
        # ---- 旧格式兼容 ----
        if not parts:
            if step3_summary.get("key_requirements"):
                parts.append("关键需求：" + "、".join(step3_summary["key_requirements"]))
            if step3_summary.get("roles_and_responsibilities"):
                roles = step3_summary["roles_and_responsibilities"]
                if isinstance(roles, list):
                    for r in roles:
                        if isinstance(r, dict):
                            parts.append(f"{r.get('role','')}：{r.get('responsibility','')}")
            if step3_summary.get("decision_chain"):
                dc = step3_summary["decision_chain"]
                if dc.get("decision_maker"):
                    parts.append(f"拍板人：{dc['decision_maker']}")
                if dc.get("influencer"):
                    parts.append(f"影响者：{dc['influencer']}")
                if dc.get("executor"):
                    parts.append(f"执行者：{dc['executor']}")
            if step3_summary.get("progress_and_stages"):
                ps = step3_summary["progress_and_stages"]
                if ps.get("current_stage"):
                    parts.append(f"当前阶段：{ps['current_stage']}")
            if step3_summary.get("risk_points"):
                risks = step3_summary["risk_points"]
                if isinstance(risks, list) and risks:
                    risk_texts = []
                    for r in risks:
                        if isinstance(r, dict) and r.get("risk"):
                            risk_texts.append(r["risk"])
                    if risk_texts:
                        parts.append("风险点：" + "、".join(risk_texts))
        step3_summary_text = "\n".join(parts)

    def build_context(prompt_template):
        def json_escape(s):
            if s is None:
                return ""
            return json.dumps(str(s), ensure_ascii=False)[1:-1]  # 去掉首尾引号

        return (prompt_template
            .replace("{customer_name}", json_escape(customer_name))
            .replace("{industry}", json_escape(industry))
            .replace("{scale}", json_escape(scale))
            .replace("{initial_demand}", json_escape(initial_demand))
            .replace("{company_background}", json_escape(company_background))
            .replace("{pain_points}", json_escape(pain_points))
            .replace("{gaps}", json_escape(gaps))
            .replace("{must_ask}", json_escape(must_ask_text))
            .replace("{transcript}", json_escape(transcript) if transcript else "暂无沟通记录")
            .replace("{input_summary}", json_escape(input_summary) if input_summary else "暂无用户已确认输入")
            .replace("{step4_input_draft}", step4_input_draft_str)
            .replace("{step4_report}", step4_report_str or "暂无Step4历史草稿")
            # 传 JSON 字符串，让 Prompt 3 的 AI 自己推理填充空字段
            .replace("{step3_summary}", json.dumps(step3_summary, ensure_ascii=False, indent=2) if step3_summary else "暂无Step3 AI摘要")
            .replace("{kb_match_result}", json_escape(kb_match_result) if kb_match_result else "暂无知识库匹配结果")
            .replace("{xlsx_sheet_summary}", json_escape(xlsx_sheet_summary) if xlsx_sheet_summary else "暂无xlsx交付物摘要")
            .replace("{service_provider_summary}", json_escape(service_provider_summary) if service_provider_summary else "暂无服务商需求总结")
        )

    result = {}

    # ====== Step 1: Prompt 3 → requirementSolutionData ======
    req_prompt = build_context(STEP4_REQUIREMENT_PROMPT)
    req_raw = call_minimax(STEP4_REQUIREMENT_PROMPT, req_prompt, max_tokens=15000)
    requirement_data = parse_json_response(req_raw)
    if not requirement_data:
        return {"success": False, "error": "Prompt 3 生成失败（输出被截断或格式异常），请稍后重试。详情：" + (req_raw[:300] if req_raw else "空响应")}

    result["requirementData"] = requirement_data
    req_json_str = json.dumps(requirement_data, ensure_ascii=False)

    # ====== Step 2: Prompt 4 → Word 内容 ======
    if artifact_type in ("both", "presales", "word"):
        word_prompt = STEP4_WORD_PROMPT.replace("{requirement_data}", req_json_str)
        word_raw = call_minimax(STEP4_WORD_PROMPT, word_prompt, max_tokens=8000)
        word_content = parse_json_response(word_raw)
        if word_content:
            # 质检
            v = validate_requirement_doc(word_content, requirement_data)
            if not v["pass"]:
                return {
                    "success": False,
                    "error": "生成结果未通过质检：\n" + "\n".join(v["errors"]),
                    "validation": v
                }
            result["wordContent"] = word_content

    # ====== Step 3: Prompt 5 → HTML 内容 ======
    if artifact_type in ("both", "html"):
        html_prompt = STEP4_HTML_PROMPT.replace("{requirement_data}", req_json_str)
        html_raw = call_minimax(STEP4_HTML_PROMPT, html_prompt, max_tokens=8000)
        html_content = parse_json_response(html_raw)
        if html_content:
            result["htmlContent"] = html_content

    result["success"] = True
    return result

# ==================== Step5 企业微信智能表格 Schema 生成 ====================

STEP5_SCHEMA_SYSTEM_PROMPT = """你是一个企业微信智能表格搭建专家。请基于需求确认数据中的 smartTableSpec，生成可直接用于建表的 JSON Schema。

请直接输出 JSON，不要任何解释文字，不要 markdown 代码块。"""


STEP5_SCHEMA_USER_PROMPT = """【smartTableSpec（需求结构化中的智能表格规格）】
```json
{smart_table_spec}
```

【scope（交付边界）】
```json
phaseOne：{phase_one_scope}
phaseTwo：{phase_two_scope}
notRecommended：{not_recommended_scope}
```

请严格按以下 JSON Schema 输出（直接输出 JSON，不要任何前缀）：

【重要】每个子表的 sample_records 至少填写 10 条真实业务数据，数据要贴合行业和客户场景，禁止填虚假或无关数据。

{
  "doc_name": "智能表格名称",
  "sheets": [
    {
      "sheet_name": "子表名称",
      "fields": [
        {
          "field_title": "字段名",
          "field_type": "文本|多行文本|单选|多选|数字|金额|日期|日期时间|人员|手机|附件|图片|关联记录|公式|自动编号|进度|勾选|URL",
          "required": true
        }
      ],
      "sample_records": [
        { "字段名": "示例值" },
        { "字段名": "示例值" }
      ]
    }
  ]
}

要求：
1. 只包含 phase = "一期" 的表，不包含二期评估
2. 每个字段的 field_type 必须从上述类型列表中选择
3. 每个子表至少有 2-3 个字段
4. sample_records 填入贴合业务场景的示例值
5. 字段数量不要超过 15 个/表（轻量交付原则）"""


@app.post("/api/step5/generate-demo")
async def generate_step5_demo(body: dict, user: dict = Depends(require_auth)):
    """生成 Step5 企业微信智能表格 JSON Schema（从 Step4 smartTableSpec 派生）"""
    client_id = body.get("client_id")
    if not client_id:
        return {"success": False, "error": "缺少 client_id"}

    client = db_get_client(client_id)
    if not client:
        return {"success": False, "error": "客户不存在"}

    # 从 Step4 产物1的最新版本获取 requirementSolutionData.smartTableSpec
    presales_versions = client.get("step4_presales_versions") or []
    if not presales_versions:
        return {"success": False, "error": "请先生成 Step4 售前方案"}

    latest = presales_versions[-1]
    content = latest.get("content") or {}
    requirement_data = content.get("requirementData")

    if not requirement_data:
        return {"success": False, "error": "Step4 产物中无 requirementData，请重新生成售前方案"}

    smart_table_spec = requirement_data.get("smartTableSpec") or {}
    scope = requirement_data.get("scope") or {}

    if not smart_table_spec:
        return {"success": False, "error": "Step4 产物中无 smartTableSpec，请重新生成售前方案"}

    user_prompt = STEP5_SCHEMA_USER_PROMPT.replace(
        "{smart_table_spec}", json.dumps(smart_table_spec, ensure_ascii=False, indent=2)
    ).replace(
        "{phase_one_scope}", json.dumps(scope.get("phaseOne") or [], ensure_ascii=False, indent=2)
    ).replace(
        "{phase_two_scope}", json.dumps(scope.get("phaseTwo") or [], ensure_ascii=False, indent=2)
    ).replace(
        "{not_recommended_scope}", json.dumps(scope.get("notRecommended") or [], ensure_ascii=False, indent=2)
    )

    raw = call_minimax(STEP5_SCHEMA_SYSTEM_PROMPT, user_prompt, max_tokens=15000)
    schema = parse_json_response(raw)

    if not schema:
        return {"success": False, "error": "Step5 Schema 生成失败：" + (raw[:200] if raw else "空响应")}

    # 保存 JSON Schema 到 client
    db_update_client(client_id, {"step5_schema": schema})

    return {"success": True, "demo": schema}


STEP5_AGENT_PROMPT = """你是一个企业微信智能表格 AI 增强专家。基于已有的智能表格 Schema，为服务商提供进一步 AI 化的建议。

【客户背景】
客户名称：{customer_name}
行业：{industry}
需求：{initial_demand}

【现有智能表格 Schema（已规划的一期交付内容）】
{schema_summary}

请生成 4-6 条"若要加强 AI 化，可以考虑..."的建议，每条包含：
- title：建议标题（如"引入 AI 自动汇总"）
- description：2-3 句话说明实现方式和价值
- example：该建议在当前客户场景中的具体应用示例（如"在【项目状态】表中，字段值变为'待验收'时，自动推送企微消息给项目经理"）
- difficulty：实现难度（低/中/高）
- phase：建议时机（一期/二期/远期）

直接输出 JSON 数组，不要 markdown 代码块，不要任何前缀文字。"""


@app.post("/api/step5/agent-suggest")
async def step5_agent_suggest(body: dict, user: dict = Depends(require_auth)):
    """生成 Step5 AI 增强建议"""
    client_id = body.get("client_id")
    if not client_id:
        return {"success": False, "error": "缺少 client_id"}

    client = db_get_client(client_id)
    if not client:
        return {"success": False, "error": "客户不存在"}

    # 获取 schema 和需求数据
    schema = client.get("step5_schema")
    if isinstance(schema, str):
        try:
            schema = json.loads(schema)
        except:
            schema = {}

    # 构建 schema 摘要用于 prompt
    sheets = schema.get("sheets") or []
    schema_lines = []
    for s in sheets:
        name = s.get("sheet_name", "未命名")
        fields = s.get("fields") or []
        field_names = [f.get("field_title", "") for f in fields]
        schema_lines.append(f"- {name}：{', '.join(field_names)}")
    schema_summary = "\n".join(schema_lines) if schema_lines else "暂无子表"

    customer_name = client.get("name", "")
    industry = client.get("industry", "")
    initial_demand = client.get("initial_demand", "")

    user_prompt = STEP5_AGENT_PROMPT.format(
        customer_name=customer_name,
        industry=industry,
        initial_demand=initial_demand,
        schema_summary=schema_summary
    )

    raw = call_minimax(STEP5_AGENT_PROMPT, user_prompt, max_tokens=4000)
    if raw.startswith("Error:"):
        return {"success": False, "error": raw}

    suggestions = parse_json_response(raw)
    if not suggestions:
        return {"success": False, "error": "AI 返回格式异常，请重试"}

    # 保存到后端
    db_update_client(client_id, {"step5_agent_suggestions": suggestions})

    return {"success": True, "suggestions": suggestions}


# ==================== 创建企业微信智能表格（从 smartTableSpec） ====================

# 字段类型映射：我们的规范 → WeCom field_type id
FIELD_TYPE_MAP = {
    # WeCom API 格式（FIELD_TYPE_ 前缀）
    "文本": "FIELD_TYPE_TEXT",
    "多行文本": "FIELD_TYPE_TEXT",
    "单选": "FIELD_TYPE_SINGLE_SELECT",
    "多选": "FIELD_TYPE_SELECT",
    "数字": "FIELD_TYPE_NUMBER",
    "金额": "FIELD_TYPE_CURRENCY",
    "日期": "FIELD_TYPE_DATE_TIME",
    "日期时间": "FIELD_TYPE_DATE_TIME",
    "人员": "FIELD_TYPE_USER",
    "附件": "FIELD_TYPE_ATTACHMENT",
    "图片": "FIELD_TYPE_IMAGE",
    "关联记录": "FIELD_TYPE_TEXT",
    "公式": "FIELD_TYPE_TEXT",
    "自动编号": "FIELD_TYPE_TEXT",
    "进度": "FIELD_TYPE_PROGRESS",
    "勾选": "FIELD_TYPE_CHECKBOX",
    "URL": "FIELD_TYPE_URL",
    # 别名
    "text": "FIELD_TYPE_TEXT",
    "number": "FIELD_TYPE_NUMBER",
    "currency": "FIELD_TYPE_CURRENCY",
    "date": "FIELD_TYPE_DATE_TIME",
    "datetime": "FIELD_TYPE_DATE_TIME",
    "contact": "FIELD_TYPE_USER",
    "file": "FIELD_TYPE_ATTACHMENT",
    "checkbox": "FIELD_TYPE_CHECKBOX",
    "percent": "FIELD_TYPE_PERCENTAGE",
}


def _map_field_type(ft: str) -> str:
    """将字段类型字符串映射为 WeCom field_type 枚举值"""
    ft = ft.strip()
    return FIELD_TYPE_MAP.get(ft, "FIELD_TYPE_TEXT")  # 默认文本


@app.post("/api/create")
async def create_wecom_sheet(body: dict, user: dict = Depends(require_auth)):
    """
    基于 smartTableSpec 创建企业微信智能表格（包含完整字段和样例数据）。

    body = {
        "client_id": 71,
        "smartTableSpec": {
            "confirmedTables": [...],
            "fieldsByTable": [...],
            "sheets": [...]  // 直接包含 sheets/fields/sample_records 结构
        }
    }
    """
    import re

    client_id = body.get("client_id")
    spec = body.get("smartTableSpec") or {}

    if not client_id:
        return {"success": False, "error": "缺少 client_id"}

    # 支持两种结构：
    # 1. confirmedTables + fieldsByTable（旧结构）
    # 2. sheets 直接包含字段和样例数据（新结构，来自 step5_schema）
    confirmed_tables = spec.get("confirmedTables") or []
    fields_by_table = spec.get("fieldsByTable") or []
    sheets_data = spec.get("sheets") or []  # 直接的 sheets 结构
    fields_map = {f.get("tableName", ""): f.get("fields", []) for f in fields_by_table}

    # ---- 1. 创建智能表格文档 ----
    client = db_get_client(client_id)
    doc_name = (client.get("name", "") if client else "") + " - 需求智能表格"
    create_resp = call_mcp("create_doc", {
        "doc_name": doc_name,
        "doc_type": 10  # 智能表格
    })
    if create_resp.get("error"):
        return {"success": False, "error": "创建文档失败：" + create_resp["error"]}

    docid = create_resp.get("docid", "")
    doc_url = create_resp.get("url", "")
    if not docid:
        return {"success": False, "error": "创建文档失败，未返回 docid"}

    created_sheets = []

    # ---- 2. 获取默认子表的 sheet_id ----
    sheet_resp = call_mcp("smartsheet_get_sheet", {"docid": docid})
    if sheet_resp.get("error"):
        return {"success": False, "error": "获取子表失败：" + sheet_resp["error"]}
    sheets = sheet_resp.get("sheet_list", []) or sheet_resp.get("sheets", []) or []
    if not sheets:
        return {"success": False, "error": "未找到子表"}
    first_sheet_id = sheets[0].get("sheet_id", "")

    # ---- 2b. 获取默认子表的字段（含默认 field_id）----
    fields_resp = call_mcp("smartsheet_get_fields", {"docid": docid, "sheet_id": first_sheet_id})
    default_field_id = ""
    if not fields_resp.get("error") and fields_resp.get("fields"):
        default_field_id = fields_resp["fields"][0].get("field_id", "")

    # ---- 3a. 使用 sheets 结构（直接包含字段和样例数据）----
    if sheets_data:
        for idx, sheet in enumerate(sheets_data):
            sheet_name = sheet.get("sheet_name", f"子表{idx + 1}")
            fields_list = sheet.get("fields") or []
            sample_records = sheet.get("sample_records") or []

            if idx == 0:
                # ---- 用默认子表 ----
                sheet_id = first_sheet_id
                # 重命名默认字段（需要真实的 field_id）
                if fields_list and default_field_id:
                    first_field = fields_list[0]
                    first_ft = _map_field_type(first_field.get("field_type") or first_field.get("fieldType") or "文本")
                    call_mcp("smartsheet_update_fields", {
                        "docid": docid,
                        "sheet_id": sheet_id,
                        "fields": [{"field_title": first_field.get("field_title") or first_field.get("fieldName") or "", "field_id": default_field_id, "field_type": first_ft}]
                    })
                    # 添加其余字段
                    if len(fields_list) > 1:
                        add_fields = [{"field_title": f.get("field_title") or f.get("fieldName") or "", "field_type": _map_field_type(f.get("field_type") or f.get("fieldType") or "文本")} for f in fields_list[1:]]
                        call_mcp("smartsheet_add_fields", {"docid": docid, "sheet_id": sheet_id, "fields": add_fields})
                # 重命名子表
                call_mcp("smartsheet_update_sheet", {"docid": docid, "properties": {"sheet_id": sheet_id, "title": sheet_name}})
                # 添加样例数据（需包装为 {"values": {...}}）
                if sample_records:
                    records_formatted = [{"values": rec} for rec in sample_records]
                    call_mcp("smartsheet_add_records", {"docid": docid, "sheet_id": sheet_id, "records": records_formatted})
            else:
                # ---- 新增子表 ----
                add_sheet_resp = call_mcp("smartsheet_add_sheet", {"docid": docid})
                if add_sheet_resp.get("error"):
                    continue
                new_props = add_sheet_resp.get("properties", {})
                new_sheet_id = new_props.get("sheet_id", "") or (add_sheet_resp.get("sheet_list", [{}])[0].get("sheet_id", "") if add_sheet_resp.get("sheet_list") else "") or ""
                if not new_sheet_id:
                    continue
                sheet_id = new_sheet_id
                # 获取新子表的默认 field_id
                new_fields_resp = call_mcp("smartsheet_get_fields", {"docid": docid, "sheet_id": sheet_id})
                new_default_field_id = ""
                if not new_fields_resp.get("error") and new_fields_resp.get("fields"):
                    new_default_field_id = new_fields_resp["fields"][0].get("field_id", "")
                # 重命名 + 设字段
                if fields_list and new_default_field_id:
                    first_field = fields_list[0]
                    first_ft = _map_field_type(first_field.get("field_type") or first_field.get("fieldType") or "文本")
                    call_mcp("smartsheet_update_fields", {
                        "docid": docid,
                        "sheet_id": sheet_id,
                        "fields": [{"field_title": first_field.get("field_title") or first_field.get("fieldName") or "", "field_id": new_default_field_id, "field_type": first_ft}]
                    })
                    if len(fields_list) > 1:
                        add_fields = [{"field_title": f.get("field_title") or f.get("fieldName") or "", "field_type": _map_field_type(f.get("field_type") or f.get("fieldType") or "文本")} for f in fields_list[1:]]
                        call_mcp("smartsheet_add_fields", {"docid": docid, "sheet_id": sheet_id, "fields": add_fields})
                # 重命名子表
                call_mcp("smartsheet_update_sheet", {"docid": docid, "properties": {"sheet_id": sheet_id, "title": sheet_name}})
                # 添加样例数据（需包装为 {"values": {...}}）
                if sample_records:
                    records_formatted = [{"values": rec} for rec in sample_records]
                    call_mcp("smartsheet_add_records", {"docid": docid, "sheet_id": sheet_id, "records": records_formatted})

            created_sheets.append(sheet_name)

    # ---- 3b. 使用 confirmedTables + fieldsByTable 结构（兼容旧）----
    elif confirmed_tables:
        for idx, table in enumerate(confirmed_tables):
            table_name = table.get("tableName", f"子表{idx + 1}")
            phase = table.get("phase", "一期")
            if phase != "一期":
                continue

            fields_def = fields_map.get(table.get("tableName", ""), [])

            if idx == 0:
                sheet_id = first_sheet_id
                if fields_def:
                    first_field = fields_def[0]
                    first_ft = _map_field_type(first_field.get("fieldType", "文本"))
                    call_mcp("smartsheet_update_fields", {
                        "docid": docid,
                        "sheet_id": sheet_id,
                        "fields": [{"field_title": first_field.get("fieldName", ""), "field_id": default_field_id, "field_type": first_ft}]
                    })
                    if len(fields_def) > 1:
                        add_fields = [{"field_title": f.get("fieldName", ""), "field_type": _map_field_type(f.get("fieldType", "文本"))} for f in fields_def[1:]]
                        call_mcp("smartsheet_add_fields", {"docid": docid, "sheet_id": sheet_id, "fields": add_fields})
                call_mcp("smartsheet_update_sheet", {"docid": docid, "properties": {"sheet_id": sheet_id, "title": table_name}})
            else:
                add_sheet_resp = call_mcp("smartsheet_add_sheet", {"docid": docid})
                if add_sheet_resp.get("error"):
                    continue
                new_props = add_sheet_resp.get("properties", {})
                new_sheet_id = new_props.get("sheet_id", "") or (add_sheet_resp.get("sheet_list", [{}])[0].get("sheet_id", "") if add_sheet_resp.get("sheet_list") else "") or ""
                if not new_sheet_id:
                    continue
                sheet_id = new_sheet_id
                # 获取新子表的默认 field_id
                new_fields_resp = call_mcp("smartsheet_get_fields", {"docid": docid, "sheet_id": sheet_id})
                new_default_field_id = ""
                if not new_fields_resp.get("error") and new_fields_resp.get("fields"):
                    new_default_field_id = new_fields_resp["fields"][0].get("field_id", "")
                if fields_def and new_default_field_id:
                    first_field = fields_def[0]
                    first_ft = _map_field_type(first_field.get("fieldType", "文本"))
                    call_mcp("smartsheet_update_fields", {
                        "docid": docid,
                        "sheet_id": sheet_id,
                        "fields": [{"field_title": first_field.get("fieldName", ""), "field_id": new_default_field_id, "field_type": first_ft}]
                    })
                    if len(fields_def) > 1:
                        add_fields = [{"field_title": f.get("fieldName", ""), "field_type": _map_field_type(f.get("fieldType", "文本"))} for f in fields_def[1:]]
                        call_mcp("smartsheet_add_fields", {"docid": docid, "sheet_id": sheet_id, "fields": add_fields})
                call_mcp("smartsheet_update_sheet", {"docid": docid, "properties": {"sheet_id": sheet_id, "title": table_name}})

            created_sheets.append(table_name)

    return {
        "success": True,
        "docid": docid,
        "url": doc_url,
        "sheets": created_sheets
    }


@app.post("/api/create_doc")
async def create_wecom_doc(body: dict, user: dict = Depends(require_auth)):
    """
    创建企业微信智能文档（smartpage）并写入 Markdown 内容。
    body = {
        "client_id": 71,
        "doc_name": "文档标题",
        "content": "# Markdown 内容..."
    }
    """
    client_id = body.get("client_id")
    doc_name = body.get("doc_name", "未命名文档")
    content = body.get("content", "")

    if not client_id:
        return {"success": False, "error": "缺少 client_id"}

    # 使用 smartpage_create 创建智能文档（不是 create_doc，那是智能表格）
    pages = [{"page_title": "内容" if not doc_name else doc_name, "page_content": content, "content_type": 1}]
    create_resp = call_mcp("smartpage_create", {"title": doc_name, "pages": pages})
    if create_resp.get("error"):
        return {"success": False, "error": "创建文档失败：" + create_resp["error"]}
    docid = create_resp.get("docid", "")
    doc_url = create_resp.get("url", "")
    if not docid:
        return {"success": False, "error": "创建文档失败，未返回 docid"}

    return {"success": True, "docid": docid, "url": doc_url}


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

    result = call_minimax(AGENT_DEMO_SYSTEM_PROMPT, user_prompt, max_tokens=8000)

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


PROFILE_GENERATE_PROMPT = """你是一个售前顾问。根据客户基本信息，生成一份结构化的客户画像摘要。

直接返回 JSON（不要 markdown 代码块），格式：
{
  "summary": "50字以内的客户画像一句话描述",
  "background": "公司背景描述，80字以内",
  "pain_points": ["核心痛点1", "核心痛点2", "核心痛点3"],
  "scale": "公司规模判断，如：200-1000人中大型企业",
  "tags": ["标签1", "标签2", "标签3"]
}"""

@app.post("/api/profile/generate")
async def generate_profile(body: dict, user: dict = Depends(require_auth)):
    """生成客户画像摘要"""
    company_name = body.get("company_name", "")
    industry = body.get("industry", "")
    initial_demand = body.get("initial_demand", "")
    if not company_name:
        return {"error": "缺少客户名称"}
    user_prompt = f"客户名称：{company_name}\n行业：{industry or '未指定'}\n原始需求：{initial_demand or '暂无'}\n请生成客户画像 JSON。"
    raw = call_minimax(PROFILE_GENERATE_PROMPT, user_prompt, max_tokens=1000)
    if raw.startswith("Error:"):
        return {"error": raw}
    result = parse_json_response(raw)
    if not result:
        return {"error": "AI 返回格式异常，请重试"}
    return result


# ==================== 健康检查 ====================

COMPANY_SEARCH_PROMPT = """你是一个企业信息分析助手。根据客户名称和行业，生成公司简介、主要客户群体、可能关注点。

直接返回 JSON（不要 markdown 代码块），格式：
{
  "company_type": "公司类型描述，如：制造业龙头民营企业",
  "main_customers": "主要客户群体描述，如：大型三甲医院、政府机构",
  "possible_focus": "可能关注点，用/分隔，如：提升审批效率/降低运营成本/数据打通",
  "company_intro": "20字以内的公司简介"
}"""

@app.post("/api/company_search")
async def company_search(body: dict, user: dict = Depends(require_auth)):
    """AI 智搜：根据客户名称和行业生成公司简介"""
    company_name = body.get("company_name", "")
    industry = body.get("industry", "")
    if not company_name:
        return {"error": "缺少公司名称"}
    user_prompt = f"客户名称：{company_name}\n行业：{industry or '未指定'}\n请分析生成 JSON。"
    raw = call_minimax(COMPANY_SEARCH_PROMPT, user_prompt, max_tokens=800)
    if raw.startswith("Error:"):
        return {"error": raw}
    result = parse_json_response(raw)
    if not result:
        return {"error": "AI 返回格式异常，请重试"}
    return result


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
