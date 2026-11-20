// Decode the actual recording, including browser WebM files without duration metadata.
export async function prepareVoiceTest(file: File) {
  const rate = 16000;
  const context = new OfflineAudioContext(1, 1, rate);
  const audio = await context.decodeAudioData(await file.arrayBuffer());
  if (audio.duration > 300 || !audio.length) throw new Error("Choose a recording of up to five minutes.");
  const output = new OfflineAudioContext(1, audio.length, rate);
  const source = output.createBufferSource();
  source.buffer = audio;
  source.connect(output.destination);
  source.start();
  const mono = (await output.startRendering()).getChannelData(0);
  const buffer = new ArrayBuffer(44 + mono.length * 2);
  const header = new DataView(buffer);
  const tag = (offset: number, value: string) => new Uint8Array(buffer, offset, value.length).set(new TextEncoder().encode(value));
  tag(0, "RIFF");
  header.setUint32(4, buffer.byteLength - 8, true);
  tag(8, "WAVEfmt ");
  header.setUint32(16, 16, true);
  header.setUint16(20, 1, true);
  header.setUint16(22, 1, true);
  header.setUint32(24, rate, true);
  header.setUint32(28, rate * 2, true);
  header.setUint16(32, 2, true);
  header.setUint16(34, 16, true);
  tag(36, "data");
  header.setUint32(40, mono.length * 2, true);
  for (let i = 0; i < mono.length; i++) {
    header.setInt16(44 + i * 2, Math.round(Math.max(-1, Math.min(1, mono[i])) * 32767), true);
  }
  return new File([buffer], "recording.wav", {type: "audio/wav"});
}
