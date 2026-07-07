#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于模板生成任意客户的可视化方案 HTML

用法：
  1) 修改下方 CONFIG 块（客户名、行业、场景、服务商等）
  2) python3 scripts/generate_html.py
  3) 产物在 OUTPUT 路径
"""
import re
from pathlib import Path

# ========== 配置区：给新客户时改这里 ==========
CONFIG = {
    "客户名": "城邦美商",
    "客户名简称": "城邦美商",
    "服务商名": "[服务商名称待填]",   # 改成你的公司名，如 "XX 科技"
    "行业": "[行业待填]",            # 如 "服装外贸" / "制造业" / "连锁餐饮"
    "场景": "打样及订单",             # 如 "订单管理" / "巡检" / "审批流"
    "版本": "1.0",
    "日期": "2026-05-22",
    "沟通次数": "1",
    "痛点数": "5",
    "核心价值": "打样订单全程可视、效率提升 40%",
    "输出子目录": "城邦美商",          # 例客户文件夹名
    "输出文件名后缀": "通用行业打样订单",  # 拼在客户名后
}
# ===============================================

BASE = Path("/workspace/定制开发方案生成器")
TEMPLATE = BASE / "templates/可视化方案模板.html"
OUTPUT_DIR = BASE / "examples" / CONFIG["输出子目录"]
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT = OUTPUT_DIR / f"{CONFIG['客户名简称']}_{CONFIG['输出文件名后缀']}_可视化方案_V{CONFIG['版本']}.html"

# 占位符替换映射
REPLACEMENTS = {f"{{{k}}}": v for k, v in CONFIG.items() if not k.startswith("输出")}

# 痛点卡片数据
PAIN_CARDS = """
    <div class="pain-card">
      <div class="pain-icon">1</div>
      <h3>打样进度不透明</h3>
      <p>客户、工厂、跟单员分散在多个微信群，状态靠人工同步</p>
      <div class="pain-impact">📉 跟单员 30% 时间用于口头同步</div>
    </div>
    <div class="pain-card">
      <div class="pain-icon">2</div>
      <h3>订单数据打架</h3>
      <p>订单状态全靠 Excel 表格，跨部门口径不一，数据冲突频发</p>
      <div class="pain-impact">📉 财务对账周期长达 15 天，差错率 5%</div>
    </div>
    <div class="pain-card">
      <div class="pain-icon">3</div>
      <h3>转化数据缺失</h3>
      <p>打样→订单的转化数据缺失，无法判断哪些客户/款式值得深耕</p>
      <div class="pain-impact">📉 错过 30% 复购机会，年损失约 200 万</div>
    </div>
    <div class="pain-card">
      <div class="pain-icon">4</div>
      <h3>物料库存风险</h3>
      <p>库存靠人工盘点，常出现「已下单但无库存」</p>
      <div class="pain-impact">📉 紧急补单占 12%，成本上升 8%</div>
    </div>
"""

# 时间线节点
TIMELINE = """
    <div class="timeline-node">
      <div class="timeline-circle">1</div>
      <div class="timeline-name">客户询价</div>
      <div class="timeline-desc">业务 / 客户</div>
    </div>
    <div class="timeline-node">
      <div class="timeline-circle">2</div>
      <div class="timeline-name">打样评估</div>
      <div class="timeline-desc">打样员</div>
    </div>
    <div class="timeline-node">
      <div class="timeline-circle pain">3</div>
      <div class="timeline-name">打样制作</div>
      <div class="timeline-desc">工厂 · ⚠ P1 痛点</div>
    </div>
    <div class="timeline-node">
      <div class="timeline-circle pain">4</div>
      <div class="timeline-name">客户确认</div>
      <div class="timeline-desc">客户+打样员 · ⚠ P1</div>
    </div>
    <div class="timeline-node">
      <div class="timeline-circle pain">5</div>
      <div class="timeline-name">下单生产</div>
      <div class="timeline-desc">跟单+工厂 · ⚠ P2</div>
    </div>
    <div class="timeline-node">
      <div class="timeline-circle">6</div>
      <div class="timeline-name">发运交付</div>
      <div class="timeline-desc">跟单+物流</div>
    </div>
    <div class="timeline-node">
      <div class="timeline-circle pain">7</div>
      <div class="timeline-name">结算收款</div>
      <div class="timeline-desc">财务 · ⚠ P2</div>
    </div>
