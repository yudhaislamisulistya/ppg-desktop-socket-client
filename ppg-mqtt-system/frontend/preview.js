const PREVIEW_MFCC = [-145.2638, 43.1256, 18.7742, -12.9531, 8.6247, -6.3184,
  4.2258, -3.1472, 2.5361, -1.8449, 1.2637, -0.9254, 0.6182];

// Sinyal deterministik tanpa koneksi MQTT, identitas pasien, atau penyimpanan.
function previewSamples(offset, count) {
  return Array.from({ length: count }, (_, index) => {
    const sample = offset + index;
    const phase = (sample % 84) / 84;
    const pulse = Math.exp(-(((phase - 0.24) / 0.065) ** 2));
    const reflection = 0.32 * Math.exp(-(((phase - 0.48) / 0.11) ** 2));
    return 120 * (pulse + reflection - 0.22) + 2 * Math.sin(sample / 35);
  });
}

if (typeof module !== "undefined") module.exports = { PREVIEW_MFCC, previewSamples };
