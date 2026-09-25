/* Hook de subtítulos: se suscribe al WebSocket de audiencia con reconexión automática. */

import { useCallback, useEffect, useRef, useState } from "react";
import { wsUrl, type AudienceSnapshot } from "./api";

export interface SubtitleEvent {
  type: "caption" | "state";
  lang: string;
  kind?: "partial" | "final";
  text?: string;
  seq?: number;
  state?: string;
  error?: string;
}

export interface SubtitleView {
  connected: boolean;
  live: boolean;
  lang: string;
  partial: string;
  finals: string[];
  snapshotOk: boolean;
  latencyMs: number;
  lastEventAt: number;
}

export function useSubtitles(sessionId: string | undefined, lang: string | undefined) {
  const [view, setView] = useState<SubtitleView>({
    connected: false,
    live: false,
    lang: lang ?? "",
    partial: "",
    finals: [],
    snapshotOk: false,
    latencyMs: 0,
    lastEventAt: 0,
  });
  const viewRef = useRef(view);
  viewRef.current = view;
  const retryRef = useRef(0);
  const wsRef = useRef<WebSocket | null>(null);

  const patch = useCallback((p: Partial<SubtitleView>) => {
    setView((prev) => {
      const next = { ...prev, ...p };
      return next;
    });
  }, []);

  useEffect(() => {
    if (!sessionId || !lang) return;
    let closed = false;

    const onEvent = (m: SubtitleEvent | AudienceSnapshot) => {
      if (m.type === "snapshot") {
        patch({
          lang: m.lang,
          partial: m.partial || "",
          finals: (m.segments || []).map((s) => s.text),
          snapshotOk: true,
          live: m.state === "live",
        });
      } else if (m.type === "caption") {
        if (m.kind === "partial") {
          patch({ partial: m.text ?? "", lastEventAt: Date.now() });
        } else if (m.kind === "final") {
          setView((prev) => {
            const finals = [...prev.finals, m.text ?? ""].slice(-20);
            return { ...prev, partial: "", finals, lastEventAt: Date.now() };
          });
        }
      } else if (m.type === "state") {
        patch({ live: m.state === "live" });
      }
    };

    const connect = () => {
      if (closed) return;
      const ws = new WebSocket(wsUrl(sessionId!, lang!));
      wsRef.current = ws;
      ws.onopen = () => {
        retryRef.current = 0;
        patch({ connected: true });
      };
      ws.onmessage = (ev) => {
        try {
          onEvent(JSON.parse(ev.data));
        } catch {}
      };
      ws.onclose = () => {
        patch({ connected: false, live: false });
        if (!closed) {
          const backoff = Math.min(15000, 800 * 2 ** retryRef.current++);
          setTimeout(connect, backoff);
        }
      };
      ws.onerror = () => ws.close();
    };

    connect();
    return () => {
      closed = true;
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [sessionId, lang, patch]);

  return view;
}

export function useNowInterval(intervalMs: number) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
}