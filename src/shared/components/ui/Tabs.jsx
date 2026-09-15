import React, { useState, useId } from 'react';

export default function Tabs({ 
  tabs = [], 
  activeTab,
  onChange,
  ariaLabel = 'Tabs',
  className = '',
  ...props 
}) {
  const [internalTab, setInternalTab] = useState(tabs[0]?.id);
  const currentTab = activeTab !== undefined ? activeTab : internalTab;
  const tabRootId = useId().replace(/:/g, '');

  const handleTabClick = (id) => {
    if (activeTab === undefined) {
      setInternalTab(id);
    }
    if (onChange) {
      onChange(id);
    }
  };

  const containerStyle = {
    display: 'flex',
    borderBottom: '1px solid var(--ceopro-border)',
    fontFamily: 'var(--ceopro-font-family)',
    gap: 'var(--ceopro-space-6)',
    ...props.style
  };

  return (
    <div className={`ceopro-tabs-container ${className}`.trim()} {...props}>
      <div role="tablist" style={containerStyle} aria-label={ariaLabel}>
        {tabs.map((tab, index) => {
          const isActive = currentTab === tab.id;
          const tabPanelId = `${tabRootId}-panel-${tab.id}`;
          const tabButtonId = `${tabRootId}-tab-${tab.id}`;
          const tabStyle = {
            padding: 'var(--ceopro-space-3) 0',
            background: 'transparent',
            border: 'none',
            borderBottom: isActive ? '2px solid var(--ceopro-primary)' : '2px solid transparent',
            marginBottom: '-1px',
            color: isActive ? 'var(--ceopro-primary)' : 'var(--ceopro-text-secondary)',
            fontWeight: isActive ? '700' : '500',
            fontSize: '14px',
            cursor: tab.disabled ? 'not-allowed' : 'pointer',
            opacity: tab.disabled ? 0.5 : 1,
            transition: 'color 150ms ease, border-color 150ms ease',
          };

          return (
            <button
              key={tab.id}
              id={tabButtonId}
              role="tab"
              type="button"
              aria-controls={tabPanelId}
              aria-selected={isActive}
              aria-disabled={tab.disabled || undefined}
              tabIndex={isActive ? 0 : -1}
              style={tabStyle}
              onClick={() => !tab.disabled && handleTabClick(tab.id)}
              onKeyDown={(event) => {
                if (tab.disabled) return;

                const enabled = tabs.filter((item) => !item.disabled);
                const currentIndex = enabled.findIndex((item) => item.id === tab.id);
                const rtl = getComputedStyle(event.currentTarget).direction === 'rtl';
                let nextIndex;
                if (event.key === 'Home') nextIndex = 0;
                else if (event.key === 'End') nextIndex = enabled.length - 1;
                else if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
                  const step = (event.key === 'ArrowRight' ? 1 : -1) * (rtl ? -1 : 1);
                  nextIndex = (currentIndex + step + enabled.length) % enabled.length;
                } else return;
                event.preventDefault();
                const nextTab = enabled[nextIndex];
                handleTabClick(nextTab.id);
                document.getElementById(`${tabRootId}-tab-${nextTab.id}`)?.focus();
              }}
              disabled={tab.disabled}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
      <div id={`${tabRootId}-panel-${currentTab}`} role="tabpanel" style={{ marginTop: 'var(--ceopro-space-4)' }} aria-labelledby={`${tabRootId}-tab-${currentTab}`}>
        {tabs.find((tab) => tab.id === currentTab)?.content}
      </div>
    </div>
  );
}
