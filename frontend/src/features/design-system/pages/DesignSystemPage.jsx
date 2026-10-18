import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import Card from '../../../shared/components/ui/Card.jsx';
import Badge from '../../../shared/components/ui/Badge.jsx';
import Avatar from '../../../shared/components/ui/Avatar.jsx';
import Dropdown from '../../../shared/components/ui/Dropdown.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Modal from '../../../shared/components/ui/Modal.jsx';
import Select from '../../../shared/components/ui/Select.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import Stepper from '../../../shared/components/ui/Stepper.jsx';
import Table from '../../../shared/components/ui/Table.jsx';
import Tabs from '../../../shared/components/ui/Tabs.jsx';
import Toast from '../../../shared/components/ui/Toast.jsx';
import Tooltip from '../../../shared/components/ui/Tooltip.jsx';
import React, { useState } from 'react';

export default function DesignSystemPage() {
  const { t: copyT } = useI18n();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [toastMessage, setToastMessage] = useState(null);

  const products = [
    { name: 'COOLFLOW Pro', owner: copyT("interfaceCopy.operations"), channel: copyT("interfaceCopy.retail"), trend: '+12.5%', status: 'Healthy' },
    { name: 'Vector Skin Kit', owner: copyT("interfaceCopy.beauty"), channel: copyT("interfaceCopy.marketplace"), trend: '+8.7%', status: 'Growing' },
    { name: 'Nova Home Care', owner: copyT("interfaceCopy.home"), channel: copyT("interfaceCopy.organic"), trend: '-2.1%', status: 'Watch' },
  ];

  const tableColumns = [
    { header: copyT("interfaceCopy.productName"), accessor: 'name' },
    { header: copyT("interfaceCopy.owner"), accessor: 'owner' },
    { header: copyT("interfaceCopy.channel"), accessor: 'channel' },
    { header: copyT("interfaceCopy.trend"), accessor: 'trend' },
    { 
      header: copyT("interfaceCopy.status"), 
      render: (row) => (
        <Badge variant={row.status === 'Healthy' ? 'success' : row.status === 'Watch' ? 'warning' : 'primary'}>
          {copyT({ Healthy: "interfaceCopy.healthy", Growing: "interfaceCopy.growing", Watch: "interfaceCopy.watch" }[row.status])}
        </Badge>
      ) 
    }
  ];

  const selectOptions = [
    { value: 'demand', label: copyT("interfaceCopy.demandPlanning") },
    { value: 'market', label: copyT("interfaceCopy.marketIntelligence") }
  ];

  const tabItems = [
    { id: 'demand', label: copyT("interfaceCopy.demand"), content: <p style={{ color: 'var(--ceopro-text-secondary)', fontSize: '14px' }}>{copyT("interfaceCopy.demandForecastingAndInsightsContent")}</p> },
    { id: 'supply', label: copyT("interfaceCopy.supply"), content: <p style={{ color: 'var(--ceopro-text-secondary)', fontSize: '14px' }}>{copyT("interfaceCopy.supplyChainAndInventoryMetrics")}</p> },
    { id: 'market', label: copyT("interfaceCopy.market"), content: <p style={{ color: 'var(--ceopro-text-secondary)', fontSize: '14px' }}>{copyT("interfaceCopy.competitorTrackingAndMarketAnalysis")}</p> }
  ];

  const triggerButton = <Button variant="outline">{copyT("interfaceCopy.openMenu")}</Button>;

  return (
    <div className="ceopro-design-system" style={{ padding: 'var(--ceopro-space-8)', maxWidth: '1200px', margin: '0 auto' }}>
      
      {toastMessage && (
        <div style={{ position: 'fixed', bottom: '24px', right: '24px', zIndex: 10000 }}>
          <Toast message={toastMessage} variant="success" onClose={() => setToastMessage(null)} />
        </div>
      )}

      <section className="ceopro-design-system-hero" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-8)' }}>
        <div>
          <span className="ceopro-kicker" style={{ fontSize: '12px', fontWeight: '700', color: 'var(--ceopro-primary)', textTransform: 'uppercase' }}>{copyT("interfaceCopy.keelDesignSystem")}</span>
          <h1 className="ceopro-page-title" style={{ margin: 'var(--ceopro-space-2) 0' }}>{copyT("interfaceCopy.designSystemPlayground")}</h1>
          <p className="ceopro-muted" style={{ color: 'var(--ceopro-text-secondary)', margin: 0 }}>{copyT("interfaceCopy.sharedUiFoundationsForKeelWorkflows")}</p>
        </div>
        <div className="ceopro-hero-actions" style={{ display: 'flex', gap: 'var(--ceopro-space-3)' }}>
          <Button variant="secondary" onClick={() => setToastMessage('Export triggered successfully!')}>{copyT("interfaceCopy.export")}</Button>
          <Button variant="primary" onClick={() => setIsModalOpen(true)}>{copyT("interfaceCopy.createInsight")}</Button>
        </div>
      </section>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(350px, 1fr))', gap: 'var(--ceopro-space-6)' }}>

        <Card className="ceopro-section-card">
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>{copyT("interfaceCopy.colors")}</h3>
            <Badge variant="neutral">{copyT("interfaceCopy.brandPalette")}</Badge>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--ceopro-space-3)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}><span style={{ width: '24px', height: '24px', borderRadius: '4px', background: 'var(--ceopro-primary)', display: 'inline-block' }} />{copyT("interfaceCopy.keelPrimary")}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}><span style={{ width: '24px', height: '24px', borderRadius: '4px', background: 'var(--ceopro-primary-dark)', display: 'inline-block' }} />{copyT("interfaceCopy.keelDark")}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}><span style={{ width: '24px', height: '24px', borderRadius: '4px', background: 'var(--ceopro-surface-soft)', border: '1px solid var(--ceopro-border)', display: 'inline-block' }} />{copyT("interfaceCopy.surfaceSoft")}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}><span style={{ width: '24px', height: '24px', borderRadius: '4px', background: '#10b981', display: 'inline-block' }} />{copyT("interfaceCopy.success")}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}><span style={{ width: '24px', height: '24px', borderRadius: '4px', background: '#f59e0b', display: 'inline-block' }} />{copyT("interfaceCopy.warning")}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}><span style={{ width: '24px', height: '24px', borderRadius: '4px', background: '#ef4444', display: 'inline-block' }} />{copyT("interfaceCopy.error")}</div>
          </div>
        </Card>

        <Card className="ceopro-section-card">
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>{copyT("interfaceCopy.typography")}</h3>
            <Badge variant="neutral">{copyT("interfaceCopy.textSystem")}</Badge>
          </div>
          <div className="ceopro-type-stack" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--ceopro-space-2)' }}>
            <h1 style={{ fontSize: '22px', margin: 0, fontWeight: '700' }}>{copyT("interfaceCopy.executiveOverview")}</h1>
            <h2 style={{ fontSize: '18px', margin: 0, fontWeight: '600' }}>{copyT("interfaceCopy.quarterlyDemand")}</h2>
            <h3 style={{ fontSize: '15px', margin: 0, fontWeight: '600' }}>{copyT("interfaceCopy.productTrend")}</h3>
            <p style={{ margin: 0, fontSize: '14px', color: 'var(--ceopro-text-primary)' }}>{copyT("interfaceCopy.keelSurfacesPerformanceDemandProductAndCompetitiveSignals")}</p>
            <p style={{ margin: 0, fontSize: '12px', color: 'var(--ceopro-text-muted)' }}>{copyT("interfaceCopy.metaLabelSupportingCopy")}</p>
            <p lang="ar" dir="rtl" style={{ margin: '8px 0 0', fontSize: '14px', color: 'var(--ceopro-text-primary)', fontFamily: 'var(--ceopro-font-family-ar)' }}>
              {copyT("interfaceCopy.arabicTypographySample")}
            </p>
          </div>
        </Card>

        <Card className="ceopro-section-card">
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>{copyT("interfaceCopy.buttons")}</h3>
            <Badge variant="neutral">{copyT("interfaceCopy.actions")}</Badge>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--ceopro-space-3)' }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--ceopro-space-2)' }}>
              <Button>{copyT("interfaceCopy.primary")}</Button>
              <Button variant="secondary">{copyT("interfaceCopy.secondary")}</Button>
              <Button variant="outline">{copyT("interfaceCopy.outline")}</Button>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--ceopro-space-2)' }}>
              <Button disabled>{copyT("common.disabled")}</Button>
              <Button onClick={() => setToastMessage('Icon action clicked!')}>{copyT("interfaceCopy.iconAction")}</Button>
            </div>
          </div>
        </Card>

        <Card className="ceopro-section-card">
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>{copyT("interfaceCopy.formControls")}</h3>
            <Badge variant="neutral">{copyT("interfaceCopy.input")}</Badge>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--ceopro-space-2)' }}>
            <Input label={copyT("interfaceCopy.searchForecast")} placeholder={copyT("interfaceCopy.eGSkincare")} />
            <Input label={copyT("interfaceCopy.password")} type="password" placeholder="••••••••" />
            <Select label={copyT("interfaceCopy.category")} options={selectOptions} />
          </div>
        </Card>

        <Card className="ceopro-section-card">
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>{copyT("interfaceCopy.badgesStatus")}</h3>
            <Badge variant="neutral">{copyT("interfaceCopy.signals")}</Badge>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--ceopro-space-3)' }}>
            <Badge variant="success">{copyT("interfaceCopy.healthy")}</Badge>
            <Badge variant="warning">{copyT("interfaceCopy.watch")}</Badge>
            <Badge variant="error">{copyT("interfaceCopy.risk")}</Badge>
            <Badge variant="primary">{copyT("interfaceCopy.synced")}</Badge>
          </div>
        </Card>

        <Card className="ceopro-section-card">
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>{copyT("interfaceCopy.avatar")}</h3>
            <Badge variant="neutral">{copyT("interfaceCopy.owners")}</Badge>
          </div>
          <div style={{ display: 'flex', gap: 'var(--ceopro-space-4)', alignItems: 'center' }}>
            <Avatar alt={copyT("interfaceCopy.ahmed")} size="40px" />
            <Avatar alt={copyT("interfaceCopy.monaRaed")} size="40px" />
            <Avatar alt={copyT("interfaceCopy.operationsTeam")} size="40px" />
          </div>
        </Card>

        <Card className="ceopro-section-card" style={{ gridColumn: '1 / -1' }}>
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>{copyT("interfaceCopy.tabs")}</h3>
            <Badge variant="neutral">{copyT("interfaceCopy.views")}</Badge>
          </div>
          <Tabs tabs={tabItems} />
        </Card>

        <Card className="ceopro-section-card" style={{ gridColumn: '1 / -1' }}>
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>{copyT("interfaceCopy.table")}</h3>
            <Badge variant="neutral">{copyT("interfaceCopy.skuView")}</Badge>
          </div>
          <Table columns={tableColumns} data={products} />
        </Card>

        <Card className="ceopro-section-card">
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>{copyT("interfaceCopy.feedbackTooltip")}</h3>
            <Badge variant="neutral">{copyT("interfaceCopy.feedback")}</Badge>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--ceopro-space-4)' }}>
            <Toast message={copyT("interfaceCopy.demandSignalChangedBy12")} variant="success" />
            <Tooltip content="AI recommendation confidence 94%">
              <span style={{ display: 'inline-block', padding: '8px 12px', background: 'var(--ceopro-surface-soft)', borderRadius: '6px', fontSize: '14px', cursor: 'pointer' }}>{copyT("interfaceCopy.hoverForTooltipConfidence")}</span>
            </Tooltip>
          </div>
        </Card>

        <Card className="ceopro-section-card">
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>{copyT("interfaceCopy.statesModals")}</h3>
            <Badge variant="neutral">{copyT("interfaceCopy.states")}</Badge>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--ceopro-space-4)' }}>
            <Skeleton width="100%" height="16px" />
            <EmptyState title={copyT("interfaceCopy.noCompetitiveData")} description={copyT("interfaceCopy.connectAChannelToStartMonitoringMarketSignals")} />
          </div>
        </Card>

        <Card className="ceopro-section-card">
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>{copyT("interfaceCopy.dropdown")}</h3>
            <Badge variant="neutral">{copyT("interfaceCopy.menu")}</Badge>
          </div>
          <Dropdown trigger={triggerButton}>
            <button onClick={() => setToastMessage('View details clicked')}>{copyT("interfaceCopy.viewDetails")}</button>
            <button onClick={() => setToastMessage('Settings clicked')}>{copyT("interfaceCopy.settings")}</button>
            <button onClick={() => setToastMessage('Export clicked')}>{copyT("interfaceCopy.exportReport")}</button>
          </Dropdown>
        </Card>

        <Card className="ceopro-section-card">
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>{copyT("interfaceCopy.stepper")}</h3>
            <Badge variant="neutral">{copyT("interfaceCopy.onboarding")}</Badge>
          </div>
          <Stepper steps={['Industry', 'Workspace', 'Integration']} currentStep={2} />
        </Card>

      </div>

      <Modal 
        isOpen={isModalOpen} 
        onClose={() => setIsModalOpen(false)} 
        title={copyT("interfaceCopy.scenarioPlannerInsights")}
        footer={
          <>
            <Button variant="outline" onClick={() => setIsModalOpen(false)}>{copyT("common.cancel")}</Button>
            <Button onClick={() => { setIsModalOpen(false); setToastMessage('New insight generated successfully!'); }}>{copyT("interfaceCopy.generate")}</Button>
          </>
        }
      >
        <p style={{ color: 'var(--ceopro-text-secondary)', fontSize: '14px', lineHeight: '1.5' }}>{copyT("interfaceCopy.configureScenarioVariablesToRunSimulationsAndGeneratePredictiveMarketIntelligenceReportsDirectlyThroughTheKeelWorkspaceEngine")}</p>
        <Input label={copyT("interfaceCopy.scenarioName")} placeholder={copyT("interfaceCopy.eGQ4EuropeanExpansion")} />
      </Modal>

    </div>
  );
}