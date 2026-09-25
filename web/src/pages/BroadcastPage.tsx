import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, Mic, MicOff, RadioTower, Trash2, XCircle } from "lucide-react";
import { TopBar } from "@/components/TopBar";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/fields";
import {
  createSession,
  deleteSession,
  getSession,
  getSessions,
  getVendors,
  ingestWsUrl,
  LANG_NAMES,
  switchVendors,
  type LanguageInfo,
  type ProviderKind,
  type SessionInfo,
  type TranslationMode,
  type VendorInfo,
} from "@/lib/api";
import { captureFile, captureMic, captureSystemAudio, listAudioDevices, resampleTo16k, type AudioDevice, type CaptureHandle } from "@/lib/audio";
import { cn } from "@/lib/utils";

const ALL_TARGETS = ["es", "en", "pt", "fr", "de"];

export function BroadcastPage() {
  const [picked, setPicked] = useState<string>("");
  const [existing, setExisting] = useState<SessionInfo[]>([]);
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [vendors, setVendors] = useState<VendorInfo[]>([]);

  const refresh = useCallback(async () => {
    try {
      const data = await getSessions();
      setExisting(data.sessions);
    } catch {}
    try {
      const vd = await getVendors();
      setVendors(vd.vendors.filter((v) => v.enabled || v.builtin));
    } catch {}
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 8000);
    return () => clearInterval(id);
  }, [refresh]);

  const onCreated = (s: SessionInfo) => {
    setPicked("");
    setSession(s);
    refresh();
  };

  return (
    <div className="min-h-full">
      <TopBar />
      <main className="mx-auto grid max-w-6xl gap-5 px-5 py-8 lg:grid-cols-2">
        <CreateCard
          onCreated={onCreated}
          existing={existing}
          onJoin={(s) => setSession(s)}
          picked={picked}
          setPicked={setPicked}
          vendors={vendors}
        />
        <TransmitCard session={session} onClose={() => setSession(null)} onDelete={async (id) => { await deleteSession(id); setSession(null); refresh(); }} />
      </main>
    </div>
  );
}