"""

# 角色泳道
SWIMLANE = """
    <div class="swimlane-row">
      <div class="swimlane-role">客户</div>
      <div class="swimlane-track">
        <div class="swimlane-step">询价</div>
        <div class="swimlane-step">确认样衣</div>
        <div class="swimlane-step">下单</div>
        <div class="swimlane-step">查物流</div>
        <div class="swimlane-step">付款</div>
      </div>
    </div>
    <div class="swimlane-row">
      <div class="swimlane-role">业务</div>
      <div class="swimlane-track">
        <div class="swimlane-step">对接客户</div>
        <div class="swimlane-step">传递需求</div>
        <div class="swimlane-step">跟踪反馈</div>
      </div>
    </div>
    <div class="swimlane-row">
      <div class="swimlane-role">打样员</div>
      <div class="swimlane-track">
        <div class="swimlane-step">评估打样</div>
        <div class="swimlane-step pain">制作样衣</div>
        <div class="swimlane-step pain">寄送客户</div>
        <div class="swimlane-step pain">修改打回</div>
      </div>
    </div>
    <div class="swimlane-row">
      <div class="swimlane-role">跟单员</div>
      <div class="swimlane-track">
        <div class="swimlane-step">下单 PO</div>
        <div class="swimlane-step pain">跟产</div>
        <div class="swimlane-step pain">发运</div>
      </div>
    </div>
    <div class="swimlane-row">
      <div class="swimlane-role">工厂</div>
      <div class="swimlane-track">
        <div class="swimlane-step pain">打样</div>
        <div class="swimlane-step pain">生产</div>
        <div class="swimlane-step">交付</div>
      </div>
    </div>
    <div class="swimlane-row">
      <div class="swimlane-role">财务</div>
      <div class="swimlane-track">
        <div class="swimlane-step">对账</div>
        <div class="swimlane-step pain">开票</div>
        <div class="swimlane-step">收款</div>
      </div>
    </div>
    <div class="swimlane-row">
      <div class="swimlane-role">老板</div>
      <div class="swimlane-track">
        <div class="swimlane-step" style="background:#5A5A5A;">查看看板</div>
        <div class="swimlane-step" style="background:#5A5A5A;">异常介入</div>
      </div>
    </div>
