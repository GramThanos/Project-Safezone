// Dates as the reader expects to see them.
//
// `toLocaleString()` with no locale formats in the browser's *interface*
// language, which is not the reader's preference: an English (US) Chrome on a
// machine set up for Greece still prints 10/7/2026. `navigator.languages` is the
// ordered list the person actually chose (the same one sent as
// Accept-Language), so it is passed explicitly everywhere.
//
// The API sends naive-UTC ISO strings (`datetime.utcnow().isoformat()`), which
// `Date` would read as local time and shift by the reader's offset — so a
// string without a zone is treated as UTC.

const locales = () => {
  if (typeof navigator === 'undefined') return undefined;
  if (navigator.languages && navigator.languages.length) return [...navigator.languages];
  return navigator.language || undefined;
};

const HAS_ZONE = /(Z|[+-]\d\d:?\d\d)$/i;

// An ISO string, a Date or epoch milliseconds -> Date, or null when unusable.
export const parseDate = (value) => {
  if (value === null || value === undefined || value === '') return null;
  let date;
  if (value instanceof Date) date = value;
  else if (typeof value === 'number') date = new Date(value);
  else {
    const text = String(value).trim();
    // Only a date-and-time is naive; a bare `YYYY-MM-DD` is already read as UTC.
    date = new Date(text.includes('T') && !HAS_ZONE.test(text) ? `${text}Z` : text);
  }
  return Number.isNaN(date.getTime()) ? null : date;
};

// Epoch seconds, as Steam and the manager report them.
export const fromUnix = (seconds) => (seconds ? new Date(seconds * 1000) : null);

const format = (value, options, fallback) => {
  const date = parseDate(value);
  if (!date) return fallback;
  try {
    return date.toLocaleString(locales(), options);
  } catch {
    return date.toLocaleString(undefined, options);
  }
};

export const formatDateTime = (value, fallback = '') =>
  format(value, { dateStyle: 'short', timeStyle: 'medium' }, fallback);

export const formatDate = (value, fallback = '') =>
  format(value, { dateStyle: 'short' }, fallback);

export const formatTime = (value, fallback = '') =>
  format(value, { hour: '2-digit', minute: '2-digit' }, fallback);
