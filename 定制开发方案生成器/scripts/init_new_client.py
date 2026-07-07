#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
为任意新客户初始化三件套生成脚本

用法：
  python3 scripts/init_new_client.py <客户简称> <行业> <场景>

示例：
  python3 scripts/init_new_client.py 海岸咖啡 连锁餐饮 巡店管理
  python3 scripts/init_new_client.py 极星制造 制造业 订单生产
  python3 scripts/init_new_client.py 知行教育 教育行业 学员管理

效果：
  - 在 examples/<客户简称>/ 创建目录
  - 在 scripts/ 创建该客户专属的 generate_*.py 脚本
  - 自动填入客户名、行业、场景
  - 输出文件名按规范生成
"""
import sys
import shutil
from pathlib import Path

BASE = Path("/workspace/定制开发方案生成器")
SCRIPTS = BASE / "scripts"
EXAMPLES = BASE / "examples"


def main():
    if len(sys.argv) < 4:
        print("用法: python3 init_new_client.py <客户简称> <行业> <场景>")
        print("示例: python3 init_new_client.py 海岸咖啡 连锁餐饮 巡店管理")
        sys.exit(1)

    client = sys.argv[1].strip()
    industry = sys.argv[2].strip()
    scene = sys.argv[3].strip()

    if not client or not industry or not scene:
        print("❌ 客户简称、行业、场景均不能为空")
        sys.exit(1)

    print(f"📦 初始化新客户: {client} · {industry} · {scene}")

    # 1. 创建客户目录
    client_dir = EXAMPLES / client
    client_dir.mkdir(parents=True, exist_ok=True)
    print(f"  ✅ 创建目录: examples/{client}/")

    # 2. 复制 HTML 脚本（已经是参数化的）
    html_target = SCRIPTS / f"generate_html_{client}.py"
    shutil.copy(SCRIPTS / "generate_html.py", html_target)
    print(f"  ✅ 复制: scripts/generate_html_{client}.py")

    # 3. 复制 docx/xlsx 模板副本
    docx_target = SCRIPTS / f"generate_docx_{client}.py"
    xlsx_target = SCRIPTS / f"generate_xlsx_{client}.py"
    shutil.copy(SCRIPTS / "generate_docx_TEMPLATE.py", docx_target)
    shutil.copy(SCRIPTS / "generate_xlsx_TEMPLATE.py", xlsx_target)
    print(f"  ✅ 复制: scripts/generate_docx_{client}.py")
    print(f"  ✅ 复制: scripts/generate_xlsx_{client}.py")

    # 4. 修改 HTML 脚本的 CONFIG：用直接字符串替换，更稳健
    html_content = html_target.read_text(encoding='utf-8')

    # 替换每条 CONFIG 项
    replacements = {
        '"客户名": "城邦美商"': f'"客户名": "{client}"',
        '"客户名简称": "城邦美商"': f'"客户名简称": "{client}"',
        '"服务商名": "[服务商名称待填]",   # 改成你的公司名，如 "XX 科技"': f'"服务商名": "[服务商名称待填]",   # ⚠️ 改成你的公司名',
        '"行业": "[行业待填]"': f'"行业": "{industry}"',
        '"场景": "打样及订单"': f'"场景": "{scene}"',
        '"痛点数": "5"': f'"痛点数": "4"',
        '"核心价值": "打样订单全程可视、效率提升 40%"': f'"核心价值": "核心场景一站式智能化"',
        '"输出子目录": "城邦美商"': f'"输出子目录": "{client}"',
        '"输出文件名后缀": "通用行业打样订单"': f'"输出文件名后缀": "{industry}{scene}"',
    }
    for old, new in replacements.items():
        html_content = html_content.replace(old, new)
    html_target.write_text(html_content, encoding='utf-8')
    print(f"  ✅ 已更新 HTML 脚本配置（客户名/行业/场景）")

    # 5. 修改 docx/xlsx 脚本：替换输出路径 + 替换 CONFIG 中的客户名/行业/场景
    path_replacements = {
        docx_target: {
            'OUTPUT = "/workspace/定制开发方案生成器/examples/城邦美商/城邦美商_需求确认与方案设计表_V1.docx"':
                f'OUTPUT = "{client_dir}/{client}_需求确认与方案设计表_V1.docx"',
        },
        xlsx_target: {
            'OUTPUT = "/workspace/定制开发方案生成器/examples/城邦美商/城邦美商_智能表格交付_V1.xlsx"':
                f'OUTPUT = "{client_dir}/{client}_智能表格交付_V1.xlsx"',
        },
    }
    # docx/xlsx 的 CONFIG 替换项（这些项在 docx/xlsx CONFIG 块里也存在）
    config_replacements = {
        '"客户名": "城邦美商"': f'"客户名": "{client}"',
        '"客户名简称": "城邦美商"': f'"客户名简称": "{client}"',
        '"行业": "[行业待填]"': f'"行业": "{industry}"',
    }
    for target, path_map in path_replacements.items():
        content = target.read_text(encoding='utf-8')
        for old_path, new_path in path_map.items():
            content = content.replace(old_path, new_path)
        for old_cfg, new_cfg in config_replacements.items():
            content = content.replace(old_cfg, new_cfg)
        target.write_text(content, encoding='utf-8')
    print(f"  ✅ 已更新 docx/xlsx 脚本输出路径 + CONFIG 客户名/行业/场景")

    # 6. 输出下一步指引
    print("")
    print("=" * 50)
    print(f"🎉 客户 [{client}] 初始化完成！")
    print("=" * 50)
    print("")
    print("📝 下一步操作：")
    print(f"  1. 编辑 scripts/generate_docx_{client}.py")
    print(f"     - 把 10 章正文里的'城邦美商'改成'{client}'")
    print(f"     - 把'打样及订单'相关业务改成'{scene}'")
    print(f"     - 把'服装外贸'改成'{industry}'")
    print("")
    print(f"  2. 编辑 scripts/generate_xlsx_{client}.py")
    print(f"     - 调整 7 个 Sheet 的字段和示例数据匹配 '{scene}' 场景")
    print("")
    print(f"  3. 编辑 scripts/generate_html_{client}.py")
    print(f"     - 替换 5 张痛点卡片、7 个时间线节点、角色泳道、6 个 mockup 的内容")
    print(f"     - 替换 4 个 KPI 数字")
    print("")
    print(f"  4. 依次运行：")
    print(f"     python3 scripts/generate_html_{client}.py")
    print(f"     python3 scripts/generate_docx_{client}.py")
    print(f"     python3 scripts/generate_xlsx_{client}.py")
    print("")
    print(f"  5. 产物位置: examples/{client}/")
    print("")


if __name__ == "__main__":
    main()
