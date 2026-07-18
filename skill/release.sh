#!/bin/bash
# =====================================================================
# Provider Assist Skill 一键发布脚本
# 用法: ./skill/release.sh 2.0.0
# =====================================================================
set -e

NEW_VERSION="$1"
if [[ -z "$NEW_VERSION" ]]; then
  echo "用法: $0 <版本号>  例如: $0 2.0.0"
  exit 1
fi

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SKILL_DIR"

echo "=========================================="
echo "  Provider Assist Skill 发布 v$NEW_VERSION"
echo "=========================================="

# 1. 更新 VERSION 文件
echo "✅ 更新 VERSION"
echo "$NEW_VERSION" > VERSION

# 2. 更新 skill.md 顶部的 version 字段
echo "✅ 更新 skill.md 版本号"
sed -i '' "s/^version: .*/version: \"$NEW_VERSION\"/" skill.md 2>/dev/null || \
sed -i "s/^version: .*/version: \"$NEW_VERSION\"/" skill.md

# 3. 自动写入 CHANGELOG（用户手动补充内容）
echo "✅ 更新 CHANGELOG"
TODAY=$(date +%Y-%m-%d)
# 检查是否已有今日条目
if grep -q "## \[$NEW_VERSION\]" CHANGELOG.md; then
  echo "   CHANGELOG 已有 v$NEW_VERSION 条目，请手动补充变更内容"
else
  # 在 CHANGELOG 顶部插入新版本块（需用户后续补充）
  sed -i "1i\\
## [$NEW_VERSION] $TODAY\\
### 新增\\
- \\
### 改动\\
- \\
### 修复\\
- \\
" CHANGELOG.md
  echo "   已创建 CHANGELOG 条目，请手动补充变更内容"
fi

# 4. Git 提交
echo "✅ Git 提交"
cd "$(dirname "$SKILL_DIR")"
git add skill/
git commit -m "释放 v$NEW_VERSION"

# 5. 推送到 GitHub
echo "✅ 推送到 GitHub"
git push origin main

# 6. 同步到腾讯云服务器
echo "✅ 同步到腾讯云服务器"
ssh ubuntu@193.112.183.213 "cd /home/ubuntu/eco-wecom-new && git pull origin main"

# 7. 验证
echo "✅ 验证部署"
curl -s https://sining.cloud/api/skill/skill.md | head -3

echo ""
echo "=========================================="
echo "  发布完成！v$NEW_VERSION"
echo "=========================================="
echo ""
echo "📋 下一步："
echo "   1. 补充 CHANGELOG.md 中的变更详情"
echo "   2. 通知用户更新 Skill："
echo "      /skill remove provider-assist"
echo "      /skill add https://sining.cloud/api/skill/skill.md"
