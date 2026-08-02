import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// 构建产物输出到项目根 static/，由 FastAPI StaticFiles 托管（部署中立）。
// emptyOutDir: true 清旧构建产物（legacy 已挪走，不误删源）。
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  build: { outDir: "../static", emptyOutDir: true, assetsDir: "assets" },
});
