# Provider Assist Skill

## 简介

**Provider Assist** 是一款面向企业微信定制开发服务商的售前助手。帮助服务商快速完成：客户调研 → 沟通纪要 → 方案生成。

## 安装

在 Work Buddy 中运行：

```
/skill add https://sining.cloud/api/skill/skill.md
```

## 首次使用

**第一步：获取 API Key**

联系平台管理员，获取你的 **API Key（受邀码）**。

**第二步：配置 API Key**

安装后，输入：

```
/xiaoqiu 配置 API Key: 你的APIKey
```

**第三步：开始使用**

输入 `/xiaoqiu` 启动售前流程。

---

## 工作流程

```
开始新客户 → /clean（必用，清理上下文）
    ↓
Step 1：售前准备
  - 收集客户基本信息（名称、行业、规模、需求）
  - 生成客户画像 + 访问题纲
    ↓
Step 2：沟通纪要
  - 可多次上传沟通记录
  - 说"ok"确认上传完毕
  - 生成 MD 题纲
    ↓
Step 3：需求整理
  - 生成三种报告（可分别生成）：
    ├─ 📄 售前报告（HTML）
    ├─ 🔧 技术报告（HTML）
    └─ 💰 报价方案（HTML）
    ↓
Step 4：知识库进化（可选）
  - 将本次经验保存到知识库
```

## 核心命令

| 命令 | 功能 |
|------|------|
| `/clean` | 开始新客户前必用，清理当前会话上下文 |
| `/memory` | 查看当前客户已收集的所有信息 |
| `/xiaoqiu` | 启动或继续售前流程 |
| `/help` | 显示帮助 |

## 数据说明

- **数据存储**：所有客户数据、沟通记录、生成的报告链接都存储在平台服务器
- **Token 预警**：生成报告前会显示预估 Token 消耗和费用，确认后再生成
- **报告访问**：生成的 HTML 报告托管在 `sining.cloud/reports/`，可分享链接给客户

## API 配置

- **API 端点**：`https://sining.cloud/api/skill/`
- **报告托管**：`https://sining.cloud/reports/`
- **认证方式**：API Key（受邀码）

---

*如有问题请联系平台管理员。*
