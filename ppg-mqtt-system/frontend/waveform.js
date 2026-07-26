const WAVEFORM_SMOOTH_WINDOW = 5;
const WAVEFORM_BASELINE_WINDOW = 40;
const WAVEFORM_AMPLITUDE = 200;

function movingAverageSame(values, windowSize) {
  const left = Math.floor(windowSize / 2);
  const right = windowSize - left - 1;

  return values.map((_value, index) => {
    let sum = 0;
    const start = Math.max(0, index - left);
    const end = Math.min(values.length - 1, index + right);
    for (let sample = start; sample <= end; sample += 1) sum += values[sample];
    return sum / windowSize;
  });
}

// Sama dengan pipeline AnimationPlot.animate() pada aplikasi desktop:
// smoothing 5 sampel, baseline 40 sampel, lalu normalisasi ke ±200.
function normalizeWaveform(samples) {
  const data = samples.map(Number).filter(Number.isFinite);
  if (data.length === 0) return [];

  const smooth =
    data.length >= WAVEFORM_SMOOTH_WINDOW
      ? movingAverageSame(data, WAVEFORM_SMOOTH_WINDOW)
      : data.slice();

  let baseline;
  if (smooth.length >= WAVEFORM_BASELINE_WINDOW) {
    baseline = movingAverageSame(smooth, WAVEFORM_BASELINE_WINDOW);
  } else {
    const mean = smooth.reduce((sum, value) => sum + value, 0) / smooth.length;
    baseline = new Array(smooth.length).fill(mean);
  }

  const signal = smooth.map((value, index) => value - baseline[index]);
  const maxAbs = signal.reduce((peak, value) => Math.max(peak, Math.abs(value)), 0) || 1;
  return signal.map((value) => (value / maxAbs) * WAVEFORM_AMPLITUDE);
}

if (typeof module !== "undefined") module.exports = { normalizeWaveform };
