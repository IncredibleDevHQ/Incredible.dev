import React, { useContext } from "react";
import { WebviewContext } from "./WebviewContext";
import { CollapsedConversationView } from "../components/CollapsedConversationView";
import { ExpandedConversationView } from "../components/ExpandedConversationView";
import {
  createNewConversation,
  onClickReply,
  clickCollapsedConversation,
} from "../controller/ChatController";

const StartChatButton: React.FC<{ onClick: () => void }> = ({ onClick }) => (
  <div className="start-chat">
    <button onClick={onClick}>Start new chat</button>
  </div>
);

export const ChatConversation: React.FC = () => {
  const { panelState, setPanelState } = useContext(WebviewContext);

  // TODO: Remove this once all the operations are handled
  const sendMessage = async (messageData: any) => {
    console.log("sendMessage", messageData);
  };

  const handleCreateNewConversation = () => {
    setPanelState((prevState) => createNewConversation(prevState));
  };

  const handleOnClickReply = (conversationId: string, message: string) => {
    setPanelState((prevState) =>
      onClickReply(prevState, conversationId, message)
    );
  };

  const handleclickCollapsedConversation = (conversationId: string) => {
    setPanelState((prevState) =>
      clickCollapsedConversation(prevState, conversationId)
    );
  };

  if (!panelState) {
    return <StartChatButton onClick={handleCreateNewConversation} />;
  }

  if (panelState.type !== "chat") {
    throw new Error(
      `Invalid panel state '${panelState.type}' (expected 'chat')`
    );
  }

  if (!panelState.hasOpenAIApiKey) {
    return (
      <div className="enter-api-key">
        <button onClick={() => sendMessage({ type: "enterOpenAIApiKey" })}>
          Enter your OpenAI API key
        </button>
        <p>
          Rubberduck uses the OpenAI API and requires an API key to work. You
          can get an API key from{" "}
          <a href="https://platform.openai.com/account/api-keys">
            platform.openai.com/account/api-keys
          </a>
        </p>
      </div>
    );
  }

  if (panelState.conversations.length === 0) {
    return <StartChatButton onClick={handleCreateNewConversation} />;
  }

  return (
    <div>
      <StartChatButton onClick={handleCreateNewConversation} />
      {panelState.conversations.map((conversation) =>
        panelState.selectedConversationId === conversation.id ? (
          <ExpandedConversationView
            key={conversation.id}
            conversation={conversation}
            onSendMessage={(message: string) =>
              handleOnClickReply(conversation.id, message)
            }
            onClickRetry={() =>
              sendMessage({
                type: "retry",
                data: { id: conversation.id },
              })
            }
            onClickDismissError={() =>
              sendMessage({
                type: "dismissError",
                data: { id: conversation.id },
              })
            }
            onClickDelete={() =>
              sendMessage({
                type: "deleteConversation",
                data: { id: conversation.id },
              })
            }
            onClickExport={() => {
              sendMessage({
                type: "exportConversation",
                data: { id: conversation.id },
              });
            }}
            onClickInsertPrompt={
              panelState.surfacePromptForOpenAIPlus
                ? () => {
                    sendMessage({
                      type: "insertPromptIntoEditor",
                      data: { id: conversation.id },
                    });
                  }
                : undefined
            }
          />
        ) : (
          <CollapsedConversationView
            key={conversation.id}
            conversation={conversation}
            onClick={() => handleclickCollapsedConversation(conversation.id)}
          />
        )
      )}
    </div>
  );
};
