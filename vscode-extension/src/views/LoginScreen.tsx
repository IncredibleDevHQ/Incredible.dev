import React, { useState, useContext } from "react";
import { WebviewContext } from "./WebviewContext";
import { PanelState } from "../schema/PanelState";

export const LoginScreen: React.FC = () => {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const { setPanelState } = useContext(WebviewContext);

  const handleLogin = () => {
    // Perform login logic
    setPanelState((prevState: PanelState) => ({
      ...prevState,
      login: { isLoggedIn: true },
    }));

    // Navigate to the IngestionScreen
    setPanelState((prevState: PanelState) => ({
      ...prevState,
      settings: { view: "ingestion" },
    }));
  };

  return (
    <div className="login-screen">
      <div className="login-component">
        <input
          type="text"
          placeholder="Username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button onClick={handleLogin}>Login</button>
      </div>
    </div>
  );
};
