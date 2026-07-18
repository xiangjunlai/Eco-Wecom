# HTML 报告部署机制

## 概述

Work Buddy Skill 生成的 HTML 报告，通过后端 API 部署到 `sining.cloud/reports/` 目录，用户可通过 URL 直接访问。

## 部署流程

```
WB Skill 生成 HTML
    ↓
POST /api/skill/reports
    ↓
后端写入文件到 /www/sining.cloud/reports/
    ↓
返回 URL: https://sining.cloud/reports/{id}_{type}.html
    ↓
同时记录到数据库（client_id, type, url, created_at）
```

## API 详情

### POST /api/skill/reports

**请求：**
```json
{
  "api_key": "服务商API Key",
  "type": "sales | tech | quote",
  "client_name": "客户名称",
  "html": "<html>...</html>"
}
```

**响应：**
```json
{
  "success": true,
  "id": "rpt_abc123",
  "url": "https://sining.cloud/reports/rpt_abc123_sales.html",
  "filename": "rpt_abc123_sales.html"
}
```

**错误响应：**
```json
{
  "success": false,
  "error": "Invalid API key"
}
```

### GET /api/skill/reports/{id}

获取特定报告的信息。

**响应：**
```json
{
  "id": "rpt_abc123",
  "client_id": 123,
  "type": "sales",
  "url": "https://sining.cloud/reports/rpt_abc123_sales.html",
  "created_at": "2024-01-01T12:00:00Z"
}
```

### GET /reports/{filename}

直接访问报告 HTML 文件（静态资源）。

## 文件命名规则

```
{id}_{type}.html

示例：
- rpt_abc123_sales.html   （售前报告）
- rpt_abc123_tech.html    （技术报告）
- rpt_abc123_quote.html   （报价方案）
```

## 访问统计

每次访问报告 URL 时，记录：

```json
{
  "report_id": "rpt_abc123",
  "visited_at": "2024-01-01T12:00:00Z",
  "ip_address": "xxx.xxx.xxx.xxx",
  "user_agent": "Mozilla/5.0..."
}
```

这些数据可在 `/admin/` 后台的"访问分析"中查看。

## 服务器配置

### 目录结构

```
/www/sining.cloud/
├── reports/              # 报告 HTML 文件
│   ├── rpt_abc123_sales.html
│   ├── rpt_abc123_tech.html
│   └── ...
└── ...

/var/www/sining.cloud/
└── reports/             # Nginx alias 指向此目录
```

### Nginx 配置

```nginx
location /reports/ {
    alias /var/www/sining.cloud/reports/;
    expires 30d;
    add_header Cache-Control "public, immutable";
}
```

## 安全考虑

1. **API Key 认证**：每个服务商有唯一的 API Key，存储在 `api_keys` 表
2. **文件隔离**：每个报告绑定到特定的服务商和客户
3. **访问日志**：所有访问都记录日志，供分析
4. **定期清理**：可配置自动删除 N 天前的报告（如 90 天）

## 部署检查清单

- [ ] Nginx 已配置 `/reports/` alias
- [ ] `/var/www/sining.cloud/reports/` 目录存在且可写
- [ ] API Key 认证机制已实现
- [ ] 访问日志已配置
- [ ] HTTPS 已启用（sining.cloud 应使用 HTTPS）
