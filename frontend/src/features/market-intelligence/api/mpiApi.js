import { translateCurrent } from '../../../shared/lib/i18n.js';
import httpClient from "../../../shared/lib/httpClient.js";

export const mpiApi = {
  async getSummary({ subjectType, subjectId, signal }) {
    if (!["BUSINESS", "PRODUCT", "COMPETITOR"].includes(subjectType) ||
        (subjectType !== "BUSINESS" && !subjectId)) throw new Error(translateCurrent("interfaceCopy.perceptionSubjectRequired"));
    const response = await httpClient.get("/features/mpi/summary", {
      params: { subject_type: subjectType, ...(subjectId ? { subject_id: subjectId } : {}) }, signal
    });
    return response.data?.data ?? response.data;
  }
};
