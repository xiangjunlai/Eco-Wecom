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
    "客户名": "亿选装饰",
    "客户名简称": "亿选装饰",
    "服务商名": "杭州装企云网络科技有限公司",   # ⚠️ 改成你的公司名
    "行业": "家装",            # 如 "服装外贸" / "制造业" / "连锁餐饮"
    "场景": "前端数据分析",             # 如 "订单管理" / "巡检" / "审批流"
    "场景类型": "数据分析",            # 数据分析 / 流程协同 / 客户销售 / 人力行政 / 通用
    "版本": "1.0",
    "日期": "2026-05-22",
    "沟通次数": "1",
    "痛点数": "5",
    "核心价值": "前端数据一屏掌控 + 决策从经验走向数据",
    "输出子目录": "亿选装饰",          # 例客户文件夹名
    "输出文件名后缀": "家装前端数据分析",  # 拼在客户名后
}
# ===============================================

BASE = Path("/workspace/定制开发方案生成器")
TEMPLATE = BASE / "templates/可视化方案模板.html"
OUTPUT_DIR = BASE / "examples" / CONFIG["输出子目录"]
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT = OUTPUT_DIR / f"{CONFIG['客户名简称']}_{CONFIG['输出文件名后缀']}_可视化方案_V{CONFIG['版本']}.html"

# 占位符替换映射
REPLACEMENTS = {f"{{{k}}}": v for k, v in CONFIG.items() if not k.startswith("输出")}

# 痛点卡片数据（家装前端数据分析场景）
PAIN_CARDS = """
    <div class="pain-card">
      <div class="pain-icon">1</div>
      <h3>客户来源散落多平台</h3>
      <p>巨量、百度、美团、小程序、线下门店、客服会话等线索分散在 6+ 系统，无法统一沉淀</p>
      <div class="pain-impact">📉 30% 线索因跟进不及时流失</div>
    </div>
    <div class="pain-card">
      <div class="pain-icon">2</div>
      <h3>客户画像严重缺失</h3>
      <p>业主信息只存 Excel，面积/户型/预算/风格全靠销售口头描述，无结构化数据支撑精准营销</p>
      <div class="pain-impact">📉 复购率仅 8%，远低于行业 20%</div>
    </div>
    <div class="pain-card">
      <div class="pain-icon">3</div>
      <h3>漏斗转化不清晰</h3>
      <p>咨询→量房→报价→签约→施工→竣工各阶段无统一看板，无法定位流失环节</p>
      <div class="pain-impact">📉 签约转化率 12%，有 8% 提升空间</div>
    </div>
    <div class="pain-card">
      <div class="pain-icon">4</div>
      <h3>工地进度不透明</h3>
      <p>47 个在施工地分散在贵阳/遵义/六盘水等 8 个区域，业主无法实时查看进度</p>
      <div class="pain-impact">📉 业主投诉率 18%，口碑转介率下滑</div>
    </div>
    <div class="pain-card">
      <div class="pain-icon">5</div>
      <h3>经营决策靠经验</h3>
      <p>老板拍脑袋定投放预算/选区域/排工期，缺数据支撑，月度营收波动 ±20%</p>
      <div class="pain-impact">📉 投放 ROI 仅 1.8，决策周期 2 周+</div>
    </div>
"""

# 时间线节点（家装前端业务 7 步）
TIMELINE = """
    <div class="timeline-node">
      <div class="timeline-circle">1</div>
      <div class="timeline-name">线索登记</div>
      <div class="timeline-desc">广告/客服/到店</div>
    </div>
    <div class="timeline-node">
      <div class="timeline-circle pain">2</div>
      <div class="timeline-name">来源打标</div>
      <div class="timeline-desc">运营 · ⚠ P1 痛点</div>
    </div>
    <div class="timeline-node">
      <div class="timeline-circle">3</div>
      <div class="timeline-name">量房</div>
      <div class="timeline-desc">设计师+业主</div>
    </div>
    <div class="timeline-node">
      <div class="timeline-circle pain">4</div>
      <div class="timeline-name">报价签约</div>
      <div class="timeline-desc">销售+业主 · ⚠ P1</div>
    </div>
    <div class="timeline-node">
      <div class="timeline-circle pain">5</div>
      <div class="timeline-name">施工</div>
      <div class="timeline-desc">工长+项目经理 · ⚠ P2</div>
    </div>
    <div class="timeline-node">
      <div class="timeline-circle">6</div>
      <div class="timeline-name">竣工</div>
      <div class="timeline-desc">业主+工程部</div>
    </div>
    <div class="timeline-node">
      <div class="timeline-circle pain">7</div>
      <div class="timeline-name">复购转介</div>
      <div class="timeline-desc">运营+全员 · ⚠ P2</div>
    </div>
"""

# 角色泳道（家装场景）
SWIMLANE = """
    <div class="swimlane-row">
      <div class="swimlane-role">业主</div>
      <div class="swimlane-track">
        <div class="swimlane-step">咨询</div>
        <div class="swimlane-step pain">量房</div>
        <div class="swimlane-step">报价</div>
        <div class="swimlane-step pain">看工地</div>
        <div class="swimlane-step">付款</div>
        <div class="swimlane-step">验收</div>
      </div>
    </div>
    <div class="swimlane-row">
      <div class="swimlane-role">销售</div>
      <div class="swimlane-track">
        <div class="swimlane-step pain">线索跟进</div>
        <div class="swimlane-step pain">客户打标</div>
        <div class="swimlane-step">报价谈判</div>
        <div class="swimlane-step">签约回款</div>
      </div>
    </div>
    <div class="swimlane-row">
      <div class="swimlane-role">设计师</div>
      <div class="swimlane-track">
        <div class="swimlane-step">预约</div>
        <div class="swimlane-step pain">量房</div>
        <div class="swimlane-step">出方案</div>
        <div class="swimlane-step">施工图</div>
      </div>
    </div>
    <div class="swimlane-row">
      <div class="swimlane-role">工长</div>
      <div class="swimlane-track">
        <div class="swimlane-step">开工准备</div>
        <div class="swimlane-step pain">拆改/水电</div>
        <div class="swimlane-step pain">泥木/油漆</div>
        <div class="swimlane-step">软装</div>
        <div class="swimlane-step pain">验收交付</div>
      </div>
    </div>
    <div class="swimlane-row">
      <div class="swimlane-role">运营</div>
      <div class="swimlane-track">
        <div class="swimlane-step pain">数据源接入</div>
        <div class="swimlane-step">维度配置</div>
        <div class="swimlane-step">报表分发</div>
        <div class="swimlane-step">周会</div>
      </div>
    </div>
    <div class="swimlane-row">
      <div class="swimlane-role">财务</div>
      <div class="swimlane-track">
        <div class="swimlane-step">收款</div>
        <div class="swimlane-step pain">分阶段对账</div>
        <div class="swimlane-step">开票</div>
        <div class="swimlane-step">成本归集</div>
      </div>
    </div>
    <div class="swimlane-row">
      <div class="swimlane-role">老板</div>
      <div class="swimlane-track">
        <div class="swimlane-step" style="background:#5A5A5A;">查看看板</div>
        <div class="swimlane-step" style="background:#5A5A5A;">投放决策</div>
        <div class="swimlane-step" style="background:#5A5A5A;">异常介入</div>
      </div>
    </div>
"""

