import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Building2, Check, Plus } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { workspacesApi } from '../api/workspacesApi.js';
import { useOpenWorkspace } from '../useOpenWorkspace.js';

// The company list inside the profile menu: open another company or start a new one.
export function WorkspaceSwitcher({ onDone }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const openWorkspace = useOpenWorkspace();
  const [busy, setBusy] = useState(null);
  const [failed, setFailed] = useState(false);
  const query = useQuery({ queryKey: ['workspaces'], queryFn: workspacesApi.list, staleTime: 60_000 });
  const workspaces = query.data?.workspaces || [];

  const choose = async (tenantId) => {
    if (tenantId === query.data?.current_tenant_id || busy) return;
    setBusy(tenantId);
    setFailed(false);
    try {
      const session = await workspacesApi.switchTo(tenantId);
      onDone?.();
      openWorkspace(session);
    } catch {
      setFailed(true);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="workspace-switcher" role="group" aria-label={t('workspaces.label')}>
      <p className="workspace-switcher__title">{t('workspaces.label')}</p>
      {workspaces.length > 1 && workspaces.map((w) => {
        const current = w.tenant_id === query.data.current_tenant_id;
        return (
          <button key={w.tenant_id} type="button" role="menuitemradio" aria-checked={current} disabled={Boolean(busy)} onClick={() => choose(w.tenant_id)}>
            <Building2 size={15} aria-hidden="true" />
            <span>{w.business_name}</span>
            {current ? <Check size={14} aria-hidden="true" /> : busy === w.tenant_id ? <span className="apex-spinner" aria-hidden="true" /> : null}
          </button>
        );
      })}
      {failed && <p className="workspace-switcher__error" role="alert">{t('workspaces.switchFailed')}</p>}
      <button type="button" role="menuitem" onClick={() => { onDone?.(); navigate(routePaths.newWorkspace); }}>
        <Plus size={15} aria-hidden="true" /><span>{t('workspaces.new')}</span>
      </button>
    </div>
  );
}

export default WorkspaceSwitcher;
