/* Convert the actual device sample rate into mono, signed PCM16 at 16 kHz.
   Weighted interval averaging filters downsampling and carries fractional frames
   across audio blocks. No microphone samples are written to the output. */
class BlueprintPCM extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.weight = 0;
    this.sum = 0;
    this.samples = [];
    this.stopped = false;
    this.port.onmessage = ({data}) => {
      if (data.type !== "flush") return;
      this.stopped = true;
      if (this.weight) this.samples.push(this.sum / this.weight);
      this.emit();
      this.port.postMessage({type: "flushed"});
    };
  }
  emit() {
    if (!this.samples.length) return;
    const buffer = new ArrayBuffer(this.samples.length * 2);
    const view = new DataView(buffer);
    this.samples.forEach((value, i) => {
      const clamped = Math.max(-1, Math.min(1, value));
      view.setInt16(i * 2, Math.round(clamped * (clamped < 0 ? 32768 : 32767)), true);
    });
    this.samples = [];
    this.port.postMessage({type: "audio", buffer}, [buffer]);
  }
  process(inputs) {
    if (this.stopped) return true;
    const channels = inputs[0];
    if (!channels?.length) return true;
    for (let i = 0; i < channels[0].length; i++) {
      let value = 0;
      for (const channel of channels) value += channel[i] || 0;
      value /= channels.length;
      let remaining = 1;
      while (remaining > 1e-9) {
        const portion = Math.min(remaining, this.ratio - this.weight);
        this.sum += value * portion;
        this.weight += portion;
        remaining -= portion;
        if (this.weight >= this.ratio - 1e-9) {
          this.samples.push(this.sum / this.weight);
          this.weight = 0; this.sum = 0;
          if (this.samples.length >= 1600) this.emit();
        }
      }
    }
    return true;
  }
}
registerProcessor("blueprint-pcm", BlueprintPCM);
