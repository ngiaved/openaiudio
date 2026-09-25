/* Captura del micrófono en el navegador → PCM16 16 kHz mono → bytes para el backend.
   (Resample lineal a 16 kHz desde la tasa nativa del AudioContext.) */

import { TARGET_RATE } from "./api";

export interface CaptureHandle {
  sampleRate: number;
  setHandler: (h: (i16: Int16Array, rms: number) => void) => void;
  close: () => void;
}

export async function captureMic(): Promise<CaptureHandle> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: false, noiseSuppression: true },
  });
  const actx = new (window.AudioContext || (window as any).webkitAudioContext)();
  const source = actx.createMediaStreamSource(stream);
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

  return {
    sampleRate: actx.sampleRate,
    setHandler: (h) => (handler = h),
    close: () => {
      processor.disconnect();
      source.disconnect();
      stream.getTracks().forEach((t) => t.stop());
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