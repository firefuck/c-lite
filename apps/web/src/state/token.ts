// The session token: read once from the link `clite dashboard` prints, then kept in session
// storage so a reload or a reconnect does not need the link again.

export interface TokenStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export interface AddressBar {
  hash: string;
  search: string;
  pathname: string;
  /** Rewrite the address without reloading (``history.replaceState``). */
  replace(path: string): void;
}

const KEY = "clite-token";

/** The token from the address (``#token=``, or ``?token=``), else the one stored earlier.
 *  A token found in the address is removed from it, so it stays out of history. */
export function takeToken(address: AddressBar, storage: TokenStorage): string {
  const fromUrl =
    new URLSearchParams(address.hash.slice(1)).get("token") || new URLSearchParams(address.search).get("token");
  if (fromUrl) {
    storage.setItem(KEY, fromUrl);
    address.replace(address.pathname);
  }
  return storage.getItem(KEY) || "";
}

export function storeToken(storage: TokenStorage, token: string): void {
  storage.setItem(KEY, token);
}

export function forgetToken(storage: TokenStorage): void {
  storage.removeItem(KEY);
}

export function storedToken(storage: TokenStorage): string {
  return storage.getItem(KEY) || "";
}
