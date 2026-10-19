import { deflateSync, inflateSync } from "node:zlib";

// Only accepts the 8-bit, non-interlaced RGB(A) PNGs produced by Chromium.
// Reconstructing scanlines is necessary: each strip starts a new PNG filter history.
function unpack(png: Buffer) {
  if (!png.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) throw new Error("Invalid screenshot PNG");
  const width = png.readUInt32BE(16), height = png.readUInt32BE(20);
  const channels = png[25] === 2 ? 3 : png[25] === 6 ? 4 : 0;
  if (png[24] !== 8 || !channels || png[26] || png[27] || png[28]) throw new Error("Unsupported screenshot PNG format");
  const chunks: Buffer[] = [];
  for (let offset = 8; offset + 12 <= png.length;) {
    const length = png.readUInt32BE(offset);
    if (offset + 12 + length > png.length) throw new Error("Truncated screenshot PNG");
    if (png.toString("ascii", offset + 4, offset + 8) === "IDAT") chunks.push(png.subarray(offset + 8, offset + 8 + length));
    offset += length + 12;
  }
  const stride = width * channels;
  const filtered = inflateSync(Buffer.concat(chunks), { maxOutputLength: (stride + 1) * height });
  if (filtered.length !== (stride + 1) * height) throw new Error("Truncated screenshot pixels");
  const pixels = Buffer.alloc(stride * height);
  for (let y = 0; y < height; y++) {
    const filter = filtered[y * (stride + 1)];
    if (filter > 4) throw new Error("Invalid PNG filter");
    for (let x = 0; x < stride; x++) {
      const index = y * stride + x;
      const left = x >= channels ? pixels[index - channels] : 0;
      const up = y ? pixels[index - stride] : 0;
      const corner = y && x >= channels ? pixels[index - stride - channels] : 0;
      const p = left + up - corner;
      const a = Math.abs(p - left), b = Math.abs(p - up), c = Math.abs(p - corner);
      const predictor = filter === 0 ? 0 : filter === 1 ? left : filter === 2 ? up : filter === 3 ? Math.floor((left + up) / 2) : a <= b && a <= c ? left : b <= c ? up : corner;
      pixels[index] = filtered[y * (stride + 1) + 1 + x] + predictor;
    }
  }
  return { width, height, channels, pixels };
}

const crcTable = Array.from({ length: 256 }, (_, n) => {
  for (let i = 0; i < 8; i++) n = (n & 1) ? 0xedb88320 ^ (n >>> 1) : n >>> 1;
  return n >>> 0;
});
function chunk(type: string, data: Buffer) {
  const result = Buffer.alloc(data.length + 12);
  result.writeUInt32BE(data.length);
  result.write(type, 4, 4, "ascii");
  data.copy(result, 8);
  let crc = 0xffffffff;
  for (const byte of result.subarray(4, -4)) crc = crcTable[(crc ^ byte) & 255] ^ (crc >>> 8);
  result.writeUInt32BE((crc ^ 0xffffffff) >>> 0, result.length - 4);
  return result;
}

export function joinPngStrips(strips: Buffer[], width: number, height: number): Buffer {
  if (!strips.length || width * height > 64_000_000) throw new Error("Screenshot exceeds the 64 megapixel budget");
  // Encode filter type 1 (Sub): efficient for horizontal runs, no cross-strip dependency.
  const rows = Buffer.alloc((width * 4 + 1) * height);
  let row = 0;
  for (const strip of strips) {
    const image = unpack(strip);
    if (image.width !== width || row + image.height > height) throw new Error("Screenshot strip dimensions changed");
    for (let y = 0; y < image.height; y++, row++) {
      const start = row * (width * 4 + 1);
      rows[start] = 1;
      for (let x = 0; x < width; x++) {
        for (let channel = 0; channel < 4; channel++) {
          const value = channel === 3 && image.channels === 3 ? 255 : image.pixels[(y * width + x) * image.channels + channel];
          const left = x === 0 ? 0 : channel === 3 && image.channels === 3 ? 255 : image.pixels[(y * width + x - 1) * image.channels + channel];
          rows[start + 1 + x * 4 + channel] = value - left;
        }
      }
    }
  }
  if (row !== height) throw new Error("Incomplete screenshot strips");
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width); header.writeUInt32BE(height, 4);
  header[8] = 8; header[9] = 6;
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", header), chunk("IDAT", deflateSync(rows)), chunk("IEND", Buffer.alloc(0)),
  ]);
}
