import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

async function start() {
  if (import.meta.env.VITE_STATIC_DEMO === "true") {
    const { installDemoApi } = await import("./web-demo");
    installDemoApi();
  }
  createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
}
void start();
