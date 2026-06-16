# Provider Assist 项目记忆文档

## 项目背景

**项目名称**: Provider Assist - 服务商需求调研助手
**路径**: /Users/laixiangjun/provider-assist-optimized/
**用户**: 服务商（Provider），用于辅助售前需求调研

### 核心流程（5步）
1. **Step1**: 服务商录入客户行业+痛点 → AI生成提问清单（Part1公司背景+痛点、Part2缺失信息、Part3提问清单11条）
2. **Step2**: 沟通记录上传（文件上传+粘贴文字可并存），每条可编辑/删除
3. **Step3**: 点按钮 → AI生成需求分析报告（JSON格式）→ 智能解析 → 渲染到编辑区
4. **Step4**: 点按钮 → 后端改prompt输出JSON → 智能解析 → 渲染到编辑区（Demo设计）
5. **Step5**: Markdown预览 + v22可视化Demo + 创建企微智能表格(/api/create)

### UI风格（v22，已确认）
- 配色：蓝色 `#1263e6` + 绿色 `#13b96f`
- 布局：3栏 `236px + minmax(620px,1fr) + 356px`
- 全部5步支持在线编辑（contenteditable）
- 数据：核心存后端，UI草稿存localStorage
- 登录后：单客户直接进工作台，多客户进列表页
- 退出按钮：工作台不显示，只在客户列表页

---

## 项目结构

```
provider-assist-optimized/
├── backend/
│   ├── main.py              # FastAPI后端（主后端）
│   ├── database.py          # SQLite数据库
│   ├── auth.py              # JWT认证+受邀码验证
│   ├── wecom_creator.mjs    # 企微智能表格创建
│   └── provider_assist.db    # SQLite数据库
├── api-vercel/              # Vercel Serverless Functions（参考）
├── knowledge/                # 知识库（17行业+17案例+10模板+672需求）
├── login.html                # 登录注册页
├── client_list.html          # 客户列表页
├── workbench.html            # 工作台主入口（Phase 1完成，1429行）
├── demo_full.html            # 旧版备份（1934行）
├── PROJECT_DOC.md            # 完整项目文档
└── docker-compose.yml
```

---

## 技术方案

### 后端架构
- **框架**: FastAPI + SQLite（未来可迁PostgreSQL）
- **认证**: JWT Token（HMAC实现）
- **部署**: Docker容器化

### 数据库表
- `users` - 用户
- `clients` - 客户
- `provider_knowledge` - 服务商知识库
- `invitation_codes` - 受邀码
- `reports` - 报告

### 企微集成
- MCP API Key: `S0RW0Ke7TfR0_NcWgTXq2Ht_BColuWjRzRVM9LMO3jHoIdKwI3gEPiNPnNxgkiPqhNXtAtM1_86okTOj8R5R8Q`

### DeepSeek集成
- API Key: `sk-63d4e005ecb646b08538368c5172ed82`

---

## Phase 2 待完成功能（Task #2）

### Step1 - AI结果只读 + 实时自动保存
- [ ] AI生成结果只读展示
- [ ] 用户可在线编辑（contenteditable）
- [ ] 实时自动保存到localStorage（草稿）
- [ ] 右侧制品区：展示 + 复制/导出 + 删除

### Step2 - 沟通记录管理
- [ ] 文件上传（.docx/.txt）→ 解析文本
- [ ] 粘贴文字输入
- [ ] 多条记录可并存
- [ ] 每条可编辑/删除
- [ ] 保存到后端client记录

### Step3 - 需求报告生成
- [ ] 点按钮触发 `/api/reports/generate`
- [ ] 后端已改prompt输出JSON（已完成）
- [ ] 前端JSON解析 + 渲染到编辑区
- [ ] 在线编辑报告内容

### Step4 - Demo设计生成
- [ ] 点按钮触发AI生成
- [ ] 后端改prompt输出JSON（需确认）
- [ ] 前端JSON解析 + 渲染编辑区

### Step5 - 企微智能表格
- [ ] Markdown格式预览
- [ ] v22风格可视化Demo展示
- [ ] `/api/create` 创建企微智能表格
- [ ] 仪表盘/Gantt等高级功能

### 登录后流程
- [ ] 单客户 → 直接进工作台
- [ ] 多客户 → 进列表页
- [ ] 退出按钮：只在客户列表页显示

---

## 已完成功能

### 后端API（backend/main.py）
- ✅ 认证: `/api/auth/register`, `/api/auth/login`, `/api/auth/me`, `/api/auth/auto-login`
- ✅ 客户: `/api/clients` CRUD
- ✅ 知识库: `/api/knowledge/search`, `/api/knowledge/global`
- ✅ 服务商知识库: `/api/provider-knowledge` CRUD
- ✅ 提问清单: `/api/question_list` - JSON格式输出
- ✅ 需求报告: `/api/reports/generate` - JSON格式输出
- ✅ 知识匹配: `/api/match`
- ✅ 企微文档: `/api/export_doc`
- ✅ 文件上传: `/api/upload`
- ✅ 上报管理: `/api/report`
- ✅ 公司搜索: `/api/company_search`
- ✅ 创建Demo: `/api/create` - 创建企微智能表格

### 前端
- ✅ login.html - 登录注册页
- ✅ client_list.html - 客户列表页
- ✅ workbench.html - 工作台UI框架（Phase 1完成）

---

## 测试账号

| 服务商名称 | 受邀码 | 状态 |
|-----------|--------|------|
| 测试服务商A | PROV2026001 | 已使用 |
| 测试服务商B | PROV2026002 | 可用 |
| 上海数字科技 | PROV2026003 | 可用 |
| 深圳智能服务 | PROV2026004 | 可用 |
| 北京企业服务 | PROV2026005 | 可用 |

---

## 启动命令

```bash
# 终端1: 后端
cd /Users/laixiangjun/provider-assist-optimized/backend
python3 main.py

# 终端2: 前端
cd /Users/laixiangjun/provider-assist-optimized
python3 -m http.server 8080

# 浏览器访问
http://localhost:8080/login.html
```

---

## 最近更新
2026-06-15 - 更新MEMORY.md，梳理Phase 2待完成任务
