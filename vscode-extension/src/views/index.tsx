import React, { ComponentType } from "react";
import { createRoot } from "react-dom/client";
import { WebviewApi, WithWebviewContext } from "./WebviewContext";
import { ExampleViewA } from "./ExampleViewA";
import { ExampleViewB } from "./ExampleViewB";
import { ChatConversation } from "./ChatConversation";
import { PanelState } from "../schema/PanelState";
import { initalPanelState } from "../dummy";

export const Views = {
  exampleViewA: ExampleViewA,
  exampleViewB: ExampleViewB,
  chatConversation: ChatConversation,
} as const;

export type ViewKey = keyof typeof Views;

interface ViewProps {
  exampleViewA?: {};
  exampleViewB?: {};
  chatConversation?: { panelState: PanelState };
}

const initialProps: ViewProps = {
  chatConversation: {
    panelState: initalPanelState,
  },
};

export function render<V extends ViewKey>(
  key: V,
  vscodeApi: WebviewApi,
  publicPath: string,
  rootId = "root"
) {
  const container = document.getElementById(rootId);
  if (!container) {
    throw new Error(`Element with id of ${rootId} not found.`);
  }

  __webpack_public_path__ = publicPath;

  const Component: ComponentType<any> = Views[key];
  const props = initialProps[key] || {};

  const root = createRoot(container!);
  root.render(
    <WithWebviewContext vscodeApi={vscodeApi}>
      <Component {...props} />
    </WithWebviewContext>
  );
}
