import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowLeft,
  Download,
  Languages,
  Mic,
  Share2,
  Wifi,
  WifiOff,
  Zap,
} from "lucide-react";
import { TopBar } from "@/components/TopBar";
import { Badge } from "@/components/ui/fields";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  getSession,
  getSessions,
  LANG_NAMES,
  type LanguageInfo,
  type SessionInfo,
} from "@/lib/api";
import { useNowInterval, useSubtitles } from "@/lib/subtitles";
import { cn } from "@/lib/utils";

const STATE_TONE: Record<string, string> = {
  live: "bg-emerald-400",
  warming: "bg-amber-400",
  idle: "bg-amber-400",
  paused: "bg-amber-400",
  queued: "bg-slate-400",
  error: "bg-red-400",
  stopped: "bg-red-400",
};

export function AudiencePage() {
  const { sid, lang } = useParams();
  const navigate = useNavigate();

  if (lang) return <Player sessionId={sid!} lang={lang} onBack={() => navigate(`/${sid}`)} />;
  if (sid) return <SessionPicker sid={sid} onExit={() => navigate("/")} />;
  return <SessionList onPick={(s, l) => navigate(`/${s}/${l}`)} />;
}

/* --------------------------- lista de sesiones --------------------------- */
function SessionList({ onPick }: { onPick: (sid: string, lang: string) => void }) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await getSessions();
      setSessions(data.sessions);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 8000);
    return () => clearInterval(id);
  }, [load]);

  return (
    <div className="min-h-full">
      <TopBar />
      <main className="mx-auto max-w-6xl px-5 py-8">
        <div className="mb-6">
          <h1 className="text-3xl font-extrabold tracking-tight">Sesiones en vivo</h1>
          <p className="mt-1 text-sm text-mute">
            Elegí una sesión y el idioma de los subtítulos: original o traducción simultánea (español por defecto).
          </p>
        </div>

        {error && (
          <Card className="mb-6 border-red-500/30 p-4 text-sm text-red-300">
            No se pudo conectar con el backend: {error}
          </Card>
        )}

        {sessions.length === 0 && !error && (
          <Card className="p-10 text-center">
            <p className="text-mute">Todavía no hay sesiones en vivo.</p>
            <p className="mt-2 text-sm text-mute">Cuando una charla arranque, va a aparecer acá.</p>
          </Card>
        )}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {sessions.map((s) => (
            <Card key={s.id} className="p-5 transition-colors hover:border-neon/50">
              <div className="flex items-center gap-2.5">
                <span className={cn("h-2.5 w-2.5 shrink-0 rounded-full", s.on_air ? "bg-emerald-400" : "bg-slate-500")} />
                <h3 className="truncate text-lg font-bold">{s.title}</h3>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-mute">
                {s.stage ? <Badge>{s.stage}</Badge> : null}
                <span>
                  Original: <b className="text-slate-300">{LANG_NAMES[s.original_language] ?? s.original_language}</b>
                </span>
                {s.ingesting && (
                  <span className="flex items-center gap-1 text-emerald-400">
                    <Mic className="size-3" /> señal en vivo
                  </span>
                )}
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                {s.languages.map((l) => (
                  <Button
                    key={l.lang}
                    size="sm"
                    variant="ghost"
                    className="border-edge hover:border-neon/50"
                    onClick={() => onPick(s.id, l.lang)}
                  >
                    {l.is_original ? <Mic className="size-3 text-neon" /> : <Languages className="size-3 text-neon" />}
                    {LANG_NAMES[l.lang] ?? l.lang}
                    <span className="text-mute">· {l.via}</span>
                  </Button>
                ))}
              </div>
            </Card>
          ))}
        </div>
      </main>
    </div>
  );
}

/* --------------------------- selector de idioma --------------------------- */
function SessionPicker({ sid, onExit }: { sid: string; onExit: () => void }) {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    getSession(sid).then(setSession).catch((e) => setError((e as Error).message));
  }, [sid]);

  return (
    <div className="min-h-full">
      <TopBar />
      <main className="mx-auto max-w-3xl px-5 py-8">
        <Button variant="ghost" size="sm" className="mb-6" onClick={onExit}>
          <ArrowLeft /> Todas las sesiones
        </Button>
        {error && (
          <Card className="mb-6 border-red-500/30 p-4 text-sm text-red-300">{error}</Card>
        )}
        <Card className="p-8">
          <h1 className="text-2xl font-extrabold">{session?.title ?? sid}</h1>
          <p className="mt-1 text-sm text-mute">
            {session?.stage ? `${session.stage} · ` : ""}Elegí el idioma de los subtítulos:
          </p>
          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            {session?.languages.map((l) => (
              <Button
                key={l.lang}
                size="lg"
                variant="primary"
                className="justify-start font-sans"
                onClick={() => navigate(`/${sid}/${l.lang}`)}
              >
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/10">
                  {l.is_original ? <Mic /> : <Languages />}
                </span>
                <span className="flex flex-col items-start leading-tight">
                  <span>{LANG_NAMES[l.lang] ?? l.lang}</span>
                  <span className="text-xs font-normal opacity-70">
                    {l.is_original ? "transcripción original" : `traducción simultánea · ${l.via}`}
                  </span>
                </span>
              </Button>
            )) ?? <p className="text-mute">Cargando…</p>}
          </div>
        </Card>
      </main>
    </div>
  );
}

