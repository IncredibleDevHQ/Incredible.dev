import React, { useContext } from "react";
import { WebviewContext } from "./WebviewContext";
import { LoginScreen } from "./LoginScreen";
import { IngestionScreen } from "./IngestionScreen";
import { ChatConversation } from "./ChatConversation";

export const AppRouter: React.FC = () => {
  const { panelState } = useContext(WebviewContext);

  const renderView = () => {
    switch (panelState.settings.view) {
      case "login":
        return <LoginScreen />;
      case "ingestion":
        return <IngestionScreen />;
      case "chat":
        return <ChatConversation />;
      default:
        return null;
    }
  };

  return <>{renderView()}</>;
};
