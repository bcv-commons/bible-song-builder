// Small helpers that give exactly what the Python reference gives (bible_song_builder/), where
// JavaScript's own functions differ: whitespace, strip, split, word runs, Counter order.

// A verse is one integer: chapter * 1000 + verse. It sorts and compares as Python's (c, v) does.
export const cvKey = (c, v) => c * 1000 + v;
export const cvC = (k) => Math.floor(k / 1000);
export const cvV = (k) => k % 1000;
export const fmtCv = (k) => `${cvC(k)}:${cvV(k)}`;

// Python's str.isspace() characters
const PY_SPACE = '\\t\\n\\v\\f\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
const SPACE_RUN = new RegExp(`[${PY_SPACE}]+`, 'u');
const LEAD = new RegExp(`^[${PY_SPACE}]+`, 'u');
const TRAIL = new RegExp(`[${PY_SPACE}]+$`, 'u');
const ONE_SPACE = new RegExp(`^[${PY_SPACE}]$`, 'u');

export const isPySpace = (ch) => ONE_SPACE.test(ch);
/** str.strip() */
export const pyStrip = (s) => s.replace(LEAD, '').replace(TRAIL, '');
/** str.rstrip() */
export const pyRstrip = (s) => s.replace(TRAIL, '');
/** str.split() */
export const pySplit = (s) => s.split(SPACE_RUN).filter((x) => x !== '');
/** str.strip(chars) */
export function stripChars(s, chars) {
    const set = new Set(chars);
    const cps = [...s];
    let a = 0, b = cps.length;
    while (a < b && set.has(cps[a])) a++;
    while (b > a && set.has(cps[b - 1])) b--;
    return cps.slice(a, b).join('');
}
/** s.split(sep, 1) */
export function splitOnce(s, sep) {
    const i = s.indexOf(sep);
    return i < 0 ? [s] : [s.slice(0, i), s.slice(i + sep.length)];
}
export const removePrefix = (s, p) => (s.startsWith(p) ? s.slice(p.length) : s);
/** len() of a str: code points */
export const pyLen = (s) => [...s].length;
/** f"{x}" for a value that may be None */
export const pyStr = (x) => (x === null || x === undefined ? 'None' : String(x));

// Python's [^\W\d_]: letters, and numbers that are not decimal digits (no combining marks)
export const WORD_RUN = /[\p{L}\p{Nl}\p{No}]+/gu;
export const WORD_CHAR = /[\p{L}\p{Nl}\p{No}]/gu;
export const wordRuns = (s) => s.match(WORD_RUN) || [];

export const isObj = (x) => x !== null && typeof x === 'object' && !Array.isArray(x);
export const sortedNums = (xs) => [...xs].sort((a, b) => a - b);
export const minOf = (xs) => Math.min(...xs);
export const maxOf = (xs) => Math.max(...xs);
export const unique = (xs) => [...new Set(xs)];

/** Counter.most_common(1)[0][0]: the first of the largest counts (a Map in insertion order) */
export function mostCommon(counter) {
    let best, bestN = -Infinity;
    for (const [k, n] of counter) if (n > bestN) { best = k; bestN = n; }
    return best;
}
export function count(counter, key, n = 1) {
    counter.set(key, (counter.get(key) || 0) + n);
}
/** Python's tuple comparison a < b, for arrays of numbers */
export function tupleLess(a, b) {
    for (let i = 0; i < Math.min(a.length, b.length); i++) {
        if (a[i] !== b[i]) return a[i] < b[i];
    }
    return a.length < b.length;
}
export function getOr(map, key, make) {
    let v = map.get(key);
    if (v === undefined) { v = make(); map.set(key, v); }
    return v;
}

export class ConfigError extends Error {}
