export const competitorsApi = {
  list: async () => ({ competitors: [] }),
  profile: async (id) => ({ id, competitor: null }),
  create: async (payload) => ({ ok: true, payload }),
};
