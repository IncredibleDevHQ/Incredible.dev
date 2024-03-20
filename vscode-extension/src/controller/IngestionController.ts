// TODO: Update this with actual ingestion process once things are in play
export const startIngestionProcess = (
  onUpdateProgress: (progress: number) => void,
  onComplete: () => void
) => {
  simulateIngestionProcess(onUpdateProgress, onComplete);
};

const simulateIngestionProcess = (
  onUpdateProgress: (progress: number) => void,
  onComplete: () => void
) => {
  let progress = 0;
  const interval = 300;
  const increment = 100 / (3000 / interval);

  const intervalId = setInterval(() => {
    progress += increment;
    if (progress >= 100) {
      clearInterval(intervalId);
      onUpdateProgress(100);
      onComplete();
    } else {
      onUpdateProgress(progress);
    }
  }, interval);
};
