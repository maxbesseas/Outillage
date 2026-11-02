const PATTERNS = {
  "0": "000110100",
  "1": "100100001",
  "2": "001100001",
  "3": "101100000",
  "4": "000110001",
  "5": "100110000",
  "6": "001110000",
  "7": "000100101",
  "8": "100100100",
  "9": "001100100",
  A: "100001001",
  B: "001001001",
  C: "101001000",
  D: "000011001",
  E: "100011000",
  F: "001011000",
  G: "000001101",
  H: "100001100",
  I: "001001100",
  J: "000011100",
  K: "100000011",
  L: "001000011",
  M: "101000010",
  N: "000010011",
  O: "100010010",
  P: "001010010",
  Q: "000000111",
  R: "100000110",
  S: "001000110",
  T: "000010110",
  U: "110000001",
  V: "011000001",
  W: "111000000",
  X: "010010001",
  Y: "110010000",
  Z: "011010000",
  "-": "010000101",
  ".": "110000100",
  " ": "011000100",
  "*": "010010100",
};

const GAP = 1;

export function sanitizeForBarcode(code) {
  const upper = String(code || "").toUpperCase();
  let result = "";
  for (const ch of upper) {
    result += PATTERNS[ch] ? ch : "-";
  }
  return result;
}

export function barcodeSVG(code, options = {}) {
  const moduleWidth = options.moduleWidth || 2;
  const height = options.height || 60;
  const showText = options.showText !== false;

  const sanitized = sanitizeForBarcode(code);
  const full = `*${sanitized}*`;

  let x = 0;
  const rects = [];

  for (let i = 0; i < full.length; i++) {
    const pattern = PATTERNS[full[i]] || PATTERNS["-"];
    for (let j = 0; j < pattern.length; j++) {
      const wide = pattern[j] === "1";
      const width = (wide ? 3 : 1) * moduleWidth;
      const isBar = j % 2 === 0;
      if (isBar) {
        rects.push(`<rect x="${x}" y="0" width="${width}" height="${height}" fill="#000"/>`);
      }
      x += width;
    }
    if (i < full.length - 1) {
      x += GAP * moduleWidth;
    }
  }

  const totalWidth = x;
  const textHeight = showText ? 16 : 0;
  const svgHeight = height + textHeight;

  const text = showText
    ? `<text x="${totalWidth / 2}" y="${height + 12}" text-anchor="middle" font-family="monospace" font-size="12">${sanitized}</text>`
    : "";

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${totalWidth}" height="${svgHeight}" viewBox="0 0 ${totalWidth} ${svgHeight}">
    <rect x="0" y="0" width="${totalWidth}" height="${svgHeight}" fill="#fff"/>
    ${rects.join("")}
    ${text}
  </svg>`;
}
