import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "../../auth/store/authStore.js";
import { notificationsApi } from "../api/notificationsApi.js";

const POLL_INTERVAL_MS = 30_000;

const queryKeys = {
  root: (tenantId, recipientKey) => [
    "tenant-notifications",
    tenantId,
    recipientKey
  ],
  list: (tenantId, recipientKey, limit) => [
    ...queryKeys.root(tenantId, recipientKey),
    "list",
    limit
  ],
  unread: (tenantId, recipientKey) => [
    ...queryKeys.root(tenantId, recipientKey),
    "unread-count"
  ]
};

export function useTenantNotifications({ limit = 5 } = {}) {
  const queryClient = useQueryClient();
  const tenantId = useAuthStore((state) => state.tenantId);
  const user = useAuthStore((state) => state.user);
  const recipientKey =
    user?.id ?? user?.userId ?? user?.user_id ?? user?.email ?? "unknown";
  const enabled = Boolean(tenantId && recipientKey !== "unknown");

  const listQuery = useQuery({
    queryKey: queryKeys.list(tenantId, recipientKey, limit),
    queryFn: ({ signal }) => notificationsApi.list({ limit }, signal),
    enabled,
    retry: false,
    refetchInterval: POLL_INTERVAL_MS,
    refetchOnWindowFocus: true
  });

  const unreadQuery = useQuery({
    queryKey: queryKeys.unread(tenantId, recipientKey),
    queryFn: ({ signal }) => notificationsApi.unreadCount(signal),
    enabled,
    retry: false,
    refetchInterval: POLL_INTERVAL_MS,
    refetchOnWindowFocus: true
  });

  const refreshNotificationQueries = async () => {
    if (!tenantId) return;
    await queryClient.invalidateQueries({
      queryKey: queryKeys.root(tenantId, recipientKey)
    });
  };

  const markReadMutation = useMutation({
    mutationFn: notificationsApi.markRead,
    onSuccess: refreshNotificationQueries
  });

  const archiveMutation = useMutation({
    mutationFn: notificationsApi.archive,
    onSuccess: refreshNotificationQueries
  });

  const readAllMutation = useMutation({
    mutationFn: notificationsApi.readAll,
    onSuccess: refreshNotificationQueries
  });

  return {
    items: listQuery.data?.data?.items ?? [],
    nextCursor: listQuery.data?.data?.nextCursor ?? null,
    unreadCount: Number(unreadQuery.data?.data?.unreadCount ?? 0),
    isLoading: listQuery.isPending || unreadQuery.isPending,
    isError: listQuery.isError || unreadQuery.isError,
    markRead: markReadMutation.mutate,
    archive: archiveMutation.mutate,
    readAll: readAllMutation.mutate,
    markingRead: markReadMutation.isPending,
    archiving: archiveMutation.isPending,
    markingAllRead: readAllMutation.isPending,
    refetch: async () => {
      await Promise.all([listQuery.refetch(), unreadQuery.refetch()]);
    }
  };
}
