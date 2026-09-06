import { fileURLToPath } from "node:url";
import chalk from "chalk";
import dotenv from "dotenv";
// get root directory based on its name
function getRootDirectoryPath(url: string, rootDirStr: string) {
  if (!url.includes(rootDirStr)) {
    throw new Error("Cut after string is not exist in provided url !");
  }
  return url.substring(0, url.lastIndexOf(rootDirStr) + rootDirStr.length);
}
function initlizeDotEnv() {
  const fileName = fileURLToPath(import.meta.url);
  try {
    const rootDir = getRootDirectoryPath(fileName, "backend");
    console.log(".env location: ", rootDir.concat("\\.env"));

    const config: dotenv.DotenvConfigOptions = {
      path: rootDir.concat("\\.env")
    };
    dotenv.config(config);
  } catch (err: any) {
    console.log(chalk.red(err.message));
  }
}
initlizeDotEnv();
