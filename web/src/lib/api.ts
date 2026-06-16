/**
 * Web版本的API层 - 使用fetch调用后端API
 */

const API_BASE = "http://localhost:8000";

let authToken = "";

// 获取token
export function getAuthToken(): string {
  return localStorage.getItem("provider_token") || "";
}

function authHeaders() {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${getAuthToken()}`,
  };
}

// ==================== 认证 ====================

export async function login(username: string, password: string) {
  const resp = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const data = await resp.json();
  if (data.success) {
    localStorage.setItem("provider_token", data.access_token);
    localStorage.setItem("provider_username", data.user.username);
    authToken = data.access_token;
  }
  return data;
}

export async function register(username: string, password: string, providerName: string) {
  const resp = await fetch(`${API_BASE}/api/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, provider_name: providerName }),
  });
  const data = await resp.json();
  if (data.success) {
    localStorage.setItem("provider_token", data.access_token);
    localStorage.setItem("provider_username", data.user.username);
    authToken = data.access_token;
  }
  return data;
}

export async function getMe() {
  const resp = await fetch(`${API_BASE}/api/auth/me`, {
    headers: authHeaders(),
  });
  return resp.json();
}

// ==================== 客户管理 ====================

export async function getClients() {
  const resp = await fetch(`${API_BASE}/api/clients`, {
    headers: authHeaders(),
  });
  return resp.json();
}

export async function getClient(id: number) {
  const resp = await fetch(`${API_BASE}/api/clients/${id}`, {
    headers: authHeaders(),
  });
  return resp.json();
}

export async function createClient(name: string, industry: string) {
  const resp = await fetch(`${API_BASE}/api/clients`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ name, industry }),
  });
  return resp.json();
}

export async function updateClient(id: number, data: Record<string, any>) {
  const resp = await fetch(`${API_BASE}/api/clients/${id}`, {
    method: "PUT",
    headers: authHeaders(),
    body: JSON.stringify(data),
  });
  return resp.json();
}

export async function deleteClient(id: number) {
  const resp = await fetch(`${API_BASE}/api/clients/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  return resp.json();
}

// ==================== 知识库 ====================

export async function searchKnowledge(industry: string, keywords: string[] = []) {
  const resp = await fetch(`${API_BASE}/api/knowledge/search`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ industry, keywords }),
  });
  return resp.json();
}

export async function getProviderKnowledge(category: string = "") {
  const url = category
    ? `${API_BASE}/api/provider-knowledge?category=${category}`
    : `${API_BASE}/api/provider-knowledge`;
  const resp = await fetch(url, {
    headers: authHeaders(),
  });
  return resp.json();
}

export async function addProviderKnowledge(data: {
  category: string;
  title: string;
  content: string;
  industry?: string;
  tags?: string;
}) {
  const resp = await fetch(`${API_BASE}/api/provider-knowledge`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(data),
  });
  return resp.json();
}

export async function getKnowledgeStats() {
  const resp = await fetch(`${API_BASE}/api/provider-knowledge/stats`, {
    headers: authHeaders(),
  });
  return resp.json();
}

// ==================== 报告生成 ====================

export async function generateReport(clientId: number, transcript: string) {
  const resp = await fetch(`${API_BASE}/api/reports/generate`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ client_id: clientId, transcript }),
  });
  return resp.json();
}

// ==================== 企业微信智能表格 ====================

export async function createWecomSmartTable(data: {
  doc_name: string;
  sheets: Array<{
    name: string;
    fields: Array<{ title: string; type: string; options?: string[] }>;
    records?: Record<string, string>[];
  }>;
  need_dashboard?: boolean;
  need_gantt?: boolean;
}) {
  const resp = await fetch(`${API_BASE}/api/wecom/create_smarttable`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(data),
  });
  return resp.json();
}
