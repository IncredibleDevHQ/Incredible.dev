import zod from "zod";
import { conversationSchema } from "./Conversation";
import { errorSchema } from "./Error";

export const panelStateSchema = zod.object({
  chat: zod.object({
    conversations: zod.array(conversationSchema),
    selectedConversationId: zod.union([zod.string(), zod.undefined()]),
    hasOpenAIApiKey: zod.boolean(),
    surfacePromptForOpenAIPlus: zod.boolean(),
    error: errorSchema.optional(),
  }).optional(),
  // TODO: Update diff as per the required structure when the time comes.
  diff: zod.object({
    oldCode: zod.string(),
    newCode: zod.string(),
    languageId: zod.string().optional(),
  }).optional(),
  ingestion: zod.object({
    indexingProgress: zod.number(),
    status: zod.enum(["notStarted", "inProgress", "completed", "failed"]),
  }).optional(),
});

export type PanelState = zod.infer<typeof panelStateSchema>;
