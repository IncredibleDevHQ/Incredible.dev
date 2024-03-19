import { v4 } from "uuid";
import { PanelState } from "../schema/PanelState";
import {
  Conversation,
  Message,
  MessageExchangeContent,
} from "../schema/Conversation";

export const createNewConversation = (prevState: PanelState): PanelState => {
  if (!prevState || prevState.type !== "chat") {
    console.error("Invalid previous state structure");
    return prevState;
  }

  const conversationId = v4();
  const newConversation: Conversation = {
    id: conversationId,
    header: {
      title: `Conversation: ${conversationId}`,
      isTitleMessage: true,
      codicon: "wand",
    },
    content: {
      type: "messageExchange",
      messages: [],
      state: {
        type: "userCanReply",
        responsePlaceholder: "Type your response...",
      },
    },
    createdAt: Date.now(),
  };

  const updatedConversations = [
    ...prevState.conversations,
    newConversation,
  ].sort((a, b) => b.createdAt - a.createdAt);

  return {
    ...prevState,
    conversations: updatedConversations,
    selectedConversationId: conversationId,
  };
};

export const onClickReply = (
  prevState: PanelState,
  conversationId: string,
  message: string
): PanelState => {
  if (!prevState || prevState.type !== "chat") {
    console.error("Invalid previous state structure or not in 'chat' mode");
    return prevState;
  }

  const updatedConversations = prevState.conversations.map(
    (conversation: Conversation) => {
      if (
        conversation.id === conversationId &&
        conversation.content.type === "messageExchange"
      ) {
        const userMessage: Message = { author: "user", content: message };
        const updatedMessages: Message[] = [
          ...conversation.content.messages,
          userMessage,
          { author: "bot", content: "I got it." },
        ];

        const updatedContent: MessageExchangeContent = {
          ...conversation.content,
          messages: updatedMessages,
          state: {
            ...conversation.content.state,
            type: "userCanReply",
          },
        };
        return { ...conversation, content: updatedContent };
      }
      return conversation;
    }
  );
  return {
    ...prevState,
    conversations: updatedConversations.sort(
      (a, b) => b.createdAt - a.createdAt
    ),
  };
};

export const clickCollapsedConversation = (
  prevState: PanelState,
  conversationId: string
): PanelState => {
  if (!prevState || prevState.type !== "chat") {
    console.error("Invalid previous state structure");
    return prevState;
  }

  return {
    ...prevState,
    selectedConversationId: conversationId,
  };
};
