import { useEffect, useState } from "react";
import { getHealth } from "./api";
import { MapWorkspace } from "./map/map_workspace";

/** The open screen is the decision map. Older config and result pages stay in the repo and are not mounted here. */
function App() {
  const [health, setHealth] = useState("服务检查中");

  useEffect(() => {
    getHealth()
      .then((status) => setHealth(`${status.service} ${status.version} · ${status.status}`))
      .catch(() => setHealth("后端连接失败"));
  }, []);

  return <MapWorkspace health={health} />;
}

export default App;
