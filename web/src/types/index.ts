export interface Customer {
  name: string;
  industry: string;
  initial_needs: string;
}

export interface StepData {
  completed: boolean;
  data: Record<string, unknown>;
}

export interface Steps {
  step1: StepData;
  step2: StepData;
  step3: StepData;
  step4: StepData;
  step5: StepData;
}

export interface Workspace {
  id: string;
  created_at: string;
  updated_at: string;
  status: "待完善" | "待沟通" | "待出报告" | "已完成";
  customer: Customer;
  steps: Steps;
}

export interface Config {
  provider_name: string;
  deepseek_api_key: string;
  wechat_api_key: string;
  mcp_url: string;
  bot_id: string;
}

export interface QuestionList {
  customer_background: string;
  industry_pain_points: string[];
  information_gaps: string[];
  required_questions: string[];
  deep_dive_questions: string[];
}

export interface ReportData {
  customer_info: string;
  pain_points: string[];
  business_scenarios: Record<string, unknown>;
  demo_design: DemoDesign;
  pending_items: PendingItem[];
}

export interface DemoDesign {
  sub_tables: SubTable[];
  automation_rules: string[];
  view_design: string;
  permission_design: string;
}

export interface SubTable {
  name: string;
  fields: FieldDef[];
}

export interface FieldDef {
  name: string;
  type: string;
  description?: string;
}

export interface PendingItem {
  question: string;
  why_important: string;
  how_to_ask: string;
}

export type WorkflowStep = 1 | 2 | 3 | 4 | 5;

export const STEP_NAMES: Record<WorkflowStep, string> = {
  1: "信息录入",
  2: "调研准备",
  3: "沟通",
  4: "报告",
  5: "Demo",
};

export const STATUS_LABELS: Record<string, string> = {
  "待完善": "待完善",
  "待沟通": "待沟通",
  "待出报告": "待出报告",
  "已完成": "已完成",
};

export const INDUSTRIES = [
  "服装制造",
  "餐饮",
  "零售",
  "制造",
  "项目管理",
  "教育",
  "医疗",
  "物流",
  "科技",
  "其他",
];