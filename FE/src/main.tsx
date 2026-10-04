import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";
import { initThemePreference } from "./lib/uiPreferences";
import { SessionProvider } from "./state/session";
import { AuthProvider } from "./auth/AuthProvider";

initThemePreference();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <SessionProvider>
          <App />
        </SessionProvider>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
