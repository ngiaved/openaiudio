/* Captura de audio en el navegador → PCM16 16 kHz mono → bytes para el backend.

   Fuentes soportadas:
     - micrófono (device elegido o default)
     - audio del sistema (tab/capture de pantalla, vía getDisplayMedia)
     - archivo local (wav/mp3/flac…, vía <audio> + MediaElementSource)

   (Resample lineal a 16 kHz desde la tasa nativa del AudioContext.) */

import { TARGET_RATE } from "./api";

export interface CaptureHandle {
  sampleRate: number;
  setHandler: (h: (i16: Int16Array, rms: number) => void) => void;
  close: () => void;
}

export interface AudioDevice {
  id: string;
  label: string;
}

export async function listAudioDevices(): Promise<AudioDevice[]> {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices
      .filter((d) => d.kind === "audioinput")
      .map((d) => ({ id: d.deviceId, label: d.label || `Micrófono ${d.deviceId.slice(0, 4)}…` }));
  } catch {
    return [];
  }
}

export async function captureMic(deviceId?: string): Promise<CaptureHandle> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: deviceId
      ? { deviceId: { exact: deviceId }, channelCount: 1, echoCancellation: false, noiseSuppression: true }
      : { channelCount: 1, echoCancellation: false, noiseSuppression: true },
  });
  return captureStream(stream);
}

export async function captureSystemAudio(): Promise<CaptureHandle> {
  const stream = await navigator.mediaDevices.getDisplayMedia({
    audio: true,
    video: true,
  });
  stream.getVideoTracks().forEach((t) => t.stop()); // necesitamos solo el audio
  return captureStream(stream);
}

export function captureFile(file: File): Promise<CaptureHandle> {
  const actx = new (window.AudioContext || (window as any).webkitAudioContext)();
  const url = URL.createObjectURL(file);
  const audio = document.createElement("audio");
  audio.src = url;
  audio.loop = true;
  audio.autoplay = true;
  const handle = wireProcessor(actx, actx.createMediaElementSource(audio), () => {
    URL.revokeObjectURL(url);
  });
  audio.play().catch(() => {});
  return new Promise((resolve) => {
    audio.addEventListener("canplay", () => resolve(handle), { once: true });
  });
}

function captureStream(stream: MediaStream): Promise<CaptureHandle> {
  const actx = new (window.AudioContext || (window as any).webkitAudioContext)();
  const source = actx.createMediaStreamSource(stream);
  const stopter = () => stream.getTracks().forEach((t) => t.stop());
  return Promise.resolve(wireProcessor(actx, source, stopter));
}

function wireProcessor(actx: AudioContext, source: AudioNode, onClose: () => void): CaptureHandle {
  const processor = actx.createScriptProcessor(4096, 1, 1);
  let handler: ((i16: Int16Array, rms: number) => void) | null = null;

  processor.onaudioprocess = (e: AudioProcessingEvent) => {
    if (!handler) return;
    const ch = e.inputBuffer.getChannelData(0);
    const i16 = new Int16Array(ch.length);
    let acc = 0;
    for (let i = 0; i < ch.length; i++) {
      const s = Math.max(-1, Math.min(1, ch[i]));
      i16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      acc += s * s;
    }
    const rms = Math.sqrt(acc / ch.length);
    handler(i16, rms);
  };

  source.connect(processor);
  processor.connect(actx.destination);

  let closed = false;
  return {
    sampleRate: actx.sampleRate,
    setHandler: (h) => (handler = h),
    close: () => {
      if (closed) return;
      closed = true;
      processor.disconnect();
      source.disconnect();
      onClose();
      actx.close().catch(() => {});
    },
  };
}

export function resampleTo16k(i16: Int16Array, fromRate: number): Int16Array {
  if (fromRate === TARGET_RATE) return i16;
  const n = Math.max(1, Math.round((i16.length * TARGET_RATE) / fromRate));
  const out = new Int16Array(n);
  for (let i = 0; i < n; i++) {
    const pos = (i * (i16.length - 1)) / Math.max(1, n - 1);
    const i0 = Math.floor(pos);
    const i1 = Math.min(i0 + 1, i16.length - 1);
    out[i] = Math.round(i16[i0] * (1 - (pos - i0)) + i16[i1] * (pos - i0));
  }
  return out;
}