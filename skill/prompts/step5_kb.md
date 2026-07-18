# Step 4: 知识库进化

## 功能

基于本次售前过程，生成可添加到服务商**知识库**的内容建议。

## 触发

用户说"知识库进化"或"更新知识库"或"保存到知识库"时触发。

## 前置条件

当前上下文必须有已完成的售前流程（至少 Step 1-3）。

## 对话流程

### 第一轮：询问用户是否保存

```
是否将本次售前过程的经验添加到知识库？

可以保存的内容：
1. 行业案例：{industry} 行业的售前经验
2. 需求模板："{main_demand}" 相关的问题模板
3. 方案片段：可复用的解决方案模块

回复"是"保存，或"否"跳过。
```

### 第二轮：确认保存内容

用户确认后，展示将保存的内容：

```
将保存以下内容到知识库：

【行业案例】
标题：{industry} - {customer_name} 售前案例
内容：{案例摘要}

【需求模板】
标题：{main_demand} 售前问题清单
内容：{must_ask 问题列表}

【方案片段】
标题：{module_name} 模块设计
内容：{module_recommendation}

确认保存？回复"确认"。
```

### 第三轮：保存并反馈

用户确认后，调用 API 保存：

```
POST https://sining.cloud/api/skill/knowledge
{
  "api_key": "{api_key}",
  "type": "case|template|fragment",
  "title": "{title}",
  "content": "{content}",
  "industry": "{industry}",
  "tags": ["售前", "{industry}"]
}
```

保存成功后：

```
✅ 已保存到知识库！

您的知识库现在包含：
- {n} 个行业案例
- {m} 个需求模板
- {k} 个方案片段

这些内容将在未来的售前过程中被引用，提高方案生成的准确性。
```

## 知识库内容类型

### 1. 行业案例

```json
{
  "type": "case",
  "title": "{industry} - {customer_name} 售前案例",
  "content": "客户背景：...\n核心需求：...\n解决方案：...\n实施效果：...",
  "industry": "{industry}",
  "tags": ["{industry}", "售前案例", "{scenario}"]
}
```

### 2. 需求模板

```json
{
  "type": "template",
  "title": "{demand} 售前问题清单",
  "content": "必问问题：\n{must_ask}\n\n深挖问题：\n{deep_dive}",
  "industry": "{industry}",
  "tags": ["{industry}", "需求模板", "{demand}"]
}
```

### 3. 方案片段

```json
{
  "type": "fragment",
  "title": "{module_name} 模块设计",
  "content": "模块说明：...\n适用场景：...\n字段设计：...\n注意事项：...",
  "industry": "{industry}",
  "tags": ["{industry}", "方案片段", "{module_name}"]
}
```

## 知识库查询

在未来的售前过程中，可通过以下方式查询知识库：

```
GET https://sining.cloud/api/skill/knowledge?industry={industry}&type={type}
```

返回匹配的知识库内容，供生成时参考。