"""

# 页面 mockup
MOCKUPS = """
    <div class="mockup">
      <div class="mockup-header">
        <div class="mockup-dot red"></div>
        <div class="mockup-dot yellow"></div>
        <div class="mockup-dot green"></div>
        <span style="margin-left:8px; font-size:12px; color:#8A8A8A;">数据看板 · 企微工作台</span>
      </div>
      <div class="mockup-body">
        <div class="mockup-title">📊 数据看板</div>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:12px;">
          <div style="background:#F7F8FA; padding:8px; border-radius:6px; text-align:center;">
            <div style="color:#8A8A8A; font-size:11px;">订单总数</div>
            <div style="color:#1E5AFF; font-size:20px; font-weight:700;">128</div>
          </div>
          <div style="background:#F7F8FA; padding:8px; border-radius:6px; text-align:center;">
            <div style="color:#8A8A8A; font-size:11px;">打样中</div>
            <div style="color:#FF6B35; font-size:20px; font-weight:700;">34</div>
          </div>
          <div style="background:#F7F8FA; padding:8px; border-radius:6px; text-align:center;">
            <div style="color:#8A8A8A; font-size:11px;">生产中</div>
            <div style="color:#1E5AFF; font-size:20px; font-weight:700;">47</div>
          </div>
          <div style="background:#F7F8FA; padding:8px; border-radius:6px; text-align:center;">
            <div style="color:#8A8A8A; font-size:11px;">异常</div>
            <div style="color:#E53935; font-size:20px; font-weight:700;">5</div>
          </div>
        </div>
        <p style="font-size:12px; color:#5A5A5A;">6 大 KPI 实时展示，状态分布、待办、趋势一屏可见</p>
      </div>
    </div>
    <div class="mockup">
      <div class="mockup-header">
        <div class="mockup-dot red"></div>
        <div class="mockup-dot yellow"></div>
        <div class="mockup-dot green"></div>
        <span style="margin-left:8px; font-size:12px; color:#8A8A8A;">智能表格 · 订单总览</span>
      </div>
      <div class="mockup-body">
        <div class="mockup-title">📦 订单总览表</div>
        <table style="width:100%; font-size:11px; border-collapse:collapse;">
          <thead>
            <tr style="background:#1E5AFF; color:#FFF;">
              <th style="padding:4px;">订单号</th><th style="padding:4px;">客户</th><th style="padding:4px;">状态</th><th style="padding:4px;">金额</th>
            </tr>
          </thead>
          <tbody>
            <tr style="background:#FFF4E5;"><td style="padding:4px;">PO-001</td><td>Bloomingdale's</td><td><span style="color:#FF6B35; font-weight:700;">打样中</span></td><td>¥ 50,000</td></tr>
            <tr style="background:#E5F7EC;"><td style="padding:4px;">PO-002</td><td>Anthropologie</td><td><span style="color:#00C853; font-weight:700;">已完成</span></td><td>¥ 120,000</td></tr>
            <tr style="background:#FFE5E5;"><td style="padding:4px;">PO-003</td><td>Free People</td><td><span style="color:#E53935; font-weight:700;">异常</span></td><td>¥ 86,000</td></tr>
          </tbody>
        </table>
        <p style="font-size:12px; color:#5A5A5A; margin-top:8px;">状态色块、超期预警、欠款公式自动算</p>
      </div>
    </div>
    <div class="mockup">
      <div class="mockup-header">
        <div class="mockup-dot red"></div>
        <div class="mockup-dot yellow"></div>
        <div class="mockup-dot green"></div>
        <span style="margin-left:8px; font-size:12px; color:#8A8A8A;">打样进度跟踪</span>
      </div>
      <div class="mockup-body">
        <div class="mockup-title">🧪 打样跟踪</div>
        <div style="font-size:12px;">
          <div style="display:flex; align-items:center; gap:8px; padding:6px 0; border-bottom:1px solid #E5E7EB;">
            <span style="width:8px; height:8px; border-radius:50%; background:#00C853;"></span>
            <span style="flex:1;">SM-2026-001 · Bloomingdale's</span>
            <span style="color:#00C853; font-size:11px;">已确认</span>
          </div>
          <div style="display:flex; align-items:center; gap:8px; padding:6px 0; border-bottom:1px solid #E5E7EB;">
            <span style="width:8px; height:8px; border-radius:50%; background:#FF6B35;"></span>
            <span style="flex:1;">SM-2026-002 · Anthropologie</span>
            <span style="color:#FF6B35; font-size:11px;">已寄出</span>
          </div>
          <div style="display:flex; align-items:center; gap:8px; padding:6px 0; border-bottom:1px solid #E5E7EB;">
            <span style="width:8px; height:8px; border-radius:50%; background:#E53935;"></span>
            <span style="flex:1;">SM-2026-003 · Free People</span>
            <span style="color:#E53935; font-size:11px;">客户打回</span>
          </div>
        </div>
        <p style="font-size:12px; color:#5A5A5A; margin-top:8px;">从打版到客户确认全流程追踪</p>
      </div>
    </div>
    <div class="mockup">
      <div class="mockup-header">
        <div class="mockup-dot red"></div>
        <div class="mockup-dot yellow"></div>
        <div class="mockup-dot green"></div>
        <span style="margin-left:8px; font-size:12px; color:#8A8A8A;">物料库存预警</span>
      </div>
      <div class="mockup-body">
        <div class="mockup-title">🏭 物料追踪</div>
        <div style="font-size:12px;">
          <div style="display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid #E5E7EB;">
            <span>纯棉面料 180g</span>
            <span style="color:#00C853;">1,200 / 500 ✓</span>
          </div>
          <div style="display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid #E5E7EB; background:#FFE5E5;">
            <span>真丝缎面 22姆米</span>
            <span style="color:#E53935; font-weight:700;">300 / 400 ⚠</span>
          </div>
          <div style="display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid #E5E7EB;">
            <span>亚麻布 230g</span>
            <span style="color:#00C853;">800 / 300 ✓</span>
          </div>
        </div>
        <p style="font-size:12px; color:#5A5A5A; margin-top:8px;">库存低于安全线自动预警</p>
      </div>
    </div>
    <div class="mockup">
      <div class="mockup-header">
        <div class="mockup-dot red"></div>
        <div class="mockup-dot yellow"></div>
        <div class="mockup-dot green"></div>
        <span style="margin-left:8px; font-size:12px; color:#8A8A8A;">客户档案</span>
      </div>
      <div class="mockup-body">
        <div class="mockup-title">👥 客户档案</div>
        <div style="font-size:12px;">
          <div style="padding:8px; background:#F7F8FA; border-radius:6px; margin-bottom:6px;">
            <div style="font-weight:600;">Bloomingdale's <span style="background:#E5F7EC; color:#00C853; font-size:10px; padding:1px 6px; border-radius:3px; margin-left:4px;">A 级</span></div>
            <div style="color:#8A8A8A; font-size:11px;">28 单 · ¥ 3,850,000 · 美东</div>
          </div>
          <div style="padding:8px; background:#F7F8FA; border-radius:6px; margin-bottom:6px;">
            <div style="font-weight:600;">Anthropologie <span style="background:#E5F7EC; color:#00C853; font-size:10px; padding:1px 6px; border-radius:3px; margin-left:4px;">A 级</span></div>
            <div style="color:#8A8A8A; font-size:11px;">22 单 · ¥ 2,680,000 · 美东</div>
          </div>
        </div>
        <p style="font-size:12px; color:#5A5A5A; margin-top:8px;">客户主数据+历史交易统一管理</p>
      </div>
    </div>
    <div class="mockup">
      <div class="mockup-header">
        <div class="mockup-dot red"></div>
        <div class="mockup-dot yellow"></div>
        <div class="mockup-dot green"></div>
        <span style="margin-left:8px; font-size:12px; color:#8A8A8A;">财务对账</span>
      </div>
      <div class="mockup-body">
        <div class="mockup-title">💰 财务对账</div>
        <table style="width:100%; font-size:11px; border-collapse:collapse;">
          <tr style="background:#F7F8FA;"><td style="padding:4px;">应收合计</td><td style="padding:4px; text-align:right; font-weight:700;">¥ 2,180,000</td></tr>
          <tr><td style="padding:4px;">已收合计</td><td style="padding:4px; text-align:right; color:#00C853;">¥ 1,560,000</td></tr>
          <tr style="background:#FFF4E5;"><td style="padding:4px;">未收合计</td><td style="padding:4px; text-align:right; color:#FF6B35; font-weight:700;">¥ 620,000</td></tr>
        </table>
        <p style="font-size:12px; color:#5A5A5A; margin-top:8px;">应收/已收/未收自动汇总</p>
      </div>
    </div>
