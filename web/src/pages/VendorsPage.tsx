import { useCallback, useEffect, useState } from "react";
import { FlaskConical, Plus, RefreshCw, Settings2, Trash2 } from "lucide-react";
import { TopBar } from "@/components/TopBar";
import { Badge } from "@/components/ui/fields";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/fields";
import { createVendor, deleteVendor, getVendors, testVendor, updateVendor, type VendorInfo } from "@/lib/api";

const EMPTY: Omit<VendorInfo, "id" | "api_key_masked" | "builtin" | "has_api_key"> = {
  name: "",
  protocol: "openai",
  enabled: true,
  supports_stt: true,
  supports_translate: true,
  stt_mode: "whisper",
  stt_model: "",
  translate_model: "",
  live_model: "",
  base_url: "",
  azure_endpoint: "",
};

export function VendorsPage() {
  const [vendors, setVendors] = useState<VendorInfo[]>([]);
  const [edit, setEdit] = useState<Partial<VendorInfo>>({});
  const [isNew, setIsNew] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await getVendors();
      setVendors(data.vendors);
    } catch {}
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const save = async () => {
    setErr(null);
    setOk(null);
    try {
      if (isNew || !edit.id) {
        await createVendor({ ...EMPTY, ...edit });
      } else {
        await updateVendor(edit.id, edit);
      }
      await refresh();
      setEdit({});
      setIsNew(false);
      setOk("Vendor guardado.");
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const toggleEnabled = async (v: VendorInfo) => {
    try {
      await updateVendor(v.id, { ...v, enabled: !v.enabled });
      await refresh();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const onTest = async (v: VendorInfo) => {
    setTesting(v.id);
    setErr(null);
    setOk(null);
    try {
      const r = await testVendor(v.id);
      setOk(`${v.name}: ${r.ok ? "OK" : "falla"} — ${r.detail}`);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setTesting(null);
    }
  };

  const onDelete = async (v: VendorInfo) => {
    if (v.builtin) return;
    try {
      await deleteVendor(v.id);
      await refresh();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  return (
    <div className="min-h-full">
      <TopBar />
      <main className="mx-auto grid max-w-6xl gap-5 px-5 py-8 lg:grid-cols-2">
        <div>
          <div className="mb-3 flex items-center gap-2">
            <h1 className="text-lg font-bold">Vendors de modelos</h1>
            <Button variant="ghost" size="sm" onClick={() => { setEdit({ ...EMPTY, enabled: true }); setIsNew(true); setErr(null); setOk(null); }}>
              <Plus /> Nuevo custom
            </Button>
            <Button variant="ghost" size="sm" onClick={refresh}><RefreshCw /></Button>
          </div>

          <div className="space-y-3">
            {vendors.map((v) => (
              <Card key={v.id}>
                <CardContent className="flex items-center gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-slate-100">{v.name}</span>
                      <Badge>{v.protocol}</Badge>
                      {v.builtin ? <Badge>built-in</Badge> : <Badge className="border-neon/40 text-neon">custom</Badge>}
                      <button
                        type="button"
                        className={`rounded-full border px-2 py-0.5 text-xs transition-colors ${v.enabled ? "border-emerald-400/40 text-emerald-400" : "border-amber-400/40 text-amber-400"}`}
                        onClick={() => toggleEnabled(v)}
                        title={v.enabled ? "Deshabilitar este vendor" : "Habilitar este vendor"}
                      >
                        {v.enabled ? "on" : "off"}
                      </button>
                    </div>
                    <div className="mt-1 truncate text-xs text-mute">
                      STT {v.stt_model || "—"} ({v.stt_mode}) · traducción {v.translate_model || "—"} · key {v.api_key_masked || "sin key"}
                    </div>
                  </div>
                  <Button variant="ghost" size="sm" onClick={() => { setEdit({ ...v }); setIsNew(false); setErr(null); setOk(null); }}>
                    <Settings2 />
                  </Button>
                  <Button variant="ghost" size="sm" disabled={testing === v.id} onClick={() => onTest(v)} title="Probar conexión">
                    <FlaskConical className={testing === v.id ? "animate-pulse" : ""} />
                  </Button>
                  {!v.builtin && (
                    <Button variant="ghost" size="sm" onClick={() => onDelete(v)}><Trash2 /></Button>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
          {ok && <p className="mt-3 text-sm text-emerald-400">{ok}</p>}
          {err && <p className="mt-3 text-sm text-red-400">{err}</p>}
        </div>

        {(isNew || edit.id) && (
          <div>
            <Card>
              <CardHeader>
                <CardTitle>{isNew ? "Nuevo vendor custom" : `Configurar ${edit.name}`}</CardTitle>
                <CardDescription>
                  Los vendors custom se guardan en data/vendors.json (la key nunca se expone en el listado). Los
                  built-in solo permiten editar modelos y encendido/apagado.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {isNew && (
                  <>
                    <Label>Nombre</Label>
                    <Input value={edit.name ?? ""} onChange={(e) => setEdit({ ...edit, name: e.target.value })} placeholder="Ej: Mi GPU NVIDIA" />
                  </>
                )}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label>Protocolo</Label>
                    <Select value={edit.protocol ?? "openai"} onChange={(e) => setEdit({ ...edit, protocol: e.target.value })} disabled={!isNew}>
                      <option value="openai">OpenAI-compatible</option>
                      <option value="anthropic">Anthropic Messages</option>
                      <option value="azure">Azure OpenAI</option>
                    </Select>
                  </div>
                  <div>
                    <Label>stt_mode</Label>
                    <Select value={edit.stt_mode ?? "whisper"} onChange={(e) => setEdit({ ...edit, stt_mode: e.target.value as VendorInfo["stt_mode"] })}>
                      <option value="whisper">whisper (transcripciones)</option>
                      <option value="inline_audio">inline_audio (chat)</option>
                      <option value="windowed">windowed</option>
                      <option value="none">sin STT</option>
                    </Select>
                  </div>
                </div>

                <Label>Base URL (API)</Label>
                <Input value={edit.base_url ?? ""} onChange={(e) => setEdit({ ...edit, base_url: e.target.value })} placeholder="https://api.…/v1" />
                {edit.protocol === "azure" && (
                  <>
                    <Label>Azure endpoint (deployments)</Label>
                    <Input value={edit.azure_endpoint ?? ""} onChange={(e) => setEdit({ ...edit, azure_endpoint: e.target.value })} placeholder="https://<res>.openai.azure.com/openai/deployments/<dep>" />
                  </>
                )}
                {isNew && (
                  <>
                    <Label>API key</Label>
                    <Input value={edit.api_key ?? ""} type="password" onChange={(e) => setEdit({ ...edit, api_key: e.target.value })} placeholder={edit.has_api_key ? "dejá vacío para conservar la actual" : "sk-…"} />
                  </>
                )}

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label>Modelo STT</Label>
                    <Input value={edit.stt_model ?? ""} onChange={(e) => setEdit({ ...edit, stt_model: e.target.value })} placeholder="whisper-1" />
                  </div>
                  <div>
                    <Label>Modelo translate</Label>
                    <Input value={edit.translate_model ?? ""} onChange={(e) => setEdit({ ...edit, translate_model: e.target.value })} placeholder="gpt-4o-mini" />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label>Modelo live (opcional)</Label>
                    <Input value={edit.live_model ?? ""} onChange={(e) => setEdit({ ...edit, live_model: e.target.value })} placeholder="" />
                  </div>
                  <div>
                    <Label>Capabilities</Label>
                    <div className="flex gap-4 pt-2.5 text-sm text-slate-300">
                      <label className="flex items-center gap-1.5">
                        <input type="checkbox" checked={!!edit.supports_stt} onChange={(e) => setEdit({ ...edit, supports_stt: e.target.checked })} /> STT
                      </label>
                      <label className="flex items-center gap-1.5">
                        <input type="checkbox" checked={!!edit.supports_translate} onChange={(e) => setEdit({ ...edit, supports_translate: e.target.checked })} /> traducción
                      </label>
                    </div>
                  </div>
                </div>
                <div className="mt-1 flex items-center gap-2 pt-1 text-sm">
                  <label className="flex items-center gap-1.5 text-slate-300">
                    <input type="checkbox" checked={!!edit.enabled} onChange={(e) => setEdit({ ...edit, enabled: e.target.checked })} /> Habilitado
                  </label>
                </div>

                <div className="mt-4 flex gap-2">
                  <Button variant="primary" onClick={save}><Plus /> Guardar</Button>
                  <Button variant="ghost" onClick={() => { setEdit({}); setIsNew(false); }}>Cancelar</Button>
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </main>
    </div>
  );
}