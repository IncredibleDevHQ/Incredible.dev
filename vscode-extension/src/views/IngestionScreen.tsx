import React, { useState, useContext, useEffect } from "react";
import { WebviewContext } from "./WebviewContext";
import { startIngestionProcess } from "../controller/IngestionController";
import { PanelState } from "../schema/PanelState";

export const IngestionScreen: React.FC = () => {
  const { panelState, setPanelState } = useContext(WebviewContext);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (panelState?.ingestion?.status === "inProgress") {
      setIsLoading(true);
    } else {
      setIsLoading(false);
    }
  }, [panelState?.ingestion?.status]);

  const handleStartIngestion = () => {
    setIsLoading(true);
    setPanelState((prevState: PanelState) => ({
      ...prevState,
      ingestion: { indexingProgress: 0, status: "inProgress" },
    }));

    startIngestionProcess(
      (progress) => {
        setPanelState((prevState: PanelState) => ({
          ...prevState,
          ingestion: {
            ...(prevState.ingestion ?? {
              status: "notStarted",
              indexingProgress: 0,
            }),
            indexingProgress: progress,
          },
        }));
      },
      () => {
        setPanelState((prevState) => ({
          ...prevState,
          ingestion: { indexingProgress: 100, status: "completed" },
          settings: { view: "chat" },
        }));
      }
    );
  };

  return (
    <div className="ingestion-screen">
      <div className="ingestion-component">
        {!isLoading && (
          <div className="start-ingestion">
            <button onClick={handleStartIngestion} disabled={isLoading}>
              Start Ingestion
            </button>
          </div>
        )}
        {isLoading && (
          <div className="ingestion-progress">
            <div>Progress: {panelState?.ingestion?.indexingProgress}%</div>
            <div>Status: {panelState?.ingestion?.status}</div>
          </div>
        )}
      </div>
    </div>
  );
};
