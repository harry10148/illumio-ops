import { useCallback, useEffect, useState } from "react";
import { BrowserRouter } from "react-router-dom";

import { AUTH_REQUIRED_EVENT, call } from "./api/client";
import type { Me } from "./api/generated";
import { LangContext, type Lang, initialLang, loadDictionary, rememberLang, t } from "./i18n";
import { Login } from "./pages/Login";
import { PasswordChange } from "./pages/PasswordChange";
import { ME_CHANGED_EVENT, Shell } from "./shell/Shell";

type Auth = { state: "checking" } | { state: "signed-out" } | { state: "signed-in"; me: Me };

export function App() {
  const [lang, setLang] = useState<Lang>(initialLang);
  const [dictVersion, setDictVersion] = useState(0);
  const [auth, setAuth] = useState<Auth>({ state: "checking" });

  const refreshMe = useCallback(async () => {
    const env = await call("auth.me");
    if (env.ok && env.data) {
      setAuth({ state: "signed-in", me: env.data });
      setLang(env.data.language); // the server-side display setting wins once signed in
    } else {
      setAuth({ state: "signed-out" });
    }
  }, []);

  useEffect(() => {
    void loadDictionary(lang).then(() => {
      rememberLang(lang);
      setDictVersion((v) => v + 1);
    });
  }, [lang]);

  useEffect(() => {
    void refreshMe();
    const onAuthRequired = () => setAuth({ state: "signed-out" });
    const onMeChanged = () => void refreshMe();
    window.addEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
    window.addEventListener(ME_CHANGED_EVENT, onMeChanged);
    return () => {
      window.removeEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
      window.removeEventListener(ME_CHANGED_EVENT, onMeChanged);
    };
  }, [refreshMe]);

  if (dictVersion === 0 || auth.state === "checking") {
    return <div className="center-page muted">{dictVersion ? t("loading") : "…"}</div>;
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
        {/* re-mounted on a language change so every label re-renders */}
        <Shell key={dictVersion} me={auth.me} onSignedOut={() => setAuth({ state: "signed-out" })} />
      </BrowserRouter>
    );
  }
  return <LangContext.Provider value={lang}>{body}</LangContext.Provider>;
}
