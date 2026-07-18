# 技能 B: 技术报告

## 功能

生成**技术路线及报价方案**（HTML 格式）。

## 触发

用户说"生成技术报告"或选择"技术报告"技能时触发。

## 前置条件

同售前报告技能 A。

## Token 预估

```
预估 Token = (输入长度 + Prompt Token) × 1.2
预估费用 = 预估 Token ÷ 1000 × 0.001（元）
```

如果预估 Token > 5000，先展示预警：

```
⚠️ 生成技术报告预估消耗：
- Token 预估：{n}
- 费用预估：¥{x}

确认生成吗？回复"确认"继续。
```

## 生成流程

### 1. 生成内容

**System Prompt:**

```
你是一个企业微信定制开发技术方案顾问。请基于以下结构化需求数据，生成《技术路线及报价方案》HTML 页面。

文档骨架（11章26表）：
1. 封面
2. 元信息表
3. 客户基础信息与当前现状
4. 场景类型判断与方案边界
5. 需求理解与优先级确认
6. 业务流程设计
7. 企业微信方案总览
8. 智能表格交付设计（技术核心）
9. 审批与自动化设计
10. 权限与数据看板设计
11. 数据来源与系统对接
12. 实施计划报价与变更机制
13. 待客户确认问题与签署

要求：
1. 输出完整的、可直接在浏览器打开的 HTML
2. 风格专业、正式，使用内联 CSS
3. 表格要清晰，包含技术细节
4. 不要生成 JSON，直接输出 HTML 内容。
```

**User Prompt:**

```
客户名称：{client_name}
行业：{industry}
规模：{scale}

需求结构化数据（requirementSolutionData）：
{requirement_data}

请生成技术路线及报价方案 HTML 页面。
```

### 2. 部署

```
POST https://sining.cloud/api/skill/reports
{
  "type": "tech",
  "client_name": "{client_name}",
  "html": "<html>...</html>"
}
```

返回：
```json
{
  "url": "https://sining.cloud/reports/{id}_tech.html",
  "id": "{id}"
}
```

### 3. 展示结果

```
✅ 技术报告已生成！

📄 访问链接：https://sining.cloud/reports/{id}_tech.html

（此链接同时保存到您的客户档案中）
```