"""

# 智能表格视图
TABLE_VIEWS = """
    <div class="table-view">
      <div class="table-view-header">📦 订单总览 · 主业务表</div>
      <table>
        <thead>
          <tr><th>订单号</th><th>客户</th><th>状态</th><th>金额</th><th>欠款</th><th>跟单员</th></tr>
        </thead>
        <tbody>
          <tr><td>PO-2026-001</td><td>Bloomingdale's</td><td><span class="status-tag status-done">已完成</span></td><td>¥ 50,000</td><td>¥ 0</td><td>张三</td></tr>
          <tr><td>PO-2026-002</td><td>Anthropologie</td><td><span class="status-tag status-doing">生产中</span></td><td>¥ 120,000</td><td>¥ 60,000</td><td>李四</td></tr>
          <tr><td>PO-2026-003</td><td>Free People</td><td><span class="status-tag status-pending">待确认</span></td><td>¥ 86,000</td><td>¥ 86,000</td><td>王五</td></tr>
        </tbody>
      </table>
    </div>
    <div class="table-view">
      <div class="table-view-header">🧪 打样进度跟踪</div>
      <table>
        <thead>
          <tr><th>打样单号</th><th>款式</th><th>打样状态</th><th>工厂</th><th>客户确认</th></tr>
        </thead>
        <tbody>
          <tr><td>SM-2026-001</td><td>WOMEN BLOUSE</td><td><span class="status-tag status-done">已确认</span></td><td>上海一厂</td><td>2026-05-10</td></tr>
          <tr><td>SM-2026-002</td><td>MEN'S T-SHIRT</td><td><span class="status-tag status-doing">已寄出</span></td><td>苏州二厂</td><td>—</td></tr>
          <tr><td>SM-2026-003</td><td>KIDS DRESS</td><td><span class="status-tag status-pending">客户打回</span></td><td>杭州三厂</td><td>—</td></tr>
        </tbody>
      </table>
    </div>
    <div class="table-view">
      <div class="table-view-header">💰 财务对账</div>
      <table>
        <thead>
          <tr><th>订单号</th><th>应收</th><th>已收</th><th>未收</th><th>状态</th></tr>
        </thead>
        <tbody>
          <tr><td>PO-2026-001</td><td>¥ 50,000</td><td>¥ 50,000</td><td>¥ 0</td><td><span class="status-tag status-done">已结清</span></td></tr>
          <tr><td>PO-2026-002</td><td>¥ 120,000</td><td>¥ 60,000</td><td>¥ 60,000</td><td><span class="status-tag status-doing">部分收款</span></td></tr>
          <tr><td>PO-2026-003</td><td>¥ 86,000</td><td>¥ 0</td><td>¥ 86,000</td><td><span class="status-tag status-pending">待收款</span></td></tr>
        </tbody>
      </table>
    </div>
