import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The engine serves the API on 8765 (`uv run python -m design_agent.surfaces.web`); in
// development Vite serves the app and passes /api through, the event stream included.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5178,
    proxy: { "/api": { target: "http://127.0.0.1:8765", changeOrigin: false } },
  },
});
