/** Drop the previous account's browser-only job handles. The session cookie is HttpOnly and is not stored here. */
export function resetAccountStorage(storage: Pick<Storage, "clear">, previousId: string | null, nextId: string | null): void {
  if (previousId !== nextId) storage.clear();
}
