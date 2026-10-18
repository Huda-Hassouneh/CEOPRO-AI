import { useEffect, useState } from 'react';
import { marketingApi } from '../api/marketingApi.js';

// Not react-query: an object URL is a real per-fetch browser resource that
// must be revoked exactly once it's no longer displayed, not just cached
// data - a plain effect owns that lifecycle directly rather than layering
// it on top of react-query's own cache/GC timing.
//
// `version` (the campaign's own generated_image_key, or any value that
// changes when the underlying image does) belongs in the dependency array
// alongside campaignId/kind - a regenerate keeps campaignId/kind identical
// but really does produce a different stored image, so without a version
// bump this effect would never re-fetch and the preview would silently
// keep showing the old image.
export function useCampaignImage(campaignId, kind, { enabled = true, version = null } = {}) {
  const [state, setState] = useState({ url: null, type: null, isLoading: false, isError: false });

  useEffect(() => {
    if (!enabled || !campaignId) {
      setState({ url: null, type: null, isLoading: false, isError: false });
      return undefined;
    }
    let objectUrl = null;
    let cancelled = false;
    setState({ url: null, type: null, isLoading: true, isError: false });

    marketingApi.getCampaignImageBlob(campaignId, kind)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setState({ url: objectUrl, type: blob.type || null, isLoading: false, isError: false });
      })
      .catch(() => {
        if (!cancelled) setState({ url: null, type: null, isLoading: false, isError: true });
      });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [campaignId, kind, enabled, version]);

  return state;
}
