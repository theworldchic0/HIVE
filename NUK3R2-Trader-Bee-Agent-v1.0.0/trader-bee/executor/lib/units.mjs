// Decimal-string <-> base-unit BigInt. Truncates, never rounds up into a bigger trade
// (terminal FIXES-LOG AX: a rounded-up sell overshot the balance and was refused).
export function toRaw(value, decimals) {
  const s = String(value).trim();
  if (!/^\d*\.?\d*$/.test(s) || s === "" || s === ".") throw new Error(`bad numeric string: ${value}`);
  const [whole = "0", frac = ""] = s.split(".");
  return BigInt((whole || "0") + (frac + "0".repeat(decimals)).slice(0, decimals));
}

export function fromRaw(value, decimals) {
  const v = BigInt(value);
  const neg = v < 0n;
  const abs = neg ? -v : v;
  const base = 10n ** BigInt(decimals);
  const frac = (abs % base).toString().padStart(decimals, "0").replace(/0+$/, "");
  return `${neg ? "-" : ""}${abs / base}${frac ? "." + frac : ""}`;
}

export const num = (raw, decimals) => Number(fromRaw(raw, decimals));

// fixed-point string for a JS number without exponent notation, truncated to `decimals`
export function fixed(n, decimals) {
  if (!Number.isFinite(n) || n < 0) throw new Error(`bad amount ${n}`);
  const s = n.toFixed(Math.min(decimals, 20));
  return s;
}
