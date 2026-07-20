# 技能 A: 售前报告

## 功能

生成**售前解决方案报告**（HTML 格式）。

## 触发

用户说"生成售前报告"或选择"售前报告"技能时触发。

## 前置条件

当前上下文必须有：
- Step 1 的客户档案（`profile_json`）
- Step 2 的 MD 题纲（`md_outline`）
- Step 3 的沟通记录（`meeting_notes`）

## Token 预估

在生成前，调用 `estimate_tokens()` 函数计算预估 Token 和费用：

```
预估 Token = estimate_tokens(客户档案JSON + 沟通纪要 + 沟通记录)
预估费用 = estimate_cost(预估 Token)
```

如果预估 Token > 3000，先展示预警：

```
⚠️ 生成售前报告预估消耗：
- Token 预估：{n}
- 费用预估：¥{x}

确认生成吗？回复"确认"继续。
```

## 生成流程

### 1. 收集上下文

从当前会话提取：

```
客户名称：{client_name}
行业：{industry}
规模：{scale}
客户档案：{profile_json}
沟通纪要：{md_outline}
沟通记录：{meeting_notes}
```

### 2. 估算 Token 和费用

使用 `estimate_tokens()` 函数计算：

```
预估 Token = estimate_tokens(客户档案JSON + 沟通纪要 + 沟通记录)
预估费用 = estimate_cost(预估 Token)
```

如果预估 Token > 3000，先展示预警：

```
⚠️ 生成售前报告预估消耗：
- Token 预估：{n}
- 费用预估：¥{x}

确认生成吗？回复"确认"继续。
```

### 3. 生成 JSON 数据

**System Prompt:**

```
你是一个企业微信定制开发售前方案顾问。请基于以下需求数据，生成一份结构化的售前解决方案 JSON 数据。

要求：
1. 只输出 JSON，不输出任何解释或 markdown 代码块
2. JSON 结构必须包含：
   - client_name: 客户名称
   - industry: 行业
   - scale: 规模
   - tags: 标签数组
   - profile_json: 客户档案（直接透传）
   - solutions: 解决方案数组，每个包含 title/description/modules
   - implementation_plan: 实施计划数组，每个包含 name/description/timeline
   - gaps: 待确认问题数组（从 profile_json.part2.gaps 提取）

3. solutions 至少 3 个模块，implementation_plan 至少 2 个阶段
```

**User Prompt:**

```
客户名称：{client_name}
行业：{industry}
规模：{scale}

客户档案（JSON）：
{profile_json}

沟通纪要：
{md_outline}

沟通记录：
{meeting_notes}

请生成售前解决方案 JSON 数据。
```

### 4. 渲染 HTML

将 AI 返回的 JSON 数据发送到后端渲染：

```
POST https://sining.cloud/api/skill/render
X-API-Key: {用户的APIKey}
Content-Type: application/json

{
  "type": "sales",
  "data": { AI 返回的 JSON 数据 }
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

### 5. 部署

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

### 6. 展示结果

展示给用户：

```
✅ 售前报告已生成！

📄 访问链接：https://sining.cloud/reports/{id}_sales.html

（此链接同时保存到您的客户档案中）
```

## HTML 模板参考

生成的 HTML 应包含以下样式：

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; color: #162033; background: #f5f7fb; }
    .container { max-width: 800px; margin: 0 auto; padding: 20px; }
    .card { background: #fff; border-radius: 16px; padding: 24px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
    h1 { color: #1263e6; font-size: 24px; }
    h2 { color: #182235; font-size: 18px; border-bottom: 2px solid #1263e6; padding-bottom: 8px; }
    .tag { display: inline-block; background: #eef6ff; color: #1263e6; padding: 4px 12px; border-radius: 20px; font-size: 12px; margin-right: 8px; }
    .pain-item { background: #f8fafc; border-radius: 12px; padding: 14px; margin-bottom: 10px; }
    .module { border: 1px solid #e8edf5; border-radius: 14px; padding: 16px; margin-bottom: 12px; }
    .module h3 { color: #1263e6; margin: 0 0 8px; }
    table { width: 100%; border-collapse: collapse; }
    th { background: #f1f8ff; color: #1e477d; padding: 10px; text-align: left; font-size: 13px; }
    td { padding: 10px; border-bottom: 1px solid #eef2f7; font-size: 13px; }
  </style>
</head>
<body>
  <div class="container">
    <!-- 内容 -->
  </div>
</body>
</html>
```