"""

# KPI
KPIS = """
    <div class="kpi-card">
      <div class="kpi-label">效率提升</div>
      <div class="kpi-value">+40%</div>
      <div class="kpi-target">目标 <span>+35%</span></div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">跟单人力节省</div>
      <div class="kpi-value">1 FTE</div>
      <div class="kpi-target">目标 <span>1 FTE</span></div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">差错率</div>
      <div class="kpi-value">-80%</div>
      <div class="kpi-target">目标 <span>-70%</span></div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">年节省</div>
      <div class="kpi-value">¥ 100万+</div>
      <div class="kpi-target">目标 <span>¥ 80万</span></div>
    </div>
"""

# 甘特图
GANTT = """
    <div class="gantt-row">
      <div class="gantt-label">需求确认</div>
      <div class="gantt-weeks">
        <div class="gantt-week" style="background:#1E5AFF;"></div>
        <div class="gantt-week"></div>
        <div class="gantt-week"></div>
        <div class="gantt-week"></div>
        <div class="gantt-week"></div>
        <div class="gantt-week"></div>
      </div>
    </div>
    <div class="gantt-row">
      <div class="gantt-label">原型设计</div>
      <div class="gantt-weeks">
        <div class="gantt-week"></div>
        <div class="gantt-week" style="background:#3D7BFF;"></div>
        <div class="gantt-week"></div>
        <div class="gantt-week"></div>
        <div class="gantt-week"></div>
        <div class="gantt-week"></div>
      </div>
    </div>
    <div class="gantt-row">
      <div class="gantt-label">开发实施</div>
      <div class="gantt-weeks">
        <div class="gantt-week"></div>
        <div class="gantt-week"></div>
        <div class="gantt-week" style="background:#00C853;"></div>
        <div class="gantt-week" style="background:#00C853;"></div>
        <div class="gantt-week"></div>
        <div class="gantt-week"></div>
      </div>
    </div>
    <div class="gantt-row">
      <div class="gantt-label">测试验证</div>
      <div class="gantt-weeks">
        <div class="gantt-week"></div>
        <div class="gantt-week"></div>
        <div class="gantt-week"></div>
        <div class="gantt-week"></div>
        <div class="gantt-week" style="background:#FF6B35;"></div>
        <div class="gantt-week"></div>
      </div>
    </div>
    <div class="gantt-row">
      <div class="gantt-label">上线培训</div>
      <div class="gantt-weeks">
        <div class="gantt-week"></div>
        <div class="gantt-week"></div>
        <div class="gantt-week"></div>
        <div class="gantt-week"></div>
        <div class="gantt-week"></div>
        <div class="gantt-week" style="background:#1A1A1A;"></div>
      </div>
    </div>
