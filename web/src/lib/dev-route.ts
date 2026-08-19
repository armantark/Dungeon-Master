export const ARCHITECTURE_PATH = "/__dev/architecture";

export function shouldMountArchitecture(
  pathname: string,
  devMode: boolean,
  enabled: boolean,
): boolean {
  const normalized = pathname.length > 1 ? pathname.replace(/\/$/, "") : pathname;
  return devMode && enabled && normalized === ARCHITECTURE_PATH;
}
