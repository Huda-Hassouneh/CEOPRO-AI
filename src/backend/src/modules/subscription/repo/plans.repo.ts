import { prisma } from "../../../config/database.js";
import { Plan, Prisma } from "../../../generated/prisma/client.js";

async function createPlan(data: Plan) {
  console.log(data);

  return prisma.plan.create({ data: { ...data } });
}
async function getPlainByName(name: string) {
  return prisma.plan.findUnique({
    where: {
      name
    }
  });
}

async function getPlanById(id: string) {
  return prisma.plan.findUnique({
    where: {
      id
    }
  });
}
async function getPlanByPriceId(id: string) {
  return prisma.plan.findUnique({
    where: { paymentProviderPlanId: id }
  });
}
async function updatePlan(id: string, data: Prisma.PlanUpdateInput) {
  // const { id: planId, ...d } = data;
  return prisma.plan.update({
    where: { id },
    data
  });
}
async function getAllPlans() {
  return prisma.plan.findMany();
}
export default {
  getAllPlans,
  updatePlan,
  getPlanByPriceId,
  getPlanById,
  getPlainByName,
  createPlan
};