function CreateCard({
  existing,
  onCreated,
  onJoin,
  picked,
  setPicked,
  vendors,
}: {
  existing: SessionInfo[];
  onCreated: (s: SessionInfo) => void;
  onJoin: (s: SessionInfo) => void;
  picked: string;
  setPicked: (id: string) => void;
  vendors: VendorInfo[];
}) {
  const [title, setTitle] = useState("");
  const [stage, setStage] = useState("");
  const [orig, setOrig] = useState("en");
  const [targets, setTargets] = useState<string[]>(["es"]);
  const [provider, setProvider] = useState<"" | ProviderKind>("");
  const [mode, setMode] = useState<"" | TranslationMode>("");
  const [vendorId, setVendorId] = useState<string>("");
  const [fallbackId, setFallbackId] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);

  const toggleTarget = (t: string) =>
    setTargets((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));

  const onCreate = async () => {
    setErr(null);
    if (!title.trim()) return setErr("Falta el título de la charla.");
    try {
      const s = await createSession({
        title: title.trim(),
        stage: stage.trim() || null,
        original_language: orig,
        targets: targets.map((l) => ({ lang: l, kind: "translate" as const })),
        provider: provider || null,
        translation_mode: mode || null,
        vendor_id: vendorId || null,
        fallback_vendor_id: fallbackId || null,
      });
      onCreated(s);
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const handleJoin = async () => {
    setErr(null);
    if (!picked) return;
    try {
      onJoin(await getSession(picked));
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Nueva sesión</CardTitle>
        <CardDescription>Creá la sesión para un escenario y transmití el audio del stage desde esta laptop (o unirme a una sesión ya existente).</CardDescription>
      </CardHeader>
      <CardContent className="space-y-1">
        <Label>Título de la charla</Label>
        <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ej: Keynote de apertura" maxLength={200} />

        <Label>Escenario / stage</Label>
        <Input value={stage} onChange={(e) => setStage(e.target.value)} placeholder="Ej: Escenario B" maxLength={100} />

        <Label>Idioma original (speaker)</Label>
        <Select value={orig} onChange={(e) => setOrig(e.target.value)}>
          {Object.entries(LANG_NAMES).map(([code, name]) => (
            <option key={code} value={code}>{name}</option>
          ))}
        </Select>

        <Label>Traducciones a generar</Label>
        <div className="flex flex-wrap gap-2 pt-1">
          {ALL_TARGETS.map((t) => (
            <button
              key={t}
              type="button"
              className={cn(
                "rounded-full border px-3 py-1 text-sm transition-colors",
                targets.includes(t)
                  ? "border-neon/60 bg-neon/10 text-neon"
                  : "border-edge text-mute hover:border-neon/40 hover:text-slate-200"
              )}
              onClick={() => toggleTarget(t)}
            >
              {LANG_NAMES[t]}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label>Provider</Label>
            <Select value={provider} onChange={(e) => setProvider(e.target.value as "" | ProviderKind)}>
              <option value="">auto (recomendado)</option>
              <option value="gemini">gemini · Gemini Live</option>
              <option value="local">local · whisper + Gemma</option>
              <option value="mock">mock · demo sin costo</option>
            </Select>
          </div>
          <div>
            <Label>Traducción</Label>
            <Select value={mode} onChange={(e) => setMode(e.target.value as "" | TranslationMode)}>
              <option value="">auto</option>
              <option value="audio">audio · Live (mejor latencia)</option>
              <option value="text">text · translation API (más barato)</option>
            </Select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label>Vendor primario</Label>
            <Select value={vendorId} onChange={(e) => setVendorId(e.target.value)}>
              <option value="">(default)</option>
              {vendors.map((v) => (
                <option key={v.id} value={v.id} disabled={!v.enabled}>{v.name}{v.enabled ? "" : " ✕"}</option>
              ))}
            </Select>
          </div>
          <div>
            <Label>Vendor fallback</Label>
            <Select value={fallbackId} onChange={(e) => setFallbackId(e.target.value)}>
              <option value="">(sin fallback)</option>
              {vendors.map((v) => (
                <option key={v.id} value={v.id} disabled={!v.enabled || v.id === vendorId}>{v.name}</option>
              ))}
            </Select>
          </div>
        </div>

        {err && <p className="mt-3 text-sm text-red-400">{err}</p>}

        <Button variant="primary" className="mt-4 w-full" onClick={onCreate}>
          <RadioTower /> Crear sesión y transmitir
        </Button>

        <div className="my-4 h-px bg-edge/60" />
        <Label>Unirse a una sesión existente</Label>
        <div className="flex gap-2">
          <Select value={picked} onChange={(e) => setPicked(e.target.value)} className="flex-1">
            <option value="">{existing.length ? "elegir sesión…" : "(no hay sesiones)"}</option>
            {existing.map((s) => (
              <option key={s.id} value={s.id}>{s.title} · {s.id}</option>
            ))}
          </Select>
          <Button onClick={handleJoin} disabled={!picked}>Transmitir</Button>
        </div>
      </CardContent>
    </Card>
  );
}

function TransmitCard({ session, onClose, onDelete }: {
  session: SessionInfo | null;
  onClose: () => void;
  onDelete: (id: string) => void;
}) {
  const [, setWsState] = useState<"closed" | "open" | "error">("closed");
  const [onAir, setOnAir] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [bytes, setBytes] = useState(0);
  const [meter, setMeter] = useState(0);
  const [langs, setLangs] = useState<LanguageInfo[]>([]);
  const [micErr, setMicErr] = useState<string | null>(null);
  const [source, setSource] = useState<"mic" | "system" | "file">("mic");
  const [deviceId, setDeviceId] = useState<string>("");
  const [devices, setDevices] = useState<AudioDevice[]>([]);
  const [activeVendors, setActiveVendors] = useState<Record<string, string>>({});

  const wsRef = useRef<WebSocket | null>(null);
  const capRef = useRef<CaptureHandle | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const startedRef = useRef(0);
  const bytesRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    listAudioDevices().then(setDevices).catch(() => {});
  }, []);

  const stop = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      try { wsRef.current.send(JSON.stringify({ type: "control", cmd: "stop" })); } catch {}
    }
    wsRef.current?.close();
    wsRef.current = null;
    capRef.current?.close();
    capRef.current = null;
    if (timerRef.current) clearInterval(timerRef.current);
    if (pollRef.current) clearInterval(pollRef.current);
    timerRef.current = null;
    pollRef.current = null;
    setWsState("closed");
    setOnAir(false);
  }, []);

  useEffect(() => stop, [stop]);

  useEffect(() => {
    if (!session) return;
    setElapsed(0);
    setBytes(0);
    bytesRef.current = 0;
    setMeter(0);
    setLsFromSession(session);
    pollRef.current = setInterval(async () => {
      try {
        const s = await getSession(session.id);
        setLsFromSession(s);
        setActiveVendors(s.session_out_active_vendors ?? {});
      } catch {}
    }, 2500);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [session?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  function setLsFromSession(s: SessionInfo) {
    setLangs(s.languages);
  }

  const runCapture = async (cap: CaptureHandle) => {
    const ws = new WebSocket(ingestWsUrl(session!.id, cap.sampleRate));
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;
    ws.onopen = () => ws.send(JSON.stringify({ engine: "browser", sampleRate: cap.sampleRate, source }));
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "hello") {
        setOnAir(true);
        setWsState("open");
        startedRef.current = Date.now();
        timerRef.current = setInterval(() => setElapsed((Date.now() - startedRef.current) / 1000), 500);
      }
    };
    ws.onclose = () => setWsState("closed");
    ws.onerror = () => setWsState("error");

    cap.setHandler((i16, rms) => {
      const db = 20 * Math.log10(Math.max(rms, 1e-9));
      setMeter(Math.min(100, Math.max(0, (db + 50) * 2)));
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(resampleTo16k(i16, cap.sampleRate).buffer);
        bytesRef.current += i16.length * 2;
        setBytes(bytesRef.current);
      }
    });
  };

  const startStream = async () => {
    if (!session) return;
    setMicErr(null);
    let cap: CaptureHandle | null = null;
    try {
      if (source === "system") {
        cap = await captureSystemAudio();
      } else if (source === "mic") {
        cap = await captureMic(deviceId || undefined);
      } else {
        throw new Error("elegí un archivo de audio primero");
      }
    } catch (e) {
      setMicErr((e as Error).message);
      return;
    }
    capRef.current = cap;
    await runCapture(cap);
  };

  const onFile = async (f: File | null) => {
    if (!f) return;
    setMicErr(null);
    try {
      const cap = await captureFile(f);
      capRef.current = cap;
      await runCapture(cap);
    } catch (e) {
      setMicErr((e as Error).message);
    }
  };

  const onSwitch = async () => {
    if (!session?.fallback_vendor_id) return;
    try {
      const s = await switchVendors(session.id);
      setLsFromSession(s);
      setActiveVendors(s.session_out_active_vendors ?? {});
    } catch (e) {
      setMicErr((e as Error).message);
    }
  };

  const stopStream = () => stop();

  return (
    <Card className="lg:sticky lg:top-20">
      <CardHeader className="flex-row items-start justify-between space-y-0">
        <div>
          <CardTitle>{session ? session.title : "Transmisión"}</CardTitle>
          <CardDescription className="mt-1">
            {session
              ? `${session.id} · original ${LANG_NAMES[session.original_language] ?? session.original_language} · ${session.provider} · traducción ${session.translation_mode}`
              : "Creá o uníte a una sesión para transmitir el audio del escenario."}
          </CardDescription>
        </div>
        {session && (
          <div className="flex gap-1.5">
            <Link to={`/${session.id}/${session.original_language}`} className="rounded-lg border border-edge px-2.5 py-1 text-xs hover:border-neon/50">
              Ver ↗
            </Link>
            <Button variant="danger" size="sm" onClick={() => onDelete(session.id)}>
              <Trash2 /> <span className="hidden sm:inline">Eliminar</span>
            </Button>
          </div>
        )}
      </CardHeader>
      <CardContent>
        {!session ? (
          <p className="py-16 text-center text-sm text-mute">Sin sesión activa.</p>
        ) : (
          <>
            <div className="mb-5 grid grid-cols-3 gap-3">
              <Stat k="Conexión" v={onAir ? "● encendida" : "apagada"} tone={onAir ? "text-emerald-400" : "text-mute"} />
              <Stat k="Tiempo" v={`${Math.floor(elapsed / 60)}:${String(Math.floor(elapsed % 60)).padStart(2, "0")}`} mono />
              <Stat k="Audio" v={`${(bytes / 1024).toFixed(0)} KiB`} mono />
            </div>

            <div className="mb-5 h-2 overflow-hidden rounded-full border border-edge bg-ink/60">
              <div
                className="h-full rounded-full bg-gradient-to-r from-neon-dark to-neon transition-[width]"
                style={{ width: `${meter}%` }}
              />
            </div>

            <div className="flex flex-wrap gap-2">
              <Button variant={onAir ? "danger" : "primary"} onClick={onAir ? stopStream : startStream}>
                {onAir ? <><MicOff /> Detener</> : <><Mic /> Iniciar micrófono</>}
              </Button>
              <Button variant="ghost" onClick={onClose}>Desconectar sesión</Button>
              {session?.fallback_vendor_id && (
                <Button variant="ghost" onClick={onSwitch} title="Conmutar manualmente primario ↔ fallback">
                  Cambiar vendor (fallback)
                </Button>
              )}
            </div>

            <div className="mt-4 grid grid-cols-1 gap-3 rounded-xl border border-edge bg-ink/40 p-3 sm:grid-cols-2">
              <div>
                <Label>Fuente de audio</Label>
                <Select value={source} onChange={(e) => setSource(e.target.value as "mic" | "system" | "file")}>
                  <option value="mic">Micrófono</option>
                  <option value="system">Audio del sistema (pantalla/tab)</option>
                  <option value="file">Archivo local</option>
                </Select>
              </div>
              {source === "mic" && (
                <div>
                  <Label>Dispositivo</Label>
                  <Select value={deviceId} onChange={(e) => setDeviceId(e.target.value)} disabled={devices.length === 0}>
                    <option value="">Default</option>
                    {devices.map((d) => (
                      <option key={d.id} value={d.id}>{d.label}</option>
                    ))}
                  </Select>
                </div>
              )}
              {source === "file" && (
                <div>
                  <Label>Archivo</Label>
                  <input ref={fileRef} type="file" accept="audio/*,.wav" className="block w-full text-sm text-mute file:mr-3 file:rounded-lg file:border-0 file:bg-panel-2 file:px-3 file:py-2 file:text-sm file:text-slate-100"
                    onChange={(e) => e.target.files && onFile(e.target.files[0])} />
                </div>
              )}
            </div>
            {source !== "file" && (
              <p className="mt-1 hidden text-xs text-mute">Elegí micrófono o sistema y pulsá iniciar; el audio se resamplea a 16 kHz PCM mono y se envía por WebSocket.</p>
            )}

            {micErr && <p className="mt-3 text-sm text-red-400">Audio: {micErr}</p>}

            <div className="mt-5 space-y-1.5 rounded-xl border border-edge bg-ink/40 p-3 font-mono text-xs">
              {langs.map((l) => (
                <div key={l.lang} className="flex items-start gap-2">
                  {/^(live|warming)/.test(l.state) ? (
                    <CheckCircle2 className="mt-0.5 size-3 text-emerald-400" />
                  ) : l.state === "error" ? (
                    <XCircle className="mt-0.5 size-3 text-red-400" />
                  ) : (
                    <XCircle className="mt-0.5 size-3 text-amber-400" />
                  )}
                  <div className="min-w-0">
                    <span className={cn("font-semibold", l.state === "live" ? "text-emerald-400" : "text-slate-300")}>
                      {LANG_NAMES[l.lang] ?? l.lang} · {l.kind} · {l.via}
                    </span>
                    <span className="ml-2 text-mute">[{l.state}]</span>
                    {activeVendors[l.lang] && (
                      <span className="ml-2 rounded bg-white/5 px-1 py-0 text-[10px] text-neon">{activeVendors[l.lang]}</span>
                    )}
                    <div className="truncate text-slate-500">▸ {l.partial || l.preview || "…"}</div>
                  </div>
                </div>
              ))}
              {langs.length === 0 && <div className="text-mute">…</div>}
            </div>

            <p className="mt-4 text-xs leading-relaxed text-mute">
              El navegador captura la fuente elegida (micrófono, audio de sistema o archivo), lo resamplea a 16 kHz
              PCM mono y lo envía por WebSocket. Abrí la <Link to="/" className="text-neon underline">vista de audiencia</Link> en
              otro dispositivo para ver los subtítulos.
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ k, v, tone, mono }: { k: string; v: string; tone?: string; mono?: boolean }) {
  return (
    <div className="rounded-xl border border-edge bg-ink/40 p-3">
      <div className="text-[10px] uppercase tracking-wider text-mute">{k}</div>
      <div className={cn("mt-0.5 truncate text-sm font-bold", tone ?? "text-slate-100", mono && "font-mono")}>{v}</div>
    </div>
  );
}