# CLAUDE.md —— 企业微信售前三件套 · 产品集成包(CC 入口)

> 你(Claude Code)正在帮助开发一款「企业微信售前方案生成」产品。该产品有 5 个 Step,
> 现在的目标:**把本包里的「企业微信售前三件套」专业能力,集成进产品的 Step4 和 Step5,
> 让生成的产物(Word / HTML / 智能表格 Schema)达到三件套规格的专业水准。**
>
> 本文件是入口。请先完整读本文件,再按「执行顺序」逐步操作。**默认只读规划,不要直接改代码,每步先给我看 diff/样例,我确认后再继续。**

---

## 1. 这个包是什么(三层内容)

```
qiwei-presale-integration/
├── CLAUDE.md                       ← 你正在读的入口文件
├── 01-skill-specs/                 【规格源·只读】三件套技能定义,是内容质量的"事实标准"
│   └── qiwei-presale-suite/
│       ├── README.md               套件总规范(一期二期边界/去营销化/服务商变量化)
│       ├── 1-solution-html/SKILL.md   HTML 售前方案 8 章规格
│       ├── 2-techplan-word/SKILL.md   Word 需求确认表 11 节规格
│       └── 3-smarttable-prompt/SKILL.md 智能表格搭建 10 节规格 + 企微合法字段类型
├── 02-upgraded-prompts/            【成品·可直接用】已按规格改写好的升级版 Prompt
│   └── Step4_Step5升级版Prompt.md  直接替换产品里 3 个 Prompt 的成品
└── 03-integration-guide/           【操作手册】分步集成指南 + 验收清单
    └── 集成指令.md
```

- **01 是"为什么"**:定义了什么叫"专业的售前产物"。不进运行时,只当规格参考。
- **02 是"怎么做"**:我已经把规格能力翻译成了可直接替换的 Prompt,这是你的主要工作蓝本。
- **03 是"步骤和验收"**:分步操作和回归检查清单。

---

## 2. 集成原理(先理解,别理解错)

产品运行时是 **后端拼 Prompt → 调 LLM → 得到 JSON → 前端渲染 → 导出 docx/html**。
所以集成**不是**让代码去"调用"skill,而是:

> 用 `02-upgraded-prompts/` 里的升级版 Prompt **替换**产品现有的
> `STEP4_WORD_PROMPT`、`STEP4_HTML_PROMPT`、`Step5 generate-demo` 三个 Prompt,
> 并为新增的 JSON 字段**同步补齐**「类型定义 + 前端渲染 + docx/html 导出器」三处。

| 三件套 skill | 替换产品的 Prompt | 写入的 DB 字段 | 最终产物 |
|-------------|------------------|---------------|---------|
| ② Word(2-techplan-word) | `STEP4_WORD_PROMPT` | `step4_presales_versions` | docx |
| ① HTML(1-solution-html) | `STEP4_HTML_PROMPT` | `step4_technical_versions` | html |
| ③ 智能表格(3-smarttable-prompt) | Step5 `generate-demo` | `step5_schema` | 建表 Schema |

---

## 3. 必须贯彻的 6 条纪律(三件套比普通生成器强的根本)

1. **一期/二期/不建议 三分边界**:ERP/CRM/OA对接、AI自动判断、机器人写表、历史数据清洗、薪资核算 → 默认全进二期,禁止写入一期承诺。
2. **业务语言翻译**:痛点/需求转业务语言,客户原话只放进指定的"原话/evidence"字段。
3. **去营销化**:禁 ROI 算钱、三档报价、服务热线、营销 CTA、追踪代码;报价只写口径不写金额。
4. **字段类型合法性(Step5)**:field_type 只能取企微 14 种合法类型(文本/多行文本/单选/多选/人员/日期/数字/金额/勾选/附件/关联记录/公式/电话/邮箱);关联字段标"关联记录"、计算字段标"公式"。
5. **日期取服务端当天**:`output_date` 由后端拼当天真实日期传入,**不让模型生成**。
6. **三产物口径一致**:同一能力在 Word/HTML/Schema 里的一期二期归属必须一致。

---

## 4. 执行顺序(逐步做,每步等我确认)

### Step 0 · 建立认知(只读)
读完 `01-skill-specs/` 全部 4 个文件 + `02-upgraded-prompts/Step4_Step5升级版Prompt.md`,
然后用三段话分别复述 Word/HTML/Schema 的结构与纪律,**先告诉我你的理解,不改代码**。

### Step 1 · 定位产品现有代码
在产品代码里找出并告诉我这些的确切位置:
- `STEP4_WORD_PROMPT`、`STEP4_HTML_PROMPT`、Step5 `generate-demo` 的 System/User Prompt 定义;
- `step4_presales_versions`、`step4_technical_versions`、`step5_schema` 的类型定义/schema;
- 把这三种 JSON 渲染成页面、以及导出 docx/html 的代码位置。
**列清单给我,先不改。**

### Step 2 · 升级 Word(对照 02 的升级版 ①)
替换 `STEP4_WORD_PROMPT`;在现有 Word JSON 上"加法式"新增标 ★ 的表;
同步补类型定义 + 前端渲染 + docx 导出。给我 diff。

### Step 3 · 升级 HTML(对照 02 的升级版 ②)
替换 `STEP4_HTML_PROMPT`;新增"数据看板"章等 ★ 字段;
同步前端渲染 + html 导出;确认水印固定"企业微信生态定制开发"、无外链/追踪。给我 diff。

### Step 4 · 升级 Step5 Schema(对照 02 的升级版 ③)
替换 Step5 schema Prompt;锁死 field_type 合法类型;落库前加校验。给我 diff。

### Step 5 · 端到端回归(对照 03 的验收清单)
用一个真实案例从 Step3 跑到 Step5,按 `03-integration-guide/集成指令.md` 第 5 节清单逐项验收,
重点查:三产物一期二期口径一致、field_type 全合法、无营销CTA、日期为当天、新增字段在页面/文档里都显示。

---

## 5. 红线提醒(最容易出错的地方)

- ⚠️ **加 JSON 字段必须三处同步**(类型定义 + 前端渲染 + 导出器),否则"生成了但看不到"。
- ⚠️ **只做加法,不删现有字段**,保证前端不崩。
- ⚠️ **日期别让模型编**,后端用当天日期作变量传入。
- ⚠️ **01-skill-specs 保持只读**,它是规格源;以后要调风格,改 skill → 重新对齐 Prompt。
- ⚠️ **分步验收**,不要一次性全改完再给我看。
