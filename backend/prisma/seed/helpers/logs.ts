export function section(title: string): void {
  console.log("");
  console.log("========================================");
  console.log(title);
  console.log("========================================");
}

export function step(message: string): void {
  console.log(`→ ${message}`);
}

export function success(message: string): void {
  console.log(`  ✔ ${message}`);
}
