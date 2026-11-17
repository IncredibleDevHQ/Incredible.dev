export const portraits = ["Mira", "June"] as const;
export const portraitUrl = (name = "mira") => `/api/presenter-portraits/${encodeURIComponent(name.toLowerCase())}`;
