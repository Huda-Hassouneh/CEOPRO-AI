import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { marketingApi } from '../api/marketingApi.js';

// The campaign's image gallery, newest first.
export function useCampaignAssets(campaignId, { enabled = true } = {}) {
  return useQuery({
    queryKey: ['marketing-assets', campaignId],
    queryFn: () => marketingApi.listAssets(campaignId),
    enabled: Boolean(campaignId) && enabled,
  });
}

function useRefreshAfterAssetChange() {
  const queryClient = useQueryClient();
  return (campaignId) => {
    queryClient.invalidateQueries({ queryKey: ['marketing-assets', campaignId] });
    queryClient.invalidateQueries({ queryKey: ['marketing-campaign', campaignId] });
    queryClient.invalidateQueries({ queryKey: ['marketing-campaigns'] });
  };
}

export function useUpdateAsset() {
  const refresh = useRefreshAfterAssetChange();
  return useMutation({
    mutationFn: ({ campaignId, assetId, ...changes }) => marketingApi.updateAsset(campaignId, assetId, changes),
    onSuccess: (_data, { campaignId }) => refresh(campaignId),
  });
}

export function useDeleteAsset() {
  const refresh = useRefreshAfterAssetChange();
  return useMutation({
    mutationFn: ({ campaignId, assetId }) => marketingApi.deleteAsset(campaignId, assetId),
    onSuccess: (_data, { campaignId }) => refresh(campaignId),
  });
}

// One gallery image as an object URL (fetched through the authenticated
// API, revoked when no longer shown) - same lifecycle as useCampaignImage.
export function useAssetImage(campaignId, assetId) {
  const [state, setState] = useState({ url: null, type: null, isLoading: false, isError: false });
  useEffect(() => {
    if (!campaignId || !assetId) return undefined;
    let objectUrl = null;
    let cancelled = false;
    setState({ url: null, type: null, isLoading: true, isError: false });
    marketingApi.getAssetImageBlob(campaignId, assetId)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setState({ url: objectUrl, type: blob.type || null, isLoading: false, isError: false });
      })
      .catch(() => { if (!cancelled) setState({ url: null, type: null, isLoading: false, isError: true }); });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [campaignId, assetId]);
  return state;
}
