import { useEffect, useState } from "react";
import { ApiRequestError, createAccount, listAccounts, patchAccount } from "./api";
import type { Account } from "./api";

export function AccountAdmin({ onClose }: { onClose: () => void }) {
  const [users, setUsers] = useState<Account[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  function reload() {
    return listAccounts().then((body) => setUsers(body.users)).catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : "无法读取账户");
    });
  }

  useEffect(() => { void reload(); }, []);

  return (
    <section className="account-admin" role="dialog" aria-modal="true" aria-label="账户">
      <header>
        <strong>账户</strong>
        <button type="button" onClick={onClose}>关闭</button>
      </header>
      {error && <p role="alert">{error}</p>}
      <ul>
        {users.map((user) => (
          <li key={user.id}>
            <span>{user.username}</span>
            <small>{user.role === "admin" ? "管理员" : "用户"}{user.disabled_at ? " · 已停用" : ""}</small>
            {!user.disabled_at && (
              <button type="button" onClick={() => { void patchAccount(user.id, { disabled: true }).then(reload).catch((reason: unknown) => setError(reason instanceof ApiRequestError ? reason.message : "停用失败")); }}>
                停用
              </button>
            )}
          </li>
        ))}
      </ul>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          const name = username.trim();
          if (!/^[A-Za-z0-9_-]{1,32}$/.test(name)) {
            setError("用户名只能包含字母、数字、下划线和短横线");
            return;
          }
          if (password.length < 8) {
            setError("密码至少 8 位");
            return;
          }
          setError("");
          void createAccount({ username: name, password, role: "user" })
            .then(() => { setUsername(""); setPassword(""); return reload(); })
            .catch((reason: unknown) => setError(reason instanceof ApiRequestError ? reason.message : "创建失败"));
        }}
      >
        <label>
          用户名
          <input aria-label="新用户名" value={username} autoComplete="off" onChange={(event) => setUsername(event.target.value)} />
        </label>
        <label>
          密码
          <input aria-label="新密码" type="password" value={password} autoComplete="new-password" onChange={(event) => setPassword(event.target.value)} />
        </label>
        <p className="account-hint">密码至少 8 位。新建账户是普通用户。</p>
        <button type="submit">创建用户</button>
      </form>
    </section>
  );
}
