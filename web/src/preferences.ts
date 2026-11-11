// Device preferences contain only these enumerated display options.
export const choices = {
  start: [{value: "channel", label: "First channel"}, {value: "needs", label: "Needs you"}],
  clock: [{value: "system", label: "System default"}, {value: "12", label: "12-hour"}, {value: "24", label: "24-hour"}],
};
export type Preference = keyof typeof choices;

export function preference(key: Preference): string {
  try {
    const saved = localStorage.getItem("house:" + key);
    return choices[key].find(option => option.value === saved)?.value ?? choices[key][0].value;
  } catch {
    return choices[key][0].value;
  }
}
