import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { competitorDataApi } from '../api/competitorDataApi.js';
import { discoveryApi } from '../api/discoveryApi.js';

// Without ids: every tracked competitor. With ids (the rows on screen): only those, so the payload follows the page.
export function useCompetitorOverview(ids) {
  const wanted = ids ? [...ids].sort() : null;
  return useQuery({
    queryKey: ['competitor-overview', wanted ? wanted.join(',') : 'all'],
    queryFn: () => competitorDataApi.overview(wanted ? { ids: wanted } : undefined),
    enabled: !wanted || wanted.length > 0,
    placeholderData: (previous) => previous, // keep the rows' details while the next page's arrive
  });
}

export function useCompetitorDataStatus(id, enabled = true) {
  return useQuery({
    queryKey: ['competitor-data-status', id],
    queryFn: () => competitorDataApi.dataStatus(id),
    enabled: Boolean(id) && enabled,
    // A background retry flips `queued` off when it finishes; keep looking while it is queued.
    refetchInterval: (query) => (query.state.data?.queued ? 5000 : false),
  });
}

export function useCompetitorComments(id, sort) {
  return useInfiniteQuery({
    queryKey: ['competitor-comments', id, sort],
    queryFn: ({ pageParam }) => competitorDataApi.comments(id, { sort, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last) => last?.next_offset ?? undefined,
    enabled: Boolean(id),
  });
}

function refreshCompetitorData(queryClient, id) {
  queryClient.invalidateQueries({ queryKey: ['competitor-overview'] });
  queryClient.invalidateQueries({ queryKey: ['competitor-comments'] });
  queryClient.invalidateQueries({ queryKey: ['competitor-data-status'] });
  queryClient.invalidateQueries({ queryKey: ['discovery-competitor', id] });
  queryClient.invalidateQueries({ queryKey: ['competitor-profile', id] });
  queryClient.invalidateQueries({ queryKey: ['product-intelligence'] });
  queryClient.invalidateQueries({ queryKey: ['price-coverage'] });
  queryClient.invalidateQueries({ queryKey: ['price-changes'] });
}

// Retry one competitor (all collectable facets, or the given ones) and refresh what is shown.
export function useRetryCompetitor() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, facets }) => competitorDataApi.retry(id, { facets }),
    onSuccess: (_data, { id }) => refreshCompetitorData(queryClient, id),
  });
}

// Starts one competitor's PRICES / SOCIAL_CONTENT collection in the background (deep = "load more"). The job takes
// a while, so what is shown is refreshed now and again shortly, and the data-status poll keeps going while queued.
export function useRetryFacet() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, facets, depth }) => competitorDataApi.retry(id, { facets, depth, background: true }),
    onSuccess: (_data, { id }) => {
      refreshCompetitorData(queryClient, id);
      setTimeout(() => refreshCompetitorData(queryClient, id), 20000);
      setTimeout(() => refreshCompetitorData(queryClient, id), 60000);
    },
  });
}

export function useRetryAllFailed() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: competitorDataApi.retryAllFailed,
    // The job runs in the background; refresh now and again shortly so finished work appears.
    onSuccess: () => {
      refreshCompetitorData(queryClient);
      setTimeout(() => refreshCompetitorData(queryClient), 15000);
    },
  });
}

export function usePriceCoverage(options) {
  return useQuery({ queryKey: ['price-coverage', options], queryFn: () => competitorDataApi.priceCoverage(options) });
}

export function useFindMissingPrices() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: competitorDataApi.findMissingPrices,
    onSuccess: () => {
      refreshCompetitorData(queryClient);
      setTimeout(() => refreshCompetitorData(queryClient), 20000);
    },
  });
}

export function useSetBarcode() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ productId, barcode }) => competitorDataApi.setBarcode(productId, barcode),
    onSuccess: () => refreshCompetitorData(queryClient),
  });
}

// The owner's decision on one price: refreshes the prices shown, the product comparisons and the coverage that
// are built from them.
export function useReviewIntel(competitorId) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (decision) => discoveryApi.reviewIntel(competitorId, decision),
    onSuccess: () => refreshCompetitorData(queryClient, competitorId),
  });
}

export function usePriceChanges(competitorId, options) {
  return useQuery({
    queryKey: ['price-changes', competitorId, options],
    queryFn: () => discoveryApi.priceChanges(competitorId, options),
    enabled: Boolean(competitorId),
  });
}

export function useRecentPriceChanges(options) {
  return useQuery({ queryKey: ['price-changes', 'all', options], queryFn: () => discoveryApi.recentPriceChanges(options) });
}

export function useCompetitorMatches(competitorId) {
  return useQuery({ queryKey: ['competitor-matches', competitorId], queryFn: () => discoveryApi.matches(competitorId), enabled: Boolean(competitorId) });
}

// The owner's decisions on matches: what is shown, the product comparisons and the coverage built from them refresh.
export function useMatchActions(competitorId) {
  const queryClient = useQueryClient();
  const done = () => {
    refreshCompetitorData(queryClient, competitorId);
    queryClient.invalidateQueries({ queryKey: ['competitor-matches', competitorId] });
  };
  return {
    reject: useMutation({ mutationFn: (productId) => discoveryApi.rejectMatch(competitorId, productId), onSuccess: done }),
    choose: useMutation({ mutationFn: (decision) => discoveryApi.chooseMatch(competitorId, decision), onSuccess: done }),
    clear: useMutation({ mutationFn: (productId) => discoveryApi.clearMatch(competitorId, productId), onSuccess: done }),
  };
}
