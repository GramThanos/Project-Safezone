// Small, deliberately boring helpers for admin configuration transfers.  Files
// are JSON rather than CSV because rewards and shop listings carry nested data
// (commands and several categories) that CSV cannot represent without lossy
// conventions.

export const downloadJson = (data, filename) => {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
};

export const readJsonFile = (file) => new Promise((resolve, reject) => {
  if (!file) return reject(new Error('Choose a JSON file first.'));
  if (file.size > 2 * 1024 * 1024) return reject(new Error('The import file is too large.'));
  const reader = new FileReader();
  reader.onerror = () => reject(new Error('Could not read that file.'));
  reader.onload = () => {
    try {
      resolve(JSON.parse(reader.result));
    } catch {
      reject(new Error('That file is not valid JSON.'));
    }
  };
  reader.readAsText(file);
});
