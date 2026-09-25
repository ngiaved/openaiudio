/* Cliente de API tipado del backend OpenAIudio. */

export const TARGET_RATE = 16000;

export const LANG_NAMES: Record<string, string> = {
  es: "Español",
  en: "English",
  pt: "Português",
  de: "Deutsch",
  fr: "Français",
  it: "Italiano",
  ja: "日本語",
  ko: "한국어",
  zh: "中文",
  ru: "Русский",
  ar: "العربية",
  hi: "हिन्दी",
  other: "Otro",
};

export type ProviderKind = "gemini" | "local" | "mock";
export type TranslationMode = "audio" | "text" | "auto";

export interface LanguageInfo {
  lang: string;
  name: string;
  kind: "original" | "translate";
  via: "audio" | "text";
  state: string;
  is_original: boolean;
  error: string;
  partial: string;
  preview: string;
}

export interface SessionInfo {
  id: string;
  title: string;
  stage: string;
  provider: ProviderKind;
  translation_mode: TranslationMode;
  original_language: string;
  created_at: number;
  on_air: boolean;
  ingesting: boolean;
  glossary: Record<string, string>[];
  languages: LanguageInfo[];
  audience_total: number;
  vendor_id: string;
  fallback_vendor_id: string | null;
  stt_model: string;
  translate_model: string;
  session_out_active_vendors?: Record<string, string>;
}

export interface CaptionSegment {
  seq: number;
  text: string;
  t0: number;
  t1: number;
}

export interface AudienceSnapshot {
  type: "snapshot";
  session: string;
  title: string;
  stage: string;
  lang: string;
  original_language: string;
  kind: "original" | "translate";
  state: string;
  partial: string;
  segments: CaptionSegment[];
}

export interface AdminTarget {
  lang: string;
  kind: string;
  via: string;
  state: string;
  errors: number;
  error: string;
  audience: number;
  partial: string;
  segments: number;
  provider: string | null;
}

export interface AdminSession {
  id: string;
  title: string;
  stage: string;
  provider: string;
  translation_mode: string;
  original_language: string;
  on_air: boolean;
  created_at: number;
  last_audio_at: number;
  targets: AdminTarget[];
}

export interface AdminStatus {
  active_providers: number;
  max_providers: number;
  sessions_count: number;
  max_sessions: number;
  model: string;
  audience_top: [string, string, number][];
  sessions: AdminSession[];
}

export interface VendorInfo {
  id: string;
  name: string;
  protocol: string;
  builtin: boolean;
  enabled: boolean;
  has_api_key: boolean;
  api_key_masked: string;
  api_key?: string;
  base_url: string;
  stt_model: string;
  translate_model: string;
  live_model: string;
  supports_stt: boolean;
  supports_translate: boolean;
  stt_mode: string;
  azure_endpoint: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${body ? `: ${body.slice(0, 160)}` : ""}`);
  }
  return res.json() as Promise<T>;
}

export function getSessions(): Promise<{ sessions: SessionInfo[] }> {
  return request("/api/sessions");
}

export function getSession(id: string): Promise<SessionInfo> {
  return request(`/api/sessions/${encodeURIComponent(id)}`);
}

export function createSession(body: {
  title: string;
  stage?: string | null;
  original_language: string;
  targets: { lang: string; kind: "translate"; via?: "audio" | "text" }[];
  provider?: ProviderKind | null;
  translation_mode?: TranslationMode | null;
  vendor_id?: string | null;
  fallback_vendor_id?: string | null;
  stt_model?: string | null;
  translate_model?: string | null;
}): Promise<SessionInfo> {
  return request("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function switchVendors(sessionId: string): Promise<SessionInfo> {
  return request(`/api/sessions/${encodeURIComponent(sessionId)}/switch`, { method: "POST" });
}

export function getVendors(): Promise<{ vendors: VendorInfo[] }> {
  return request("/api/vendors");
}

export function createVendor(body: Partial<VendorInfo> & { name: string }): Promise<VendorInfo> {
  return request("/api/vendors", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function updateVendor(id: string, body: Partial<VendorInfo>): Promise<VendorInfo> {
  return request(`/api/vendors/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteVendor(id: string): Promise<Response> {
  return fetch(`/api/vendors/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function testVendor(id: string): Promise<{ ok: boolean; vendor: string; detail: string }> {
  return request(`/api/vendors/${encodeURIComponent(id)}/test`, { method: "POST" });
}

export function deleteSession(id: string): Promise<Response> {
  return fetch(`/api/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function getAdminStatus(): Promise<AdminStatus> {
  return request("/api/admin/status");
}

export function wsUrl(sessionId: string, lang: string): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws/audience/${encodeURIComponent(sessionId)}?lang=${encodeURIComponent(lang)}`;
}

export function ingestWsUrl(sessionId: string, sampleRate: number): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws/ingest/${encodeURIComponent(sessionId)}?sample_rate=${sampleRate}`;
}