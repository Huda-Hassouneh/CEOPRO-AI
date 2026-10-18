import {PrismaPg} from '@prisma/adapter-pg';
import {PrismaClient} from '../generated/prisma/client.js';
import {getRequiredEnv} from './env.js';
export const marketDispatcherPrisma=new PrismaClient({adapter:new PrismaPg({connectionString:getRequiredEnv('MARKET_DISPATCHER_DATABASE_URL')})});
