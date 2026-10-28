import { defineConfig } from "vite";
// Tauri 要求相对路径 + 固定端口；浏览器模式由侧车 --ui dist 直接托管
export default defineConfig({ base: "./", server: { port: 1420, strictPort: true }, build: { target: "es2021", outDir: "dist" } });
