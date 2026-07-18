# /memory 命令

## 功能

查看当前客户已收集到的所有信息，或补充遗漏信息。

## 触发

用户发送 `/memory` 或说"查看当前进度"、"我的记忆"。

## 执行流程

### 1. 检查是否有当前客户

如果没有正在进行的客户：

```
暂无进行中的客户。
说"售前"或"/xiaoqiu"开始新客户流程。
```

### 2. 展示当前客户信息

如果存在当前客户，展示所有已收集的信息：

```
📋 当前客户：{client_name}
行业：{industry}
规模：{scale}
当前阶段：{current_step}

========== 已收集信息 ==========

【客户档案】
{profile_summary}

【访问题纲】
{must_ask_summary}

【沟通记录】({notes_count}条)
{meeting_notes_preview}

【MD题纲】
{md_outline_preview}

【报告】
- 售前报告：{sales_report_url or "未生成"}
- 技术报告：{tech_report_url or "未生成"}
- 报价方案：{quote_report_url or "未生成"}

=================================
```

### 3. 询问是否需要补充

```
需要补充或修改哪些信息？
例如："把客户名称改成XXX"、"添加一条沟通记录"
```

## 补充信息命令

用户可以通过自然语言补充信息：

- "把客户名称改成XXX" → 更新 `client_name`
- "补充沟通记录：XXX" → 添加到 `meeting_notes[]`
- "行业改成制造业" → 更新 `industry`
- "添加需求标签：销售管理" → 添加到 `tags`

## 数据结构

当前上下文存储的数据：

```json
{
  "client_name": "",
  "industry": "",
  "scale": "",
  "tags": [],
  "initial_demand": "",
  "profile_json": {},
  "profile_text": "",
  "visit_outline": "",
  "meeting_notes": [],
  "md_outline": "",
  "requirement_data": {},
  "reports": {
    "sales": {"url": "", "generated_at": ""},
    "tech": {"url": "", "generated_at": ""},
    "quote": {"url": "", "generated_at": ""}
  },
  "token_usage": {
    "total_tokens": 0,
    "total_cost": 0
  }
}
```

## 使用场景

- 用户想确认当前进度时
- 用户想补充遗漏信息时
- 售前过程中想回顾已收集的信息时
