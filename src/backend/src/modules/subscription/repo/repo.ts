import { prisma } from "../../../config/database.js";

export async function insertAppConfig(key: string, value: string) {
  return prisma.appConfig.create({
    data: {
      key,
      value
    }
  });
}
export async function getAppConfig(key: string) {
  return prisma.appConfig.findUnique({
    where: {
      key
    }
  });
}