"""

# 读取模板
html = TEMPLATE.read_text(encoding='utf-8')

# 占位符替换
for k, v in REPLACEMENTS.items():
    html = html.replace(k, v)

# 块替换（用注释标记）
html = html.replace(
    '<!-- ... 复制 3-4 张 ... -->',
    PAIN_CARDS
)
html = html.replace(
    '<!-- ... -->',
    TIMELINE + '\n    <!-- ... -->',  # 第一次替换：时间线
)
# 多次替换通用的 <!-- ... -->
# 简单做法：所有剩下的 <!-- ... --> 都按上下文替换
# 我们改用更精确的占位符

# 重新写一遍模板
template_text = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{客户名} · {行业} · {场景} 可视化方案 V{版本}</title>
<style>
__CSS__
</style>
</head>
<body>

<!-- 导航 -->
<div class="nav">
  <div class="logo">{服务商名}</div>
  <div class="nav-meta">{客户名简称} · {行业} · V{版本}</div>
</div>

<!-- Hero -->
<div class="hero">
  <h1>{行业} · {场景}<br>一站式智能化解决方案</h1>
  <p class="sub">帮助 {客户名} 解决 <strong>{痛点数}</strong> 个核心痛点 · 实现 <strong>{核心价值}</strong></p>
  <div class="ctas">
    <a href="#pain" class="btn btn-primary">查看痛点分析</a>
    <a href="#solution" class="btn btn-secondary">了解方案</a>
  </div>
</div>

<!-- 痛点 -->
<section id="pain">
  <h2 class="section-title">客户核心痛点</h2>
  <p class="section-sub">基于 {沟通次数} 次需求沟通，提炼出的 {痛点数} 个最关键问题</p>
  <div class="pain-grid">
__PAIN_CARDS__
  </div>
</section>

<!-- 流程时间线 -->
<section>
  <h2 class="section-title">{场景}端到端流程</h2>
  <p class="section-sub">红色节点表示当前痛点集中的环节</p>
  <div class="timeline">
__TIMELINE__
  </div>
</section>

<!-- 角色泳道 -->
<section>
  <h2 class="section-title">角色协同</h2>
  <p class="section-sub">各角色在流程中的责任分工（橙色为痛点集中环节）</p>
  <div class="swimlane">
__SWIMLANE__
  </div>
</section>

<!-- 页面 mockup -->
<section id="solution">
  <h2 class="section-title">核心功能展示</h2>
  <p class="section-sub">企微工作台 + 智能表格 + 数据看板</p>
  <div class="mockup-grid">
__MOCKUPS__
  </div>
</section>

<!-- 表格视图 -->
<section>
  <h2 class="section-title">智能表格设计</h2>
  <p class="section-sub">7 个 Sheet 覆盖业务全流程</p>
__TABLE_VIEWS__
</section>

<!-- 价值 KPI -->
<section>
  <h2 class="section-title">预期价值</h2>
  <p class="section-sub">基于行业基准与贵司现状估算</p>
  <div class="kpi-grid">
__KPIS__
  </div>
</section>

<!-- 实施计划 -->
<section>
  <h2 class="section-title">实施计划</h2>
  <p class="section-sub">6 周交付，预计 2026-07 上线</p>
  <div class="gantt">
__GANTT__
  </div>
</section>

<!-- CTA -->
<div class="cta-section">
  <h2>下一步</h2>
  <p>请于 3 个工作日内反馈确认，我们即可启动开发</p>
  <a href="mailto:contact@shanyu-future.com" class="btn btn-primary">联系方案生成器</a>
</div>

<footer>
  © [服务商名称待填] · V{版本} · {日期}
</footer>

</body>
</html>
'''

# 读取模板里的 CSS
template = TEMPLATE.read_text(encoding='utf-8')
css_match = re.search(r'<style>(.*?)</style>', template, re.DOTALL)
css = css_match.group(1) if css_match else ""

# 拼装
final = template_text
final = final.replace("__CSS__", css)
final = final.replace("__PAIN_CARDS__", PAIN_CARDS)
final = final.replace("__TIMELINE__", TIMELINE)
final = final.replace("__SWIMLANE__", SWIMLANE)
final = final.replace("__MOCKUPS__", MOCKUPS)
final = final.replace("__TABLE_VIEWS__", TABLE_VIEWS)
final = final.replace("__KPIS__", KPIS)
final = final.replace("__GANTT__", GANTT)

# 占位符
for k, v in REPLACEMENTS.items():
    final = final.replace(k, v)

OUTPUT.write_text(final, encoding='utf-8')
print(f"✅ 已生成: {OUTPUT}")
print(f"   大小: {OUTPUT.stat().st_size / 1024:.1f} KB")
