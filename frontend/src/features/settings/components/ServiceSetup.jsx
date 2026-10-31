import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ApexButton, Pill, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import { operatorApi } from '../api/operatorApi.js';
import { SettingsSection } from './SettingsSection.jsx';

const RESULT_TONE = { valid: 'success', valid_restricted: 'success', rejected: 'danger', quota_exhausted: 'warning', model_unavailable: 'warning' };

function ProviderRow({ row, t }) {
  const [result, setResult] = useState(null);
  const test = useMutation({ mutationFn: () => operatorApi.test(row.provider), onSuccess: setResult, onError: () => setResult('error') });
  return (
    <li className="service-setup__row">
      <div>
        <strong>{row.label}</strong> <Pill tone={row.configured ? 'success' : 'warning'}>{t(row.configured ? 'settings.service.configured' : 'settings.service.notConfigured')}</Pill>
        <p className="apex-muted">{t('settings.service.unlocks')}: {row.unlocks}</p>
        <p className="apex-muted">{t('settings.service.variable')}: <code>{row.env.join(' / ')}</code></p>
        <p className="apex-muted">{t('settings.service.cost')}: {row.cost}</p>
        {row.recent_problem && <p><Pill tone="danger">{t('settings.service.recent', { problem: t(`settings.service.problem.${row.recent_problem.code}`) })}</Pill></p>}
        {result && <p role="status"><Pill tone={RESULT_TONE[result] || 'neutral'}>{t(`settings.service.result.${result}`)}</Pill></p>}
      </div>
      <ApexButton size="sm" variant="secondary" loading={test.isPending} disabled={!row.configured} onClick={() => { setResult(null); test.mutate(); }}>
        {test.isPending ? t('settings.service.testing') : t('settings.service.test')}
      </ApexButton>
    </li>
  );
}

// Operator-only. Read-only status of the provider keys held in the environment, plus a one-call connection test.
export function ServiceSetup({ t }) {
  const query = useQuery({ queryKey: ['operator-providers'], queryFn: operatorApi.providers });
  return (
    <SettingsSection title={t('settings.service.title')} subtitle={t('settings.service.subtitle')}>
      {query.isError ? <StateBlock kind="error" compact title={t('settings.service.loadFailed')} onRetry={() => query.refetch()} />
        : <ul className="service-setup">{(query.data || []).map((row) => <ProviderRow key={row.provider} row={row} t={t} />)}</ul>}
    </SettingsSection>
  );
}
