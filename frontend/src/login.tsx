import { useState } from "react";
import { ApiRequestError, loginAccount, setCsrfToken } from "./api";
import type { Account } from "./api";

export function LoginScreen({ onLoggedIn }: { onLoggedIn: (account: Account) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <main className="login-screen">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setBusy(true);
          setError("");
          void loginAccount(username.trim(), password)
            .then((body) => {
              setCsrfToken(body.csrf_token);
              onLoggedIn(body.user);
            })
            .catch((reason: unknown) => {
              setError(reason instanceof ApiRequestError ? reason.message : "登录失败");
            })
            .finally(() => setBusy(false));
        }}
      >
        <p className="eyebrow">温州电力设计院</p>
        <h1>登录</h1>
        <label>
          用户名
          <input value={username} autoComplete="username" onChange={(event) => setUsername(event.target.value)} />
        </label>
        <label>
          密码
          <input type="password" value={password} autoComplete="current-password" onChange={(event) => setPassword(event.target.value)} />
        </label>
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={busy || !username.trim() || !password}>登录</button>
      </form>
    </main>
  );
}
