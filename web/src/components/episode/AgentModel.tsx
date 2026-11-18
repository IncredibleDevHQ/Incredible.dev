// The model an agent runs on and how hard it thinks, side by side. The first of each is the
// agent's own default, named where the agent says what it is. A new model starts on its default
// effort, since the levels are each model's own.
import type { ModelOption } from "../../api";
import { Select } from "../Select";
import { effortName, optionLabel } from "./models";

export type ModelPick = { model: string; effort: string };

// Whether an agent offers anything to pick: more than one model, or a level of effort.
export const offersPicks = (models: ModelOption[] | undefined) => (models?.length ?? 0) > 1 || (models ?? []).some((m) => m.efforts.length > 0);

export function AgentModel({ models, pick, disabled, onChange }: { models: ModelOption[]; pick: ModelPick; disabled?: boolean; onChange: (pick: ModelPick) => void }) {
  const row = models.find((m) => m.id === pick.model) ?? models[0];
  const efforts = row?.efforts ?? [];
  const usual = !efforts.length ? "Agent's default" : row?.default_effort ? `Default · ${effortName(row.default_effort)}` : "Default";
  return (
    <div className="ep-agent-model">
      <Select
        size="sm"
        label="Model"
        value={row?.id ?? ""}
        disabled={disabled || models.length <= 1}
        options={models.map((m) => ({ value: m.id, label: optionLabel(m) }))}
        onChange={(model) => onChange({ model, effort: "" })}
      />
      <Select
        size="sm"
        label="Effort"
        value={efforts.includes(pick.effort) ? pick.effort : ""}
        disabled={disabled || !efforts.length}
        options={[{ value: "", label: usual }, ...efforts.map((e) => ({ value: e, label: effortName(e) }))]}
        onChange={(effort) => onChange({ model: row?.id ?? "", effort })}
      />
    </div>
  );
}