# 页面 mockup（家装数据分析场景）
MOCKUPS = """
    <div class="mockup">
      <div class="mockup-header">
        <div class="mockup-dot red"></div>
        <div class="mockup-dot yellow"></div>
        <div class="mockup-dot green"></div>
        <span style="margin-left:8px; font-size:12px; color:#8A8A8A;">数据驾驶舱 · 企微工作台</span>
      </div>
      <div class="mockup-body">
        <div class="mockup-title">📊 家装前端数据驾驶舱</div>
        <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:6px; margin-bottom:12px;">
          <div style="background:#F7F8FA; padding:6px; border-radius:6px; text-align:center;">
            <div style="color:#8A8A8A; font-size:10px;">在施工地</div>
            <div style="color:#1E5AFF; font-size:18px; font-weight:700;">127</div>
          </div>
          <div style="background:#F7F8FA; padding:6px; border-radius:6px; text-align:center;">
            <div style="color:#8A8A8A; font-size:10px;">待签约</div>
            <div style="color:#FF6B35; font-size:18px; font-weight:700;">34</div>
          </div>
          <div style="background:#F7F8FA; padding:6px; border-radius:6px; text-align:center;">
            <div style="color:#8A8A8A; font-size:10px;">异常工地</div>
            <div style="color:#E53935; font-size:18px; font-weight:700;">5</div>
          </div>
        </div>
        <p style="font-size:12px; color:#5A5A5A;">6 大 KPI · 状态分布 · 工地预警 一屏掌握</p>
      </div>
    </div>
    <div class="mockup">
      <div class="mockup-header">
        <div class="mockup-dot red"></div>
        <div class="mockup-dot yellow"></div>
        <div class="mockup-dot green"></div>
        <span style="margin-left:8px; font-size:12px; color:#8A8A8A;">数据源管理 · 企微智能表格</span>
      </div>
      <div class="mockup-body">
        <div class="mockup-title">🔌 数据源接入</div>
        <table style="width:100%; font-size:11px; border-collapse:collapse;">
          <thead>
            <tr style="background:#1E5AFF; color:#FFF;">
              <th style="padding:4px;">数据源</th><th style="padding:4px;">类型</th><th style="padding:4px;">状态</th>
            </tr>
          </thead>
          <tbody>
            <tr><td style="padding:4px;">巨量引擎</td><td>广告投放</td><td><span style="color:#00C853; font-weight:700;">✅ 正常</span></td></tr>
            <tr style="background:#FFF4E5;"><td style="padding:4px;">美团/大众点评</td><td>本地生活</td><td><span style="color:#00C853; font-weight:700;">✅ 正常</span></td></tr>
            <tr style="background:#FFE5E5;"><td style="padding:4px;">线下到店登记</td><td>门店</td><td><span style="color:#FF6B35; font-weight:700;">⚠ 滞后</span></td></tr>
            <tr><td style="padding:4px;">金蝶云财务</td><td>财务</td><td><span style="color:#00C853; font-weight:700;">✅ 正常</span></td></tr>
          </tbody>
        </table>
        <p style="font-size:12px; color:#5A5A5A; margin-top:8px;">10 类数据源自动/手工同步，状态实时</p>
      </div>
    </div>
    <div class="mockup">
      <div class="mockup-header">
        <div class="mockup-dot red"></div>
        <div class="mockup-dot yellow"></div>
        <div class="mockup-dot green"></div>
        <span style="margin-left:8px; font-size:12px; color:#8A8A8A;">维度配置 · 智能表格</span>
      </div>
      <div class="mockup-body">
        <div class="mockup-title">⚙️ 分析维度</div>
        <div style="font-size:12px;">
          <div style="display:flex; align-items:center; gap:8px; padding:6px 0; border-bottom:1px solid #E5E7EB;">
            <span style="background:#E5F7EC; color:#00C853; padding:1px 6px; border-radius:3px; font-size:10px;">默认</span>
            <span style="flex:1;">客户来源</span>
            <span style="color:#8A8A8A; font-size:10px;">投放 ROI</span>
          </div>
          <div style="display:flex; align-items:center; gap:8px; padding:6px 0; border-bottom:1px solid #E5E7EB;">
            <span style="background:#E5F7EC; color:#00C853; padding:1px 6px; border-radius:3px; font-size:10px;">默认</span>
            <span style="flex:1;">户型 / 面积段</span>
            <span style="color:#8A8A8A; font-size:10px;">客单价分层</span>
          </div>
          <div style="display:flex; align-items:center; gap:8px; padding:6px 0; border-bottom:1px solid #E5E7EB;">
            <span style="background:#E5F7EC; color:#00C853; padding:1px 6px; border-radius:3px; font-size:10px;">默认</span>
            <span style="flex:1;">工期 / 阶段</span>
            <span style="color:#8A8A8A; font-size:10px;">漏斗分析</span>
          </div>
          <div style="display:flex; align-items:center; gap:8px; padding:6px 0;">
            <span style="background:#F7F8FA; color:#8A8A8A; padding:1px 6px; border-radius:3px; font-size:10px;">可选</span>
            <span style="flex:1;">流失原因</span>
            <span style="color:#8A8A8A; font-size:10px;">流失分析</span>
          </div>
        </div>
        <p style="font-size:12px; color:#5A5A5A; margin-top:8px;">12 个维度随需启用，灵活组合</p>
      </div>
    </div>
    <div class="mockup">
      <div class="mockup-header">
        <div class="mockup-dot red"></div>
        <div class="mockup-dot yellow"></div>
        <div class="mockup-dot green"></div>
        <span style="margin-left:8px; font-size:12px; color:#8A8A8A;">工地管理 · 智能表格</span>
      </div>
      <div class="mockup-body">
        <div class="mockup-title">🏗️ 工地实时跟踪</div>
        <div style="font-size:12px;">
          <div style="display:flex; align-items:center; gap:8px; padding:6px 0; border-bottom:1px solid #E5E7EB;">
            <span style="width:8px; height:8px; border-radius:50%; background:#00C853;"></span>
            <span style="flex:1;">GZ-2026-038 · 王女士/云岩</span>
            <span style="color:#00C853; font-size:11px;">施工中 75%</span>
          </div>
          <div style="display:flex; align-items:center; gap:8px; padding:6px 0; border-bottom:1px solid #E5E7EB; background:#FFE5E5;">
            <span style="width:8px; height:8px; border-radius:50%; background:#E53935;"></span>
            <span style="flex:1;">GZ-2026-029 · 陈女士/南明</span>
            <span style="color:#E53935; font-size:11px; font-weight:700;">油漆超期 7 天</span>
          </div>
          <div style="display:flex; align-items:center; gap:8px; padding:6px 0; border-bottom:1px solid #E5E7EB;">
            <span style="width:8px; height:8px; border-radius:50%; background:#FF6B35;"></span>
            <span style="flex:1;">GZ-2026-045 · 张总/遵义</span>
            <span style="color:#FF6B35; font-size:11px;">泥木待验收</span>
          </div>
        </div>
        <p style="font-size:12px; color:#5A5A5A; margin-top:8px;">8 个区域、47 个工地、阶段/进度/异常一表管</p>
      </div>
    </div>
    <div class="mockup">
      <div class="mockup-header">
        <div class="mockup-dot red"></div>
        <div class="mockup-dot yellow"></div>
        <div class="mockup-dot green"></div>
        <span style="margin-left:8px; font-size:12px; color:#8A8A8A;">客户档案 · 智能表格</span>
      </div>
      <div class="mockup-body">
        <div class="mockup-title">👥 业主画像</div>
        <div style="font-size:12px;">
          <div style="padding:8px; background:#F7F8FA; border-radius:6px; margin-bottom:6px;">
            <div style="font-weight:600;">王女士 <span style="background:#E5F7EC; color:#00C853; font-size:10px; padding:1px 6px; border-radius:3px; margin-left:4px;">A 级</span></div>
            <div style="color:#8A8A8A; font-size:11px;">140m²三室 · 28万 · 贵阳云岩</div>
          </div>
          <div style="padding:8px; background:#F7F8FA; border-radius:6px; margin-bottom:6px;">
            <div style="font-weight:600;">张总 <span style="background:#E5F7EC; color:#00C853; font-size:10px; padding:1px 6px; border-radius:3px; margin-left:4px;">A 级</span></div>
            <div style="color:#8A8A8A; font-size:11px;">260m²别墅 · 85万 · 复购</div>
          </div>
        </div>
        <p style="font-size:12px; color:#5A5A5A; margin-top:8px;">结构化画像 + 复购/转介标识</p>
      </div>
    </div>
    <div class="mockup">
      <div class="mockup-header">
        <div class="mockup-dot red"></div>
        <div class="mockup-dot yellow"></div>
        <div class="mockup-dot green"></div>
        <span style="margin-left:8px; font-size:12px; color:#8A8A8A;">趋势分析 · 智能表格</span>
      </div>
      <div class="mockup-body">
        <div class="mockup-title">📈 月度趋势</div>
        <table style="width:100%; font-size:11px; border-collapse:collapse;">
          <tr style="background:#F7F8FA;"><td style="padding:4px;">2026-01</td><td style="padding:4px; text-align:right;">12 单</td><td style="padding:4px; text-align:right; color:#8A8A8A;">28 万</td></tr>
          <tr><td style="padding:4px;">2026-02</td><td style="padding:4px; text-align:right;">15 单</td><td style="padding:4px; text-align:right; color:#8A8A8A;">32 万</td></tr>
          <tr style="background:#F7F8FA;"><td style="padding:4px;">2026-03</td><td style="padding:4px; text-align:right;">18 单</td><td style="padding:4px; text-align:right; color:#8A8A8A;">42 万</td></tr>
          <tr><td style="padding:4px;">2026-04</td><td style="padding:4px; text-align:right;">22 单</td><td style="padding:4px; text-align:right; color:#8A8A8A;">58 万</td></tr>
          <tr style="background:#FFF4E5;"><td style="padding:4px;">2026-05</td><td style="padding:4px; text-align:right; font-weight:700;">28 单</td><td style="padding:4px; text-align:right; font-weight:700; color:#FF6B35;">186 万</td></tr>
        </table>
        <p style="font-size:12px; color:#5A5A5A; margin-top:8px;">线索/营收/签约/流失 一图全览</p>
      </div>
    </div>
"""

