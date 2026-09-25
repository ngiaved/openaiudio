import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Activity, AlertTriangle, Server, Users } from "lucide-react";
import { TopBar } from "@/components/TopBar";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/fields";
import { getAdminStatus, LANG_NAMES, type AdminStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const STATE_TONE: Record<string, string> = {
  live: "bg-emerald-400",
  warming: "bg-amber-400",
  idle: "bg-amber-400",
  paused: "bg-slate-400",
  queued: "bg-slate-400",
  error: "bg-red-400",
  stopped: "bg-red-400",
};

export function AdminPage() {
  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState(0);

  const poll = useCallback(async () => {
    try {
      setStatus(await getAdminStatus());
      setUpdatedAt(Date.now());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    poll();
    const id = setInterval(poll, 2000);
    return () => clearInterval(id);
  }, [poll]);

  return (
    <div className="min-h-full">
      <TopBar />
      <main className="mx-auto max-w-6xl px-5 py-8">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-3xl font-extrabold tracking-tight">Panel de producción</h1>
            <p className="mt-1 text-sm text-mute">Estado de cada sesión, idioma y provider en tiempo real (actualiza cada 2 s).</p>
          </div>
          {error && <Badge className="border-red-500/40 text-red-300">backend: {error}</Badge>}
        </div>

        <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Tile icon={<Activity className="size-4 text-neon" />} k="Providers activos" v={status ? `${status.active_providers}/${status.max_providers}` : "—"} />
          <Tile icon={<Server className="size-4 text-neon" />} k="Sesiones" v={status ? `${status.sessions_count}/${status.max_sessions}` : "—"} />
          <Tile icon={<Users className="size-4 text-neon" />} k="Audiencia (top)" v={String(status ? status.audience_top[0]?.[2] ?? 0 : "—")} />
          <Tile k="Modelo" v={status?.model ?? "—"} mono />
        </div>

        <Card className="overflow-x-auto p-0">
          <table className="w-full min-w-[820px] text-sm">
            <thead>
              <tr className="border-b border-edge text-left text-[11px] uppercase tracking-wider text-mute">
                <th className="px-4 py-3">Sesión</th>
                <th className="px-3 py-3">Idioma</th>
                <th className="px-3 py-3">Rol / vía</th>
                <th className="px-3 py-3">Estado</th>
                <th className="px-3 py-3 text-right">Err</th>
                <th className="px-3 py-3 text-right">Aud</th>
                <th className="px-3 py-3 text-right">Segs</th>
                <th className="px-4 py-3">Parcial</th>
              </tr>
            </thead>
            <tbody>
              {!status && (
                <tr><td colSpan={8} className="px-4 py-6 text-mute">Cargando…</td></tr>
              )}
              {status && status.sessions.length === 0 && (
                <tr><td colSpan={8} className="px-4 py-6 text-mute">Sin sesiones.</td></tr>
              )}
              {status?.sessions.map((s) => (
                <TargetRows key={s.id} session={s} />
              ))}
            </tbody>
          </table>
        </Card>

        <p className="mt-3 text-xs text-mute">
          Última actualización {updatedAt ? new Date(updatedAt).toLocaleTimeString() : "—"}.
          Enlaces útiles: <a className="text-neon underline" href="/api/admin/status">/api/admin/status</a> ·
          <a className="text-neon underline" href="/api/sessions">/api/sessions</a> ·
          <a className="text-neon underline" href="/healthz">/healthz</a>
        </p>
      </main>
    </div>
  );
}

function TargetRows({ session }: { session: NonNullable<AdminStatus["sessions"]>[number] }) {
  const anyLive = session.on_air;
  return (
    <>
      {session.targets.map((t, i) => (
        <tr key={t.lang} className="border-b border-edge/50 hover:bg-white/[0.02]">
          {i === 0 && (
            <>
              <td rowSpan={session.targets.length} className="px-4 py-2.5">
                <div className="flex items-center gap-1.5 font-semibold">
                  <span className={cn("h-2 w-2 rounded-full", anyLive ? "bg-emerald-400" : "bg-slate-600")} />
                  <span className="truncate max-w-[180px]">{session.title}</span>
                </div>
                <div className="mt-0.5 text-[11px] text-mute">
                  {session.id} · {session.provider} · {session.translation_mode}
                  {session.stage ? ` · ${session.stage}` : ""}
                </div>
              </td>
            </>
          )}
          <td className="px-3 py-2.5 font-medium">{LANG_NAMES[t.lang] ?? t.lang}</td>
          <td className="px-3 py-2.5 text-mute">{t.kind} / <span className="font-mono text-xs">{t.via}</span></td>
          <td className="px-3 py-2.5">
            <span className="inline-flex items-center gap-1.5 text-xs">
              <span className={cn("h-2 w-2 rounded-full", STATE_TONE[t.state] ?? "bg-slate-400")} />
              {t.state}
              {t.provider ? <span className="font-mono text-mute">({t.provider})</span> : null}
            </span>
            {t.error && (
              <div className="mt-1 flex items-start gap-1 text-[11px] leading-snug text-red-400">
                <AlertTriangle className="mt-0.5 size-3 shrink-0" />
                <span className="break-words whitespace-pre-wrap">{t.error}</span>
              </div>
            )}
          </td>
          <td className={cn("px-3 py-2.5 text-right font-mono", t.errors ? "text-red-400" : "text-mute")}>{t.errors}</td>
          <td className="px-3 py-2.5 text-right font-mono">{t.audience}</td>
          <td className="px-3 py-2.5 text-right font-mono">{t.segments}</td>
          <td className="max-w-[260px] truncate px-4 py-2.5 font-mono text-xs text-slate-400">
            {t.partial || "…"}
          </td>
        </tr>
      ))}
    </>
  );
}

function Tile({ k, v, icon, mono }: { k: string; v: string; icon?: ReactNode; mono?: boolean }) {
  return (
    <Card className="p-4">
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-mute">
        {icon} {k}
      </div>
      <div className={cn("mt-1 text-2xl font-extrabold", mono && "font-mono text-lg")}>{v}</div>
    </Card>
  );
}