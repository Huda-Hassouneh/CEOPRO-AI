export function line() {
  console.log("============================================================");
}

export function logStep(message: string) {
  console.log(`\n→ ${message}`);
}

export function success(message: string) {
  console.log(`  ✔ ${message}`);
}

export function info(message: string) {
  console.log(`  • ${message}`);
}

export function warn(message: string, error?: unknown) {
  console.warn(`  ! ${message}`, ...(error !== undefined ? [error] : []));
}
