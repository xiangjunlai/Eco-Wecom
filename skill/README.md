# Provider Assist Skill 📦

## 版本管理

当前版本：`2.0.0`（见 `VERSION` 文件）

### 版本号规则
- **主版本 (X.y.z)**：不兼容的交互流程变更
- **次版本 (x.Y.z)**：向后兼容的新功能
- **修订版 (x.y.Z)**：Bug 修复、文档更新

### 发布流程
```bash
# 一键发布（自动完成所有步骤）
./skill/release.sh 2.0.0

# 或手动发布
# 1. 更新 VERSION 文件
echo "2.0.0" > skill/VERSION

# 2. 更新 CHANGELOG
# 3. 推 GitHub
git add . && git commit -m "释放 v2.0.0" && git push

# 4. 同步服务器
ssh ubuntu@193.112.183.213 "cd /home/ubuntu/eco-wecom-new && git pull"
```

## 目录结构

```
skill/
├── skill.md              # ⭐ Skill 主入口（Work Buddy 安装源）
├── VERSION               # 当前版本号
├── CHANGELOG.md          # 版本历史
├── deploy.md             # HTML 报告部署机制
├── release.sh            # 一键发布脚本
├── prompts/              # 各 Step 的 Prompt 模板
│   ├── step1_prep.md     # 售前准备
│   ├── step3_notes.md    # 沟通纪要
│   ├── step4_sales.md    # 售前报告
│   ├── step4_tech.md     # 技术报告
│   ├── step4_quote.md    # 报价方案
│   └── step5_kb.md       # 知识库进化
└── commands/             # /clean、/memory 等命令定义
    ├── clean.md
    └── memory.md
```

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/skill/skill.md` | GET | 获取 Skill 安装源 |
| `/api/skill/manifest` | GET | 获取 Skill 元信息 |
| `/api/skill/register` | POST | 新用户注册 |
| `/api/skill/login` | POST | 老用户 API Key 登录 |
| `/api/skill/prompts/{step}` | POST | 获取指定 Step 的 Prompt |
| `/api/skill/submit` | POST | 提交完整售前数据 |
| `/api/skill/reports` | POST | 上传 HTML 报告 |
| `/api/skill/knowledge` | POST | 保存知识库条目 |

## 测试账号

- **API Key（受邀码）**：`PROV2026001` ~ `PROV2026005`
- **Web 测试登录**：`devuser` / `DevTest123`

## 快速验证

```bash
# 检查云端 Skill 版本
curl https://sining.cloud/api/skill/skill.md | head -5

# 测试登录接口
curl -X POST https://sining.cloud/api/skill/login \
  -H "Content-Type: application/json" \
  -d '{"api_key":"PROV2026001"}'
```
