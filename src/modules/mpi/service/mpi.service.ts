import { requestMpiSummary } from "../client/mpi.client.js";
import type {
  AiMpiSummaryResponse,
  MpiSubjectType
} from "../types/mpi.types.js";

export async function getMpiSummary(input: {
  subjectType: MpiSubjectType;
  subjectId?: string;
  authorization: string;
}): Promise<AiMpiSummaryResponse> {
  console.log(await requestMpiSummary(input));

  return requestMpiSummary(input);
}
