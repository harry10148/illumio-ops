import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The build lands inside the Python package so the offline bundle ships it as-is.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../illumio_ops/web/static",
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false,
  },
});
