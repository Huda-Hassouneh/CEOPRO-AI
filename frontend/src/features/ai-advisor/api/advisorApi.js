export const advisorApi = {
  listSessions: async () => ({ sessions: [] }),
  chat: async (payload) => ({ message: payload }),
  evidenceTrail: async (sessionId) => ({ sessionId, evidence: [] }),
};