/* ------------------------------- reproductor ------------------------------ */
function Player({
  sessionId,
  lang,
  onBack,
}: {
  sessionId: string;
  lang: string;
  onBack: () => void;
}) {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const view = useSubtitles(sessionId, lang);
  useNowInterval(1000);

  useEffect(() => {
    getSession(sessionId)
      .then(setSession)
      .catch((e) => setError((e as Error).message));
  }, [sessionId]);

  const latency = view.lastEventAt ? Math.min(9999, Date.now() - view.lastEventAt) : null;
  const langInfo: LanguageInfo | undefined = useMemo(
    () => session?.languages.find((l) => l.lang === lang),
    [session, lang]
  );
  const finals = view.finals.slice(-3);

  return (
    <div className="flex min-h-full flex-col">
      <TopBar />
      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col px-5 py-6">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Button variant="ghost" size="sm" onClick={onBack}>
            <ArrowLeft /> Todas las sesiones
          </Button>
          <div className="ml-auto flex gap-2">
            <Button variant="ghost" size="sm" onClick={onBack}>
              <Languages /> Cambiar idioma
            </Button>
            <a
              className="inline-flex h-8 items-center gap-2 rounded-xl border border-edge px-3 text-xs text-slate-300 hover:border-neon/50 hover:text-white"
              href={`/api/sessions/${sessionId}/export?lang=${lang}&fmt=srt`}
              download
            >
              <Download /> SRT
            </a>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                navigator.clipboard?.writeText(
                  `${location.origin}/${sessionId}/${lang}`
                ).then(() => toast("Link copiado")).catch(() => {});
              }}
            >
              <Share2 /> Share
            </Button>
          </div>
        </div>

        {error && (
          <Card className="mb-4 border-red-500/30 p-4 text-sm text-red-300">
            {error} — ¿se creó esta sesión?{" "}
            <button className="underline" onClick={onBack}>volver a la lista</button>
          </Card>
        )}

        <Card className="relative flex flex-1 items-end overflow-hidden p-6 md:p-10">
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-ink/60 via-transparent to-transparent" />
          <div className="relative w-full">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
              <div>
                <h1 className="text-xl font-extrabold md:text-2xl">{session?.title ?? sessionId}</h1>
                <p className="text-sm text-mute">
                  {session?.stage ? `${session.stage} · ` : ""}
                  {langInfo?.is_original ? "transcripción original" : "traducción simultánea"}
                  {" · "}
                  {LANG_NAMES[lang] ?? lang}
                </p>
              </div>
              <Badge className="items-center gap-1.5">
                <span className={cn("h-2 w-2 rounded-full", STATE_TONE[view.live ? "live" : langInfo?.state ?? "idle"] ?? "bg-slate-400")} />
                {view.connected ? (view.live ? "en vivo" : "transcribiendo…") : "conectando…"}
              </Badge>
            </div>

            <div className="min-h-[140px]">
              <AnimatePresence mode="wait">
                {view.partial ? (
                  <motion.div
                    key="partial"
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    transition={{ duration: 0.18 }}
                    className="subtitle-glow text-3xl font-extrabold leading-tight text-neon md:text-5xl"
                  >
                    {view.partial}
                  </motion.div>
                ) : (
                  <motion.div
                    key="empty"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="text-lg text-mute"
                  >
                    {view.connected ? "Subtitle en camino…" : "Esperando señal de audio…"}
                  </motion.div>
                )}
              </AnimatePresence>

              <div className="mt-6 space-y-2">
                {finals.map((f, i) => (
                  <motion.p
                    key={`${i}-${f.slice(0, 12)}`}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    className={cn("text-slate-300", i === finals.length - 1 ? "text-xl font-bold text-slate-100" : "text-sm text-slate-500")}
                  >
                    {f}
                  </motion.p>
                ))}
              </div>
            </div>
          </div>
        </Card>

        <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-mute">
          <span className="inline-flex items-center gap-1.5">
            {view.connected ? <Wifi className="size-4 text-emerald-400" /> : <WifiOff className="size-4 text-amber-400" />}
            {view.connected ? "conectado" : "reconectando"}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Zap className="size-4 text-neon" />
            latencia {latency === null ? "—" : `${latency} ms`}
          </span>
          <span>
            provider: <span className="font-mono">{session?.provider ?? "…"}</span> · modo traducción{" "}
            <span className="font-mono">{session?.translation_mode ?? "…"}</span>
          </span>
        </div>
      </main>
    </div>
  );
}

let toastTimer: ReturnType<typeof setTimeout> | undefined;
function toast(msg: string) {
  const el = document.getElementById("toast-slot");
  if (!el) return;
  el.textContent = msg;
  el.classList.remove("opacity-0");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("opacity-0"), 2000);
}