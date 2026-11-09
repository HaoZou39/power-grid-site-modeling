import { useEffect, useState } from "react";
import { AccountAdmin } from "./account_admin";
import { clearCsrfToken, currentAccount, getHealth, logoutAccount, resetAccountStorage, setCsrfToken } from "./api";
import type { Account } from "./api";
import { LoginScreen } from "./login";
import { MapWorkspace } from "./map/map_workspace";

function App() {
  const [health, setHealth] = useState("服务检查中");
  const [account, setAccount] = useState<Account | null>(null);
  const [ready, setReady] = useState(false);
  const [managing, setManaging] = useState(false);

  useEffect(() => {
    getHealth()
      .then((status) => setHealth(`${status.service} ${status.version} · ${status.status}`))
      .catch(() => setHealth("后端连接失败"));
    currentAccount()
      .then((body) => {
        setCsrfToken(body.csrf_token);
        setAccount(body.user);
      })
      .catch(() => setAccount(null))
      .finally(() => setReady(true));
    const expired = () => {
      clearCsrfToken();
      resetAccountStorage(window.sessionStorage, "expired", null);
      setAccount(null);
      setManaging(false);
    };
    window.addEventListener("session-expired", expired);
    return () => window.removeEventListener("session-expired", expired);
  }, []);

  useEffect(() => {
    const previous = window.sessionStorage.getItem("active-account");
    if (account === null) {
      if (previous) resetAccountStorage(window.sessionStorage, previous, null);
      return;
    }
    if (previous !== account.id) resetAccountStorage(window.sessionStorage, previous, account.id);
    window.sessionStorage.setItem("active-account", account.id);
  }, [account]);

  if (!ready) return <main className="login-screen"><p>正在确认登录状态</p></main>;
  if (!account) return <LoginScreen onLoggedIn={setAccount} />;

  return (
    <>
      <MapWorkspace
        key={account.id}
        health={health}
        accountId={account.id}
        accountName={account.username}
        accountRole={account.role}
        onLogout={() => {
          void logoutAccount().finally(() => {
            clearCsrfToken();
            resetAccountStorage(window.sessionStorage, account.id, null);
            setAccount(null);
            setManaging(false);
          });
        }}
        onManageAccounts={() => setManaging(true)}
      />
      {managing && account.role === "admin" && <AccountAdmin onClose={() => setManaging(false)} />}
    </>
  );
}

export default App;
