// Générateur de QR Code (mode octets, correction d'erreur M, versions 1 à 10 — jusqu'à 174 octets).
const ECC_PER_BLOCK = [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26];
const NUM_BLOCKS = [-1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5];
const MAX_VERSION = 10;

function rawModules(ver) {
  let r = (16 * ver + 128) * ver + 64;
  if (ver >= 2) {
    const n = Math.floor(ver / 7) + 2;
    r -= (25 * n - 10) * n - 55;
    if (ver >= 7) r -= 36;
  }
  return r;
}

function dataCapacity(ver) {
  return Math.floor(rawModules(ver) / 8) - ECC_PER_BLOCK[ver] * NUM_BLOCKS[ver];
}

function gfMul(x, y) {
  let z = 0;
  for (let i = 7; i >= 0; i--) {
    z = (z << 1) ^ ((z >>> 7) * 0x11d);
    z ^= ((y >>> i) & 1) * x;
  }
  return z;
}

function rsDivisor(degree) {
  const result = new Array(degree).fill(0);
  result[degree - 1] = 1;
  let root = 1;
  for (let i = 0; i < degree; i++) {
    for (let j = 0; j < degree; j++) {
      result[j] = gfMul(result[j], root);
      if (j + 1 < degree) result[j] ^= result[j + 1];
    }
    root = gfMul(root, 2);
  }
  return result;
}

function rsRemainder(data, divisor) {
  const result = new Array(divisor.length).fill(0);
  for (const b of data) {
    const factor = b ^ result.shift();
    result.push(0);
    divisor.forEach((coef, i) => {
      result[i] ^= gfMul(coef, factor);
    });
  }
  return result;
}

function encodeData(bytes, ver) {
  const bits = [];
  const put = (val, len) => {
    for (let i = len - 1; i >= 0; i--) bits.push((val >>> i) & 1);
  };
  put(0b0100, 4);
  put(bytes.length, ver < 10 ? 8 : 16);
  bytes.forEach((b) => put(b, 8));
  const capBits = dataCapacity(ver) * 8;
  put(0, Math.min(4, capBits - bits.length));
  put(0, (8 - (bits.length % 8)) % 8);
  const out = [];
  for (let i = 0; i < bits.length; i += 8) {
    let v = 0;
    for (let j = 0; j < 8; j++) v = (v << 1) | bits[i + j];
    out.push(v);
  }
  for (let pad = 0xec; out.length < dataCapacity(ver); pad ^= 0xec ^ 0x11) out.push(pad);
  return out;
}

function addEccAndInterleave(data, ver) {
  const numBlocks = NUM_BLOCKS[ver];
  const eccLen = ECC_PER_BLOCK[ver];
  const raw = Math.floor(rawModules(ver) / 8);
  const numShort = numBlocks - (raw % numBlocks);
  const shortLen = Math.floor(raw / numBlocks);
  const divisor = rsDivisor(eccLen);
  const blocks = [];
  for (let i = 0, k = 0; i < numBlocks; i++) {
    const dat = data.slice(k, k + shortLen - eccLen + (i < numShort ? 0 : 1));
    k += dat.length;
    const ecc = rsRemainder(dat, divisor);
    if (i < numShort) dat.push(0);
    blocks.push(dat.concat(ecc));
  }
  const result = [];
  for (let i = 0; i < blocks[0].length; i++) {
    blocks.forEach((block, j) => {
      if (i !== shortLen - eccLen || j >= numShort) result.push(block[i]);
    });
  }
  return result;
}

function alignPositions(ver) {
  if (ver === 1) return [];
  const n = Math.floor(ver / 7) + 2;
  const step = Math.ceil((ver * 4 + 4) / (n * 2 - 2)) * 2;
  const res = [6];
  for (let pos = ver * 4 + 10; res.length < n; pos -= step) res.splice(1, 0, pos);
  return res;
}

