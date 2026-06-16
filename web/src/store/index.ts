/**
 * Web版本的Store - 使用fetch调用后端API
 */

import { create } from "zustand";
import * as api from "../lib/api";
import type { Workspace, Config, WorkflowStep } from "../types";

interface AppState {
  config: Config | null;
  workspaces: Workspace[];
  activeWorkspace: Workspace | null;
  currentStep: WorkflowStep;
  isLoading: boolean;
  error: string | null;

  // 认证
  isAuthenticated: boolean;
  currentUser: { username: string; provider_name: string } | null;

  // Actions
  login: (username: string, password: string) => Promise<boolean>;
  register: (username: string, password: string, providerName: string) => Promise<boolean>;
  logout: () => void;
  checkAuth: () => void;

  loadConfig: () => Promise<void>;
  saveConfig: (config: Config) => Promise<void>;
  loadWorkspaces: () => Promise<void>;
  createWorkspace: (customerName: string, industry: string) => Promise<string>;
  selectWorkspace: (id: string) => Promise<void>;
  updateWorkspace: (workspace: Workspace) => Promise<void>;
  deleteWorkspace: (id: string) => Promise<void>;
  setCurrentStep: (step: WorkflowStep) => void;
  clearActiveWorkspace: () => void;
  clearError: () => void;

  // 知识库
  searchKnowledge: (industry: string, keywords?: string[]) => Promise<any>;
  getProviderKnowledge: (category?: string) => Promise<any[]>;
  addProviderKnowledge: (data: any) => Promise<void>;
  getKnowledgeStats: () => Promise<any>;

  // 报告
  generateReport: (clientId: number, transcript: string) => Promise<string>;

  // 企业微信
  createWecomSmartTable: (data: any) => Promise<any>;
}

export const useAppStore = create<AppState>((set, get) => ({
  config: null,
  workspaces: [],
  activeWorkspace: null,
  currentStep: 1,
  isLoading: false,
  error: null,
  isAuthenticated: false,
  currentUser: null,

  // 认证
  checkAuth: () => {
    const token = localStorage.getItem("provider_token");
    const username = localStorage.getItem("provider_username");
    if (token) {
      set({ isAuthenticated: true, currentUser: { username: username || "", provider_name: "" } });
    }
  },

  login: async (username: string, password: string) => {
    try {
      const data = await api.login(username, password);
      if (data.success) {
        set({
          isAuthenticated: true,
          currentUser: data.user,
        });
        return true;
      }
      set({ error: data.detail || "登录失败" });
      return false;
    } catch (e) {
      set({ error: String(e) });
      return false;
    }
  },

  register: async (username: string, password: string, providerName: string) => {
    try {
      const data = await api.register(username, password, providerName);
      if (data.success) {
        set({
          isAuthenticated: true,
          currentUser: data.user,
        });
        return true;
      }
      set({ error: data.detail || "注册失败" });
      return false;
    } catch (e) {
      set({ error: String(e) });
      return false;
    }
  },

  logout: () => {
    localStorage.removeItem("provider_token");
    localStorage.removeItem("provider_username");
    set({
      isAuthenticated: false,
      currentUser: null,
      workspaces: [],
      activeWorkspace: null,
    });
  },

  loadConfig: async () => {
    // Web版本暂无配置管理
  },

  saveConfig: async (config: Config) => {
    set({ config });
  },

  loadWorkspaces: async () => {
    set({ isLoading: true });
    try {
      const workspaces = await api.getClients();
      set({ workspaces: Array.isArray(workspaces) ? workspaces : [], isLoading: false });
    } catch (e) {
      set({ error: String(e), isLoading: false });
    }
  },

  createWorkspace: async (customerName: string, industry: string) => {
    try {
      const data = await api.createClient(customerName, industry);
      if (data.success) {
        await get().loadWorkspaces();
        return data.id;
      }
      throw new Error(data.detail || "创建失败");
    } catch (e) {
      set({ error: String(e) });
      throw e;
    }
  },

  selectWorkspace: async (id: string) => {
    try {
      const workspace = await api.getClient(parseInt(id));
      set({ activeWorkspace: workspace });
    } catch (e) {
      set({ error: String(e) });
    }
  },

  updateWorkspace: async (workspace: Workspace) => {
    try {
      await api.updateClient(workspace.id, workspace);
      set({ activeWorkspace: workspace });
      await get().loadWorkspaces();
    } catch (e) {
      set({ error: String(e) });
    }
  },

  deleteWorkspace: async (id: string) => {
    try {
      await api.deleteClient(parseInt(id));
      set({ activeWorkspace: null });
      await get().loadWorkspaces();
    } catch (e) {
      set({ error: String(e) });
    }
  },

  setCurrentStep: (step: WorkflowStep) => {
    set({ currentStep: step });
  },

  clearActiveWorkspace: () => {
    set({ activeWorkspace: null, currentStep: 1 });
  },

  clearError: () => {
    set({ error: null });
  },

  // 知识库
  searchKnowledge: async (industry: string, keywords: string[] = []) => {
    return api.searchKnowledge(industry, keywords);
  },

  getProviderKnowledge: async (category: string = "") => {
    return api.getProviderKnowledge(category);
  },

  addProviderKnowledge: async (data: any) => {
    return api.addProviderKnowledge(data);
  },

  getKnowledgeStats: async () => {
    return api.getKnowledgeStats();
  },

  // 报告
  generateReport: async (clientId: number, transcript: string) => {
    const data = await api.generateReport(clientId, transcript);
    return data.report || "";
  },

  // 企业微信
  createWecomSmartTable: async (data: any) => {
    return api.createWecomSmartTable(data);
  },
}));
