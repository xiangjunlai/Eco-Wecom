#!/usr/bin/env bash
# ============================================================
# 占位符自检脚本（防空壳）
# 用途：扫描【生成的产物】，检查是否残留未回填的占位符。
#   空壳产物 = 模型套了模板骨架却没填真实信息，全是占位符 —— 等于零分。
#
# 检测两类占位符：
#   1) 模板花括号占位符：{客户名} {行业} {场景} {版本} {服务商名称待填} 等
#   2) 空壳话术：（待补充）（待识别）（暂无）（待确认）—— 注意是【带括号】的成对空话
#
# 合法例外：
#   - “⚠️ 待确认 / ⚠️ 待客户提供 / ⚠️ 缺失”是【正确做法】（抽不到信息时的诚实标注），
#     脚本只拦【带圆括号的纯占位空话】和【花括号模板变量】，不拦带 ⚠️ 的待确认条目。
#
# 退出码：0 = 干净（已填满）；1 = 检出占位符（仍是空壳，必须回填）。
# 用法：
#   bash scripts/check_placeholder.sh <产物目录>
#   bash scripts/check_placeholder.sh /workspace/长谊新材料
# 不传参数则默认扫当前目录。
# ============================================================
set -uo pipefail

TARGET="${1:-.}"

if [ ! -e "$TARGET" ]; then
  echo ">>> ❌ 目标不存在：$TARGET"
  exit 1
fi

echo "=== 占位符自检：扫描产物 $TARGET ==="

# --- 1) 文本类产物（html / md / txt）直接 grep ---
# 花括号模板变量：{中文字段名}，如 {客户名}{行业}{场景}{版本}
BRACE='\{[^}]*(客户|客户名|行业|场景|版本|服务商|工具名|公司名|痛点)[^}]*\}'
# 带圆括号的空壳话术
HOLLOW='（待补充）|（待识别）|（暂无）|（待确认）|（待填）|（待补充.*）|（暂无.*）'

txt_hits=$(grep -rnE "$BRACE|$HOLLOW" \
  --include="*.html" --include="*.md" --include="*.txt" \
  "$TARGET" 2>/dev/null || true)

# --- 2) docx / xlsx 是压缩包，解压 xml 后再扫 ---
bin_hits=""
while IFS= read -r f; do
  [ -z "$f" ] && continue
  inner=$(unzip -p "$f" 2>/dev/null | grep -aoE "$BRACE|$HOLLOW" 2>/dev/null | sort -u || true)
  if [ -n "$inner" ]; then
    bin_hits="${bin_hits}\n[$f]\n${inner}"
  fi
done < <(find "$TARGET" \( -name "*.docx" -o -name "*.xlsx" \) 2>/dev/null)

if [ -n "$txt_hits" ] || [ -n "$bin_hits" ]; then
  echo ">>> ⚠️ 检出未回填的占位符 —— 产物仍是空壳，必须用真实材料回填后重新生成："
  echo ""
  [ -n "$txt_hits" ] && echo "$txt_hits"
  [ -n "$bin_hits" ] && echo -e "$bin_hits"
  echo ""
  echo ">>> 提示：抽不到的信息请写成 “⚠️ 待确认”（不带圆括号的空话），不要留模板占位符。"
  exit 1
else
  echo ">>> ✅ 干净：未检出残留占位符，产物已用真实信息填满。"
  exit 0
fi