# 智能表格视图（家装数据分析）
TABLE_VIEWS = """
    <div class="table-view">
      <div class="table-view-header">🔌 数据源管理 · 主配置表</div>
      <table>
        <thead>
          <tr><th>数据源</th><th>类型</th><th>频率</th><th>字段数</th><th>状态</th></tr>
        </thead>
        <tbody>
          <tr><td>巨量引擎投放后台</td><td>广告投放</td><td>每小时</td><td>18</td><td><span class="status-tag status-done">✅ 正常</span></td></tr>
          <tr><td>美团/大众点评</td><td>本地生活</td><td>每日</td><td>9</td><td><span class="status-tag status-done">✅ 正常</span></td></tr>
          <tr><td>微信客服会话</td><td>在线咨询</td><td>实时</td><td>11</td><td><span class="status-tag status-done">✅ 正常</span></td></tr>
          <tr><td>线下到店登记</td><td>门店</td><td>每日</td><td>12</td><td><span class="status-tag status-doing">⚠ 滞后</span></td></tr>
          <tr><td>金蝶云财务</td><td>财务</td><td>实时</td><td>7</td><td><span class="status-tag status-done">✅ 正常</span></td></tr>
        </tbody>
      </table>
    </div>
    <div class="table-view">
      <div class="table-view-header">🏗️ 工地管理 · 核心业务表</div>
      <table>
        <thead>
          <tr><th>工地编号</th><th>客户/区域</th><th>阶段</th><th>进度</th><th>状态</th></tr>
        </thead>
        <tbody>
          <tr><td>GZ-2026-038</td><td>王女士/云岩</td><td>泥木</td><td>75%</td><td><span class="status-tag status-doing">施工中</span></td></tr>
          <tr><td>GZ-2026-029</td><td>陈女士/南明</td><td>油漆</td><td>85%</td><td><span class="status-tag status-pending">超期 7 天</span></td></tr>
          <tr><td>GZ-2026-045</td><td>张总/遵义</td><td>泥木</td><td>90%</td><td><span class="status-tag status-doing">待验收</span></td></tr>
          <tr><td>GZ-2026-033</td><td>赵女士/花溪</td><td>软装</td><td>60%</td><td><span class="status-tag status-doing">施工中</span></td></tr>
        </tbody>
      </table>
    </div>
    <div class="table-view">
      <div class="table-view-header">👥 客户档案 · 主数据表</div>
      <table>
        <thead>
          <tr><th>客户</th><th>区域</th><th>户型</th><th>金额</th><th>等级</th></tr>
        </thead>
        <tbody>
          <tr><td>王女士</td><td>贵阳云岩</td><td>140m²三室</td><td>¥ 280,000</td><td><span class="status-tag status-done">A</span></td></tr>
          <tr><td>张总</td><td>遵义</td><td>260m²别墅</td><td>¥ 850,000</td><td><span class="status-tag status-done">A</span></td></tr>
          <tr><td>陈女士</td><td>贵阳南明</td><td>95m²两室</td><td>¥ 165,000</td><td><span class="status-tag status-doing">B</span></td></tr>
          <tr><td>周总</td><td>安顺</td><td>320m²别墅</td><td>¥ 1,200,000</td><td><span class="status-tag status-done">A</span></td></tr>
        </tbody>
      </table>
    </div>
"""

# KPI（家装数据分析场景）
KPIS = """
    <div class="kpi-card">
      <div class="kpi-label">线索转化率</div>
      <div class="kpi-value">+30%</div>
      <div class="kpi-target">目标 <span>+25%</span></div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">数据归集人力</div>
      <div class="kpi-value">-1.5 FTE</div>
      <div class="kpi-target">目标 <span>-1 FTE</span></div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">工地投诉率</div>
      <div class="kpi-value">-60%</div>
      <div class="kpi-target">目标 <span>-50%</span></div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">决策周期</div>
      <div class="kpi-value">2 天</div>
      <div class="kpi-target">当前 <span>14 天</span></div>
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
  <a href="mailto:contact@example.com" class="btn btn-primary">联系我们</a>
</div>

<footer>
  © {服务商名} · V{版本} · {日期}
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
