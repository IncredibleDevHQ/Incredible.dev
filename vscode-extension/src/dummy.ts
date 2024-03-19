import { PanelState } from "./schema/PanelState";

export const initalPanelState: PanelState = {
  chat: {
    conversations: [
      {
        id: "conv1",
        header: {
          title: "Conversation Title",
          isTitleMessage: false,
          codicon: "magnet",
        },
        content: {
          type: "messageExchange",
          messages: [
            {
              author: "bot",
              content: "Please tell me more about your issue. How about it.",
            },
            {
              author: "user",
              content: "Hello, how can I help?",
            },
            {
              author: "bot",
              content: "Please tell me more about your issue.",
            },
          ],
          state: {
            type: "userCanReply",
            responsePlaceholder: "Type your response...",
          },
        },
        createdAt: Date.now() - 1002,
      },
      {
        id: "conv2",
        header: {
          title: "Instruction Refinement",
          isTitleMessage: true,
          codicon: "table",
        },
        content: {
          type: "messageExchange",
          messages: [
            {
              author: "user",
              content: "Hello, how can I help?",
            },
            {
              author: "bot",
              content: "Please tell me more about your issue.",
            },
          ],
          state: {
            type: "userCanReply",
            responsePlaceholder: "Type your response...",
          },
        },
        createdAt: Date.now() - 1000,
      },
    ],
    selectedConversationId: "conv1",
    hasOpenAIApiKey: true,
    surfacePromptForOpenAIPlus: false,
    error: {
      title: "Network Error",
      message:
        "Unable to connect to the server. Please check your internet connection and try again.",
    },
  },
};
