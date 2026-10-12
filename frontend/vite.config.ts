import { Agent } from "node:http";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5176,
    strictPort: true,
    allowedHosts: true,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET ?? "http://127.0.0.1:8010",
        // Node 20 复用空闲连接时会撞上 uvicorn 5 s keep-alive 关闭，偶发 502。
        agent: new Agent({ keepAlive: false }),
      },
    },
  },
});
