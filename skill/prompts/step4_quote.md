# 技能 C: 报价方案

## 功能

生成**报价方案**（HTML 格式）。

## 触发

用户说"生成报价方案"或"生成报价"或选择"报价"技能时触发。

## 前置条件

同售前报告技能 A。

## Token 预估

```
预估 Token = (输入长度 + Prompt Token) × 1.2
预估费用 = 预估 Token ÷ 1000 × 0.001（元）
```

如果预估 Token > 3000，先展示预警：

```
⚠️ 生成报价方案预估消耗：
- Token 预估：{n}
- 费用预估：¥{x}

确认生成吗？回复"确认"继续。
```

## 生成流程

### 1. 生成内容

**System Prompt:**

```
你是一个企业微信定制开发报价方案顾问。请基于以下需求数据，生成一份清晰的报价方案 HTML 页面。

要求：
1. 输出完整的、可直接在浏览器打开的 HTML
2. 风格简洁、清晰，使用内联 CSS
3. 内容结构：
   - 报价概览（总价区间）
   - 分模块报价明细
   - 一期/二期分阶段报价
   - 实施服务费说明
   - 付款方式建议
   - 注意事项

4. 报价要基于合理的行业标准
5. 不要生成 JSON，直接输出 HTML 内容。
```

**User Prompt:**

```
客户名称：{client_name}
行业：{industry}
规模：{scale}

需求摘要：
{requirement_summary}

一期模块推荐：
{module_recommendation}

请生成报价方案 HTML 页面。
```

### 2. 部署

```
POST https://sining.cloud/api/skill/reports
{
  "type": "quote",
  "client_name": "{client_name}",
  "html": "<html>...</html>"
}
```

返回：
```json
{
  "url": "https://sining.cloud/reports/{id}_quote.html",
  "id": "{id}"
}
```

### 3. 展示结果

```
✅ 报价方案已生成！

📄 访问链接：https://sining.cloud/reports/{id}_quote.html

（此链接同时保存到您的客户档案中）
```
