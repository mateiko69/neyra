/** Primary photo first in comma list (Discover / matches use first slot). */
export function photoUrlsForApi(urls: string[], primaryIndex: number): string {
  if (!urls.length) return "";
  const i = Math.min(Math.max(0, primaryIndex), urls.length - 1);
  const primary = urls[i];
  const rest = urls.filter((_, j) => j !== i);
  return [primary, ...rest].join(",");
}
