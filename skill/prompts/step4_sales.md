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

在生成前，计算预估 Token 和费用：

```
输入长度 = 客户档案字数 + 沟通记录字数 + MD题纲字数
Prompt Token ≈ {prompt_length}（固定）
预估 Token = (输入长度 + Prompt Token) × 1.2（考虑 JSON 输出）
预估费用 = 预估 Token ÷ 1000 × 0.001（元）
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

### 2. 生成 HTML

**System Prompt:**

```
你是一个企业微信定制开发售前方案顾问。请基于以下需求数据，生成一份客户友好的售前解决方案 HTML 页面。

要求：
1. 输出完整的、可直接在浏览器打开的 HTML（包含 <html><head><body>）
2. 风格专业、现代，使用内联 CSS（不要外部依赖）
3. 内容结构：
   - 封面（客户名称、方案标题、日期）
   - 客户画像与痛点
   - 需求理解与优先级
   - 解决方案模块推荐
   - 实施计划与价值
   - 待确认问题

4. 不要生成 JSON，直接输出 HTML 内容。
5. HTML 存放在 sining.cloud/reports/ 目录下。
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

请生成售前解决方案 HTML 页面。
```

### 3. 部署

生成 HTML 后，通过 API 部署：

```
POST https://sining.cloud/api/skill/reports
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

### 4. 展示结果

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
