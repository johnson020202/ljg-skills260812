import { expect, test } from "bun:test";
import { deflateSync, inflateSync } from "node:zlib";
import { joinPngStrips } from "../assets/png-strips";

function chunk(type: string, bytes: Buffer) {
  const result = Buffer.alloc(bytes.length + 12);
  result.writeUInt32BE(bytes.length);
  result.write(type, 4);
  bytes.copy(result, 8);
  result.writeUInt32BE(Bun.hash.crc32(result.subarray(4, -4)), result.length - 4);
  return result;
}
function fixture(channels: number, filter: number) {
  const width = 2, height = 2;
  const pixels = Array.from({ length: width * height * channels }, (_, index) => (index * 47 + 11) % 256);
  const bytes = Buffer.alloc((width * channels + 1) * height);
  for (let y = 0; y < height; y++) {
    const start = y * (width * channels + 1);
    bytes[start] = filter;
    for (let x = 0; x < width * channels; x++) {
      const i = y * width * channels + x;
      const left = x >= channels ? pixels[i - channels] : 0;
      const up = y ? pixels[i - width * channels] : 0;
      const corner = y && x >= channels ? pixels[i - width * channels - channels] : 0;
      const p = left + up - corner;
      const nearest = [left, up, corner].reduce((a, b) => Math.abs(p - a) <= Math.abs(p - b) ? a : b);
      const predictor = [0, left, up, Math.floor((left + up) / 2), nearest][filter];
      bytes[start + 1 + x] = pixels[i] - predictor;
    }
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width); header.writeUInt32BE(height, 4);
  header[8] = 8; header[9] = channels === 3 ? 2 : 6;
  return { pixels, png: Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]), chunk("IHDR", header), chunk("IDAT", deflateSync(bytes)), chunk("IEND", Buffer.alloc(0))]) };
}

for (const channels of [3, 4]) {
  test(`stitches all PNG filters, verifies CRCs and exact ${channels}-channel pixels`, () => {
    const fixtures = Array.from({ length: 5 }, (_, filter) => fixture(channels, filter));
    const png = joinPngStrips(fixtures.map(item => item.png), 2, 10);
    expect(png.readUInt32BE(16)).toBe(2);
    expect(png.readUInt32BE(20)).toBe(10);
    const compressed: Buffer[] = [];
    for (let offset = 8; offset < png.length;) {
      const length = png.readUInt32BE(offset);
      expect(png.readUInt32BE(offset + length + 8)).toBe(Bun.hash.crc32(png.subarray(offset + 4, offset + 8 + length)));
      if (png.toString("ascii", offset + 4, offset + 8) === "IDAT") compressed.push(png.subarray(offset + 8, offset + 8 + length));
      offset += length + 12;
    }
    const raw = inflateSync(Buffer.concat(compressed));
    const actual: number[] = [];
    for (let y = 0; y < 10; y++) {
      expect(raw[y * 9]).toBe(1);
      for (let x = 0; x < 8; x++) actual.push((raw[y * 9 + 1 + x] + (x >= 4 ? actual.at(-4)! : 0)) % 256);
    }
    const expected = fixtures.flatMap(item => {
      const rgba: number[] = [];
      for (let i = 0; i < item.pixels.length; i += channels) rgba.push(...item.pixels.slice(i, i + 3), channels === 4 ? item.pixels[i + 3] : 255);
      return rgba;
    });
    expect(actual).toEqual(expected);
  });
}
test("PNG stitcher rejects inconsistent dimensions and oversized output", () => {
  const png = fixture(3, 0).png;
  expect(() => joinPngStrips([png], 3, 2)).toThrow("dimensions");
  expect(() => joinPngStrips([png], 2, 3)).toThrow("Incomplete");
  expect(() => joinPngStrips([png], 10000, 10000)).toThrow("budget");
});
