import sharp from 'sharp';
const src = process.argv[2], out = process.argv[3];
const navy = { r: 18, g: 27, b: 51, alpha: 1 };
await sharp(src).resize(192, 192).png().toFile(`${out}/icon-192.png`);
await sharp(src).resize(512, 512).png().toFile(`${out}/icon-512.png`);
// maskable: shrink into the 80% safe zone on the same navy
const inner = await sharp(src).resize(410, 410).png().toBuffer();
await sharp({ create: { width: 512, height: 512, channels: 4, background: navy } }).composite([{ input: inner, gravity: 'center' }]).png().toFile(`${out}/icon-512-maskable.png`);
await sharp(src).resize(180, 180).flatten({ background: navy }).png().toFile(`${out}/apple-touch-icon.png`);
console.log('icons written');
