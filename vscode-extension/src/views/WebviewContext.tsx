import { createContext, useEffect, useState } from "react";
import DeferredPromise from "promise-deferred";
import { v4 as uuid } from "uuid";
import {
  ViewApi,
  ViewApiError,
  ViewApiEvent,
  ViewApiRequest,
  ViewApiResponse,
  ViewEvents,
} from "../viewApi";
import { PanelState } from "../schema/PanelState";
import { initalPanelState } from "../dummy";

export type WebviewContextValue = {
  callApi: CallAPI;
  addListener: AddRemoveListener;
  removeListener: AddRemoveListener;
  panelState: PanelState;
  setPanelState: React.Dispatch<React.SetStateAction<PanelState>>;
};

export type WebviewApi = ReturnType<typeof acquireVsCodeApi>;

type CallAPI = <K extends keyof ViewApi>(
  key: K,
  ...params: Parameters<ViewApi[K]>
) => Promise<ReturnType<ViewApi[K]>>;
type AddRemoveListener = <K extends keyof ViewEvents>(
  key: K,
  cb: (...params: Parameters<ViewEvents[K]>) => void
) => void;

export const webviewContextValue = (
  postMessage: (message: unknown) => void,
  initialPanelState: PanelState
): WebviewContextValue => {
  const [panelState, setPanelState] = useState<PanelState>(initialPanelState);
  const pendingRequests: Record<string, DeferredPromise.Deferred<unknown>> = {};
  const listeners: Record<string, Set<(...args: unknown[]) => void>> = {};

  const onMessage = (e: MessageEvent<Record<string, unknown>>) => {
    if (e.data.type === "response") {
      const data = e.data as ViewApiResponse;
      pendingRequests[data.id].resolve(data.value);
    } else if (e.data.type === "error") {
      const data = e.data as ViewApiError;
      pendingRequests[data.id].reject(new Error(data.value));
    } else if (e.data.type === "event") {
      const data = e.data as ViewApiEvent;
      listeners?.[data.key]?.forEach((cb) => cb(...data.value));
    }
  };

  window.addEventListener("message", onMessage);

  const callApi = <K extends keyof ViewApi>(
    key: K,
    ...params: Parameters<ViewApi[K]>
  ) => {
    const id = uuid();
    const deferred = new DeferredPromise<ReturnType<ViewApi[K]>>();
    const req: ViewApiRequest = { type: "request", id, key, params };
    pendingRequests[id] = deferred;
    postMessage(req);
    return deferred.promise;
  };

  const addListener: AddRemoveListener = (key, cb) => {
    if (!listeners[key]) {
      listeners[key] = new Set();
    }
    listeners[key].add(cb as (...args: unknown[]) => void);
  };

  const removeListener: AddRemoveListener = (key, cb) => {
    if (!listeners[key]) {
      return;
    }
    listeners[key].delete(cb as (...args: unknown[]) => void);
  };

  return { callApi, addListener, removeListener, panelState, setPanelState };
};

export const WebviewContext = createContext<WebviewContextValue>(
  {} as WebviewContextValue
);

export const WithWebviewContext = ({
  vscodeApi,
  children,
}: {
  vscodeApi: WebviewApi;
  children: React.ReactNode;
}) => {
  const [panelState, setPanelState] = useState<PanelState>(initalPanelState);

  useEffect(() => {
    console.log("panelState updated:", panelState);
  }, [panelState]);

  const value = webviewContextValue(vscodeApi.postMessage, panelState);
  value.panelState = panelState;
  value.setPanelState = setPanelState;

  return (
    <WebviewContext.Provider value={value}>{children}</WebviewContext.Provider>
  );
};
