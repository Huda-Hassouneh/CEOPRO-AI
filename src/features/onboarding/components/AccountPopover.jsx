import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { X } from 'lucide-react';
import Avatar from '../../../shared/components/ui/Avatar.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../../auth/store/authStore.js';
import { getAccountProfile } from '../utils/accountProfile.js';

export function AccountPopover() {
  const { t } = useI18n();
  const user = useAuthStore((state) => state.user);
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef(null);
  const triggerRef = useRef(null);
  const popoverRef = useRef(null);
  const closeRef = useRef(null);
  const popoverId = useId().replace(/:/g, '');
  const profile = useMemo(() => getAccountProfile(user, t), [t, user]);

  useEffect(() => {
    if (!open) return undefined;
    closeRef.current?.focus({ preventScroll: true });

    const handlePointerDown = (event) => {
      if (!wrapperRef.current?.contains(event.target)) setOpen(false);
    };
    const handleKeyDown = (event) => {
      if (event.key !== 'Escape') return;
      setOpen(false);
      triggerRef.current?.focus();
    };

    document.addEventListener('pointerdown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  return (
    <div className="ceopro-account" ref={wrapperRef}>
      <button
        ref={triggerRef}
        type="button"
        className="ceopro-account__trigger"
        aria-label={t('onboarding.account.open')}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? popoverId : undefined}
        onClick={() => setOpen((current) => !current)}
      >
        <Avatar src={profile.avatarUrl} alt={profile.personName} fallback={profile.initials} size="32px" />
      </button>
      {open && (
        <div
          ref={popoverRef}
          id={popoverId}
          className="ceopro-account-popover"
          role="dialog"
          aria-label={t('onboarding.account.title')}
          tabIndex="-1"
        >
          <button
            ref={closeRef}
            type="button"
            className="ceopro-account-popover__close"
            aria-label={t('onboarding.account.close')}
            onClick={() => { setOpen(false); triggerRef.current?.focus(); }}
          ><X size={14} /></button>
          <div className="ceopro-account-popover__person">
            <Avatar src={profile.avatarUrl} alt={profile.personName} fallback={profile.initials} size="38px" />
            <span><strong>{profile.personName}</strong><small>{profile.email}</small></span>
          </div>
          <div className="ceopro-account-popover__company">
            <small>{t('onboarding.account.company')}</small>
            <strong>{profile.companyName}</strong>
          </div>
        </div>
      )}
    </div>
  );
}
