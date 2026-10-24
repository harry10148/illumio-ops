import { useCallback, useEffect, useState } from "react";
import { BrowserRouter } from "react-router-dom";

import { AUTH_REQUIRED_EVENT, call } from "./api/client";
import type { Me } from "./api/generated";
import { LangContext, type Lang, initialLang, loadDictionary, t } from "./i18n";
import { Login } from "./pages/Login";
import { PasswordChange } from "./pages/PasswordChange";
import { Shell } from "./shell/Shell";

type Auth = { state: "checking" } | { state: "signed-out" } | { state: "signed-in"; me: Me };

export function App() {
  const [lang] = useState<Lang>(initialLang);
  const [ready, setReady] = useState(false);
  const [auth, setAuth] = useState<Auth>({ state: "checking" });

  const refreshMe = useCallback(async () => {
    const env = await call("auth.me");
    setAuth(env.ok && env.data ? { state: "signed-in", me: env.data } : { state: "signed-out" });
  }, []);

  useEffect(() => {
    void loadDictionary(lang).then(() => setReady(true));
  }, [lang]);

  useEffect(() => {
    void refreshMe();
    const onAuthRequired = () => setAuth({ state: "signed-out" });
    window.addEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
  }, [refreshMe]);

  if (!ready || auth.state === "checking") {
    return <div className="center-page muted">{ready ? t("loading") : "…"}</div>;
  }

  let body;
  if (auth.state === "signed-out") {
    body = <Login onSignedIn={() => void refreshMe()} />;
  } else if (auth.me.must_change_password) {
    body = (
      <div className="center-page">
        <PasswordChange requireOld={false} onChanged={() => void refreshMe()} />
      </div>
    );
  } else {
    body = (
      <BrowserRouter>
        <Shell username={auth.me.username} onSignedOut={() => setAuth({ state: "signed-out" })} />
      </BrowserRouter>
    );
  }
  return <LangContext.Provider value={lang}>{body}</LangContext.Provider>;
}