function buildMatrix(codewords, ver) {
  const size = ver * 4 + 17;
  const modules = Array.from({ length: size }, () => new Array(size).fill(false));
  const isFn = Array.from({ length: size }, () => new Array(size).fill(false));
  const setFn = (x, y, dark) => {
    modules[y][x] = dark;
    isFn[y][x] = true;
  };

  for (let i = 0; i < size; i++) {
    setFn(6, i, i % 2 === 0);
    setFn(i, 6, i % 2 === 0);
  }
  const finder = (cx, cy) => {
    for (let dy = -4; dy <= 4; dy++) {
      for (let dx = -4; dx <= 4; dx++) {
        const dist = Math.max(Math.abs(dx), Math.abs(dy));
        const x = cx + dx;
        const y = cy + dy;
        if (x >= 0 && x < size && y >= 0 && y < size) setFn(x, y, dist !== 2 && dist !== 4);
      }
    }
  };
  finder(3, 3);
  finder(size - 4, 3);
  finder(3, size - 4);
  const pos = alignPositions(ver);
  pos.forEach((cy, i) => {
    pos.forEach((cx, j) => {
      if ((i === 0 && j === 0) || (i === 0 && j === pos.length - 1) || (i === pos.length - 1 && j === 0)) return;
      for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) setFn(cx + dx, cy + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
    });
  });

  const drawFormat = (mask) => {
    const data = (0 << 3) | mask; // niveau M = 0b00
    let rem = data;
    for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
    const bits = ((data << 10) | rem) ^ 0x5412;
    const bit = (i) => ((bits >>> i) & 1) !== 0;
    for (let i = 0; i <= 5; i++) setFn(8, i, bit(i));
    setFn(8, 7, bit(6));
    setFn(8, 8, bit(7));
    setFn(7, 8, bit(8));
    for (let i = 9; i < 15; i++) setFn(14 - i, 8, bit(i));
    for (let i = 0; i < 8; i++) setFn(size - 1 - i, 8, bit(i));
    for (let i = 8; i < 15; i++) setFn(8, size - 15 + i, bit(i));
    setFn(8, size - 8, true);
  };
  drawFormat(0);

  if (ver >= 7) {
    let rem = ver;
    for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
    const bits = (ver << 12) | rem;
    for (let i = 0; i < 18; i++) {
      const dark = ((bits >>> i) & 1) !== 0;
      const a = size - 11 + (i % 3);
      const b = Math.floor(i / 3);
      setFn(a, b, dark);
      setFn(b, a, dark);
    }
  }

  let i = 0;
  for (let right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5;
    for (let vert = 0; vert < size; vert++) {
      for (let j = 0; j < 2; j++) {
        const x = right - j;
        const upward = ((right + 1) & 2) === 0;
        const y = upward ? size - 1 - vert : vert;
        if (!isFn[y][x] && i < codewords.length * 8) {
          modules[y][x] = ((codewords[i >>> 3] >>> (7 - (i & 7))) & 1) !== 0;
          i++;
        }
      }
    }
  }

  const applyMask = (mask) => {
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        let inv;
        switch (mask) {
          case 0: inv = (x + y) % 2 === 0; break;
          case 1: inv = y % 2 === 0; break;
          case 2: inv = x % 3 === 0; break;
          case 3: inv = (x + y) % 3 === 0; break;
          case 4: inv = (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0; break;
          case 5: inv = ((x * y) % 2) + ((x * y) % 3) === 0; break;
          case 6: inv = (((x * y) % 2) + ((x * y) % 3)) % 2 === 0; break;
          default: inv = (((x + y) % 2) + ((x * y) % 3)) % 2 === 0;
        }
        if (inv && !isFn[y][x]) modules[y][x] = !modules[y][x];
      }
    }
  };

  const penalty = () => {
    let p = 0;
    const line = (get) => {
      for (let a = 0; a < size; a++) {
        let run = 1;
        for (let b = 1; b < size; b++) {
          if (get(a, b) === get(a, b - 1)) {
            run++;
            if (run === 5) p += 3;
            else if (run > 5) p++;
          } else run = 1;
        }
      }
    };
    line((a, b) => modules[a][b]);
    line((a, b) => modules[b][a]);
    for (let y = 0; y < size - 1; y++) {
      for (let x = 0; x < size - 1; x++) {
        const c = modules[y][x];
        if (c === modules[y][x + 1] && c === modules[y + 1][x] && c === modules[y + 1][x + 1]) p += 3;
      }
    }
    const dark = modules.reduce((s, row) => s + row.filter(Boolean).length, 0);
    p += Math.floor(Math.abs(dark * 20 - size * size * 10) / (size * size)) * 10;
    return p;
  };

  let best = 0;
  let bestPenalty = Infinity;
  for (let m = 0; m < 8; m++) {
    applyMask(m);
    drawFormat(m);
    const pn = penalty();
    if (pn < bestPenalty) {
      bestPenalty = pn;
      best = m;
    }
    applyMask(m);
  }
  applyMask(best);
  drawFormat(best);
  return modules;
}

export function qrMatrix(text) {
  const bytes = Array.from(new TextEncoder().encode(text));
  for (let ver = 1; ver <= MAX_VERSION; ver++) {
    const headerBits = 4 + (ver < 10 ? 8 : 16);
    if (Math.ceil((headerBits + bytes.length * 8) / 8) <= dataCapacity(ver)) {
      return buildMatrix(addEccAndInterleave(encodeData(bytes, ver), ver), ver);
    }
  }
  throw new Error("Texte trop long pour le QR code");
}

export function qrSVG(text, { size = 96, margin = 2 } = {}) {
  const m = qrMatrix(text);
  const n = m.length + margin * 2;
  let d = "";
  m.forEach((row, y) =>
    row.forEach((dark, x) => {
      if (dark) d += `M${x + margin} ${y + margin}h1v1h-1z`;
    })
  );
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${n} ${n}" width="${size}" height="${size}" shape-rendering="crispEdges" role="img" aria-label="QR code ${text.replace(/[<>&"]/g, "")}"><rect width="${n}" height="${n}" fill="#fff"/><path d="${d}" fill="#000"/></svg>`;
}
