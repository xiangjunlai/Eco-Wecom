# Provider Assist Skill 版本历史

所有版本采用 **语义化版本**：`主版本.次版本.修订号`

## [2.1.0] 2026-07-20

### 新增
- **`/api/skill/login` 接口**：解析 API Key（格式 `{受邀码}:{用户名}:{user_id}`）+ 密码验证
- **`/api/skill/render` 接口**：AI 生成 JSON → 后端 Jinja2 模板渲染 HTML
- **`estimate_tokens()` 函数**：使用 tiktoken 准确估算 Token 数量
- **`estimate_cost()` 函数**：估算 API 调用费用

### 改动
- **API Key 格式更新**：从纯受邀码改为 `{受邀码}:{用户名}:{user_id}`，支持用户级识别
- **注册接口**：改用 `/api/auth/register`（复用现有系统）
- **登录接口**：Skill 端改用 `/api/skill/login`（新增接口）
- **报告生成流程**：AI 输出 JSON → `/api/skill/render` 渲染 HTML → `/api/skill/reports` 上传

---

## [2.0.0] 2026-07-18

### 新增
- **对话式交互流程**：Skill 安装后自动判断新/老用户，全流程对话引导
- **`/api/skill/register`** 接口：新用户注册（受邀码+公司名+姓名+密码）
- **`/api/skill/login`** 接口：老用户 API Key 验证
- **小秋角色**：引入 AI 助手"小秋"全程热情引导

### 改动
- skill.md 从"纯说明书"改为"对话式 Agent 流程"
- 新用户首次安装有粘贴内容 → 自动识别并注册
- 无粘贴内容 → 对话询问新/老用户，再走对应流程

---

## [1.0.0] 2026-07-14

### 初始版本
- 支持 `/xiaoqiu` 触发售前流程
- Step1-5 完整工作流
- `/clean`、`/memory` 命令
- `/api/skill/submit`、`/api/skill/reports`、`/api/skill/prompts/{step}` 接口
