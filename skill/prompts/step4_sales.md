# 技能 A: 售前报告

## 功能

调用 SaaS 真实 API 生成**售前解决方案报告**（HTML 格式）。

## 触发

用户说"生成售前报告"或选择"售前报告"技能时触发。

## 前置条件

当前上下文必须有：
- Step 1 的客户档案（`profile_json`）
- Step 2 的 MD 题纲（`md_outline`）
- Step 3 的沟通记录（`meeting_notes`）
- 有效的 `access_token`（登录后获得）

## 生成流程

### 1. 收集上下文

从当前会话提取：

```
客户名称：{client_name}
行业：{industry}
沟通记录：{meeting_notes（合并成一段）}
```

### 2. 调用 SaaS API 生成报告

使用登录后获得的 `access_token`，调用 SaaS 真实 API：

```
POST https://sining.cloud/api/reports/generate
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "transcript": "{meeting_notes 合并的沟通记录}",
  "industry": "{industry}",
  "output_type": "report"
}
```

API 返回结构化的需求分析报告（JSON）。

### 3. 渲染 HTML

将 SaaS 返回的报告 JSON 发送到后端渲染：

```
POST https://sining.cloud/api/skill/render
X-API-Key: {用户的APIKey}
Content-Type: application/json

{
  "type": "sales",
  "data": { SaaS API 返回的 JSON }
}
```

API 返回：
```json
{
  "success": true,
  "html": "<html>...</html>",
  "type": "sales"
}
```

### 4. 上传部署

将返回的 HTML 上传到报告服务：

```
POST https://sining.cloud/api/skill/reports
X-API-Key: {用户的APIKey}
Content-Type: application/json

{
  "type": "sales",
  "client_name": "{client_name}",
  "html": "<html>...</html>"
}
```

API 返回：
```json
{
  "url": "https://sining.cloud/reports/{id}_sales.html",
  "id": "{id}"
}
```

### 5. 展示结果

展示给用户：

```
✅ 售前报告已生成！

📄 访问链接：https://sining.cloud/reports/{id}_sales.html

（此链接同时保存到您的客户档案中）
```

## 错误处理

- 如果 `/api/reports/generate` 返回 401，说明 access_token 已过期，需要重新登录
- 如果渲染失败，使用 SaaS API 返回的原始内容展示
- 网络错误时提示用户重试
