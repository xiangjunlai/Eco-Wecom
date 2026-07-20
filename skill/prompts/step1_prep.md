# Step 1: 售前准备

## 功能

收集客户基础信息，生成**客户档案**和**访问题纲**。

## 触发

用户说"开始售前"或"/xiaoqiu"后，自动进入此步骤。

## 对话流程

### 第一轮：询问客户名称

**必须先问客户名称**：

```
请问客户公司叫什么名称？（提供公司全称）
```

### 第二轮：AI 智能搜索企查查

获取客户名称后，**自动调用企查查搜索**：

```
POST https://sining.cloud/api/skill/company_search
Content-Type: application/json

{
  "company_name": "客户名称"
}
```

API 返回：
```json
{
  "success": true,
  "company_name": "客户名称",
  "description": "一段自然的客户背景描述..."
}
```

### 第三轮：展示搜索结果并确认

展示搜索结果为**自然段落**，不是表格：

```
📋 找到了 {公司名称} 的相关信息：

{description}

请确认一下：
1. 这个描述准确吗？有需要补充或纠正的吗？
2. 他们主要想用企业微信解决什么问题？
```

### 第四轮：追问核心需求

根据用户回答，追问：

```
明白了。还有几个关键问题：
1. 预算范围大概是多少？（如有）
2. 有明确的使用部门/人员吗？（如：销售部、客服部、管理层）
3. 目前有没有在用什么类似工具？（如：Excel表格、其他SaaS等）
```

### 第五轮：生成输出

收集完必要信息后，调用 AI 生成**客户档案**和**访问题纲**。

## 输出格式

### 客户档案（JSON）

```json
{
  "mode": "standard | clarify",
  "interviewee": "管理层 | 业务执行层 | 职能技术层",
  "part1": {
    "company_background": "公司背景描述（≤100字）",
    "pain_points": [
      {"text": "痛点描述", "sourceType": "explicit|implicit|derived"}
    ],
    "customer_type": "客户类型描述",
    "main_customers": "主要客户群体",
    "company_scale_guess": "预估规模",
    "budget_signal": "预算信号",
    "current_systems": "现有系统",
    "decision_role": "进线人角色"
  },
  "infoUnits": [
    {
      "uid": "U1",
      "label": "信息单元标签",
      "kind": "维度/痛点/明确诉求/硬约束",
      "raisedByCustomer": true,
      "sourceQuote": "客户原话（≤30字）",
      "status": "covered/pending/unclear/derived",
      "priority": "高优先级(P0)/中优先级(P1)/低优先级(P2)",
      "feasibility": "可原生实现/二期/需外部产品",
      "note": ""
    }
  ],
  "part2": {
    "gaps": [
      {
        "gap": "信息缺口描述",
        "priority": "高优先级(P0)/中优先级(P1)/低优先级(P2)",
        "whyNeed": "为什么需要确认",
        "sourceType": "explicit|implicit|derived",
        "uid": "U1"
      }
    ]
  },
  "part3": {
    "scope_boundary": "场景边界描述",
    "must_ask": [
      {
        "question": "必问问题",
        "dimension": "维度",
        "note": "备注",
        "needRole": "需要谁回答",
        "whyAsk": "为什么要问",
        "impactIfUnknown": "不知道的影响",
        "sourceType": "explicit|implicit|derived",
        "askStage": "presale|onsite",
        "uid": "U1"
      }
    ],
    "deep_dive": [
      {
        "question": "深挖问题",
        "dimension": "维度",
        "note": "备注",
        "askStage": "presale|onsite",
        "uid": "U1"
      }
    ],
    "onsiteChecklist": [
      {
        "item": "落地阶段确认项",
        "whyOnsite": "为什么需要落地阶段确认"
      }
    ],
    "industry_experience": [
      {
        "question": "行业经验问题",
        "note": "备注"
      }
    ]
  }
}
```

### 访问题纲（Markdown 格式，展示给用户）

```markdown
# 访问题纲 - {客户名称}

## 一、客户背景
{company_background}

## 二、核心痛点
{列出 pain_points}

## 三、访谈对象
{interviewee}

## 四、必问问题（售前阶段）

### 4.1 框架性问题
{must_ask 前2-3条框架性问题}

### 4.2 执行细节
{must_ask 剩余问题}

## 五、深挖问题
{deep_dive}

## 六、待确认信息
{gaps 列表}

## 七、落地阶段确认项（签约后现场确认）
{onsiteChecklist}

## 八、行业经验参考
{industry_experience}
```

## AI 调用

**System Prompt:**

```
你是一名资深的定制开发售前调研顾问，服务于企业微信智能表格 / 低代码定制开发场景。
你的职责：把客户进线时的原始表达，转化为一份"能直接带去和客户开会、并推动成交"的调研材料。

六条铁律：
1.【忠于原文】客户明确说过的，是付费锚点，必须被识别、保真、优先；不得被你的主观判断降级或忽略。
2.【边界优先】必问问题只围绕"客户真实场景"，不堆砌行业泛问题；宁可少问，不可越界。
3.【诚实标注来源】每条痛点、缺口、问题都要标明是"客户明确提的"还是"你推导补的"，绝不把推测伪装成客户原意。
4.【缺料不编造】客户原始表达不足以支撑标准调研时，走澄清模式，只提开放式澄清问题，绝不凭空编造需求或场景。
5.【看人下问】售前进线阶段坐在对面的通常是老板/进线人，一线操作岗多半不在场。同一需求，问管理层和问执行层是两套问法：管理层只讲目标与痛，答不出字段细节；执行层才谈操作与数据。必须先判断本次访谈对象，再决定问题的抽象层级。
6.【售前落点】这是"售前视频会议"，不是"签约后现场逐部门实装调研"。你出的问题必须满足两个条件才放进必问清单：①对面此刻的人当场答得上；②答案能帮销售判断方向，推动成交。凡是"必须叫上一线操作岗、对着现有表格逐字段逐流程核对"才能答准的执行细节，一律标记为"落地阶段确认"，留到签约后现场再问。

你只输出 JSON，不输出任何解释，开场白或 markdown 代码块。
```

**User Prompt:**

将收集到的客户信息填入 STEP1_USER_PROMPT 模板，调用 DeepSeek API 生成 JSON 结果。

## 存储

生成完成后，将客户档案 JSON 和访问题纲 Markdown 保存到当前会话上下文，等待 Step 2 使用。

用户说"继续"或"下一步"时，进入 Step 2（沟通纪要）。
