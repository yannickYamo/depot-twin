import { defineConfig } from "vite";

// Relative base so the built site works from any path, including a project page.
export default defineConfig({ base: "./", build: { outDir: "dist" } });
