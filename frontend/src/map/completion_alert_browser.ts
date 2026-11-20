import { CompletionAlert } from "./completion_alert";
import type { AlertHost, AlertPermission } from "./completion_alert";

function browserHost(): AlertHost {
  let audio: AudioContext | null = null;
  return {
    get secure() { return window.isSecureContext; },
    get permission(): AlertPermission {
      if (!window.isSecureContext || typeof Notification === "undefined") return "unsupported";
      return Notification.permission;
    },
    requestPermission() { return Notification.requestPermission(); },
    notify(title, body) {
      const item = new Notification(title, { body, lang: "zh-CN" });
      item.onclick = () => { window.focus(); item.close(); };
    },
    title: () => document.title,
    setTitle(value) { document.title = value; },
    arm() {
      const Ctx = window.AudioContext;
      if (!Ctx) return;
      audio ??= new Ctx();
      void audio.resume().catch(() => {});
    },
    beep() {
      if (!audio || audio.state !== "running") return;
      const start = audio.currentTime;
      const gain = audio.createGain();
      gain.connect(audio.destination);
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.05, start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.42);
      for (const [freq, at] of [[880, 0], [1175, 0.22]] as const) {
        const osc = audio.createOscillator();
        osc.frequency.value = freq;
        osc.connect(gain);
        osc.start(start + at);
        osc.stop(start + at + 0.18);
      }
    },
    schedule: (fn, ms) => window.setTimeout(fn, ms),
    cancel(id) { window.clearTimeout(id); },
  };
}

export const completionAlert = new CompletionAlert(browserHost());
