import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./pages/system/PceConnection";
import "./pages/system/Jobs";
import "./styles/tokens.css";
import "./styles/base.css";

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
