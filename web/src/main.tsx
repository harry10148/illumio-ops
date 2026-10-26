import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./pages/system/PceConnection";
import "./pages/system/Collection";
import "./pages/system/Lateral";
import "./pages/system/Jobs";
import "./pages/system/Logs";
import "./pages/system/Tls";
import "./pages/system/Security";
import "./pages/system/Display";
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
