import { AlertTriangle, CheckCircle2 } from 'lucide-react';
import Modal from '../../../shared/components/ui/Modal.jsx';
import Button from '../../../shared/components/ui/Button.jsx';

export function CompetitorConfirmation({ open, t, locale, name, message, destructive = false, busy, error, onCancel, onConfirm }) {
  return <Modal isOpen={open} onClose={() => { if (!busy) onCancel(); }}
    title={t(destructive ? 'competitorManagement.untrack' : 'competitorManagement.status')}
    closeLabel={t('common.cancel')} dir={locale === 'ar' ? 'rtl' : 'ltr'}
    className="competitor-confirmation" maxWidth="460px"
    footer={<><Button variant="outline" disabled={busy} onClick={onCancel}>{t('common.cancel')}</Button>
      <Button className={destructive ? 'competitor-button--danger' : ''} disabled={busy} onClick={onConfirm}>{t(busy ? 'competitorManagement.saving' : 'common.confirm')}</Button></>}>
    <div className={`competitor-confirmation__icon ${destructive ? 'is-danger' : ''}`} aria-hidden="true">
      {destructive ? <AlertTriangle size={25} /> : <CheckCircle2 size={25} />}
    </div>
    {name && <strong className="competitor-confirmation__name">{name}</strong>}
    <p className="competitor-confirmation__message">{message}</p>
    {error && <p className="competitor-feedback competitor-feedback--error" role="alert">{error}</p>}
  </Modal>;
}
