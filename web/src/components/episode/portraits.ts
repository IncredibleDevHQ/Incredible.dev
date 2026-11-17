export const portraits = ["Mira", "Kai", "Ellis", "June"] as const;
export const portraitUrl = (name = "mira") => `/api/presenter-portraits/${encodeURIComponent(name.toLowerCase())}`;
