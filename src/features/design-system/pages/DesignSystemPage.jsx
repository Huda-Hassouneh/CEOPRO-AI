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
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [toastMessage, setToastMessage] = useState(null);

  const products = [
    { name: 'COOLFLOW Pro', owner: 'Operations', channel: 'Retail', trend: '+12.5%', status: 'Healthy' },
    { name: 'Vector Skin Kit', owner: 'Beauty', channel: 'Marketplace', trend: '+8.7%', status: 'Growing' },
    { name: 'Nova Home Care', owner: 'Home', channel: 'Organic', trend: '-2.1%', status: 'Watch' },
  ];

  const tableColumns = [
    { header: 'Product Name', accessor: 'name' },
    { header: 'Owner', accessor: 'owner' },
    { header: 'Channel', accessor: 'channel' },
    { header: 'Trend', accessor: 'trend' },
    { 
      header: 'Status', 
      render: (row) => (
        <Badge variant={row.status === 'Healthy' ? 'success' : row.status === 'Watch' ? 'warning' : 'primary'}>
          {row.status}
        </Badge>
      ) 
    }
  ];

  const selectOptions = [
    { value: 'demand', label: 'Demand Planning' },
    { value: 'market', label: 'Market Intelligence' }
  ];

  const tabItems = [
    { id: 'demand', label: 'Demand', content: <p style={{ color: 'var(--ceopro-text-secondary)', fontSize: '14px' }}>Demand forecasting and insights content.</p> },
    { id: 'supply', label: 'Supply', content: <p style={{ color: 'var(--ceopro-text-secondary)', fontSize: '14px' }}>Supply chain and inventory metrics.</p> },
    { id: 'market', label: 'Market', content: <p style={{ color: 'var(--ceopro-text-secondary)', fontSize: '14px' }}>Competitor tracking and market analysis.</p> }
  ];

  const triggerButton = <Button variant="outline">Open Menu ▾</Button>;

  return (
    <div className="ceopro-design-system" style={{ padding: 'var(--ceopro-space-8)', maxWidth: '1200px', margin: '0 auto' }}>
      
      {toastMessage && (
        <div style={{ position: 'fixed', bottom: '24px', right: '24px', zIndex: 10000 }}>
          <Toast message={toastMessage} variant="success" onClose={() => setToastMessage(null)} />
        </div>
      )}

      <section className="ceopro-design-system-hero" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-8)' }}>
        <div>
          <span className="ceopro-kicker" style={{ fontSize: '12px', fontWeight: '700', color: 'var(--ceopro-primary)', textTransform: 'uppercase' }}>CEOPRO AI / Design System</span>
          <h1 className="ceopro-page-title" style={{ margin: 'var(--ceopro-space-2) 0' }}>Design System Playground</h1>
          <p className="ceopro-muted" style={{ color: 'var(--ceopro-text-secondary)', margin: 0 }}>Shared UI foundations for CEOPRO workflows.</p>
        </div>
        <div className="ceopro-hero-actions" style={{ display: 'flex', gap: 'var(--ceopro-space-3)' }}>
          <Button variant="secondary" onClick={() => setToastMessage('Export triggered successfully!')}>Export</Button>
          <Button variant="primary" onClick={() => setIsModalOpen(true)}>Create insight</Button>
        </div>
      </section>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(350px, 1fr))', gap: 'var(--ceopro-space-6)' }}>

        <Card className="ceopro-section-card">
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>Colors</h3>
            <Badge variant="neutral">Brand palette</Badge>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--ceopro-space-3)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}><span style={{ width: '24px', height: '24px', borderRadius: '4px', background: 'var(--ceopro-primary)', display: 'inline-block' }} /> CEOPRO Primary</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}><span style={{ width: '24px', height: '24px', borderRadius: '4px', background: 'var(--ceopro-primary-dark)', display: 'inline-block' }} /> CEOPRO Dark</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}><span style={{ width: '24px', height: '24px', borderRadius: '4px', background: 'var(--ceopro-surface-soft)', border: '1px solid var(--ceopro-border)', display: 'inline-block' }} /> Surface Soft</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}><span style={{ width: '24px', height: '24px', borderRadius: '4px', background: '#10b981', display: 'inline-block' }} /> Success</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}><span style={{ width: '24px', height: '24px', borderRadius: '4px', background: '#f59e0b', display: 'inline-block' }} /> Warning</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}><span style={{ width: '24px', height: '24px', borderRadius: '4px', background: '#ef4444', display: 'inline-block' }} /> Error</div>
          </div>
        </Card>

        <Card className="ceopro-section-card">
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>Typography</h3>
            <Badge variant="neutral">Text system</Badge>
          </div>
          <div className="ceopro-type-stack" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--ceopro-space-2)' }}>
            <h1 style={{ fontSize: '22px', margin: 0, fontWeight: '700' }}>Executive Overview</h1>
            <h2 style={{ fontSize: '18px', margin: 0, fontWeight: '600' }}>Quarterly Demand</h2>
            <h3 style={{ fontSize: '15px', margin: 0, fontWeight: '600' }}>Product Trend</h3>
            <p style={{ margin: 0, fontSize: '14px', color: 'var(--ceopro-text-primary)' }}>CEOPRO AI surfaces performance, demand, product, and competitive signals.</p>
            <p style={{ margin: 0, fontSize: '12px', color: 'var(--ceopro-text-muted)' }}>Meta label / supporting copy</p>
            <p lang="ar" dir="rtl" style={{ margin: '8px 0 0', fontSize: '14px', color: 'var(--ceopro-text-primary)', fontFamily: 'var(--ceopro-font-family-ar)' }}>
              رؤية الطلب والتنبؤ المؤسسي للمنتجات واحتياجات السوق.
            </p>
          </div>
        </Card>

        <Card className="ceopro-section-card">
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>Buttons</h3>
            <Badge variant="neutral">Actions</Badge>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--ceopro-space-3)' }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--ceopro-space-2)' }}>
              <Button>Primary</Button>
              <Button variant="secondary">Secondary</Button>
              <Button variant="outline">Outline</Button>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--ceopro-space-2)' }}>
              <Button disabled>Disabled</Button>
              <Button onClick={() => setToastMessage('Icon action clicked!')}>✦ Icon action</Button>
            </div>
          </div>
        </Card>

        <Card className="ceopro-section-card">
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>Form controls</h3>
            <Badge variant="neutral">Input</Badge>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--ceopro-space-2)' }}>
            <Input label="Search forecast" placeholder="e.g. skincare" />
            <Input label="Password" type="password" placeholder="••••••••" />
            <Select label="Category" options={selectOptions} />
          </div>
        </Card>

        <Card className="ceopro-section-card">
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>Badges / Status</h3>
            <Badge variant="neutral">Signals</Badge>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--ceopro-space-3)' }}>
            <Badge variant="success">Healthy</Badge>
            <Badge variant="warning">Watch</Badge>
            <Badge variant="error">Risk</Badge>
            <Badge variant="primary">Synced</Badge>
          </div>
        </Card>

        <Card className="ceopro-section-card">
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>Avatar</h3>
            <Badge variant="neutral">Owners</Badge>
          </div>
          <div style={{ display: 'flex', gap: 'var(--ceopro-space-4)', alignItems: 'center' }}>
            <Avatar alt="Ahmed" size="40px" />
            <Avatar alt="Mona Raed" size="40px" />
            <Avatar alt="Operations Team" size="40px" />
          </div>
        </Card>

        <Card className="ceopro-section-card" style={{ gridColumn: '1 / -1' }}>
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>Tabs</h3>
            <Badge variant="neutral">Views</Badge>
          </div>
          <Tabs tabs={tabItems} />
        </Card>

        <Card className="ceopro-section-card" style={{ gridColumn: '1 / -1' }}>
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>Table</h3>
            <Badge variant="neutral">SKU View</Badge>
          </div>
          <Table columns={tableColumns} data={products} />
        </Card>

        <Card className="ceopro-section-card">
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>Feedback & Tooltip</h3>
            <Badge variant="neutral">Feedback</Badge>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--ceopro-space-4)' }}>
            <Toast message="Demand signal changed by +12%" variant="success" />
            <Tooltip content="AI recommendation confidence 94%">
              <span style={{ display: 'inline-block', padding: '8px 12px', background: 'var(--ceopro-surface-soft)', borderRadius: '6px', fontSize: '14px', cursor: 'pointer' }}>
                Hover for Tooltip Confidence
              </span>
            </Tooltip>
          </div>
        </Card>

        <Card className="ceopro-section-card">
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>States & Modals</h3>
            <Badge variant="neutral">States</Badge>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--ceopro-space-4)' }}>
            <Skeleton width="100%" height="16px" />
            <EmptyState title="No competitive data" description="Connect a channel to start monitoring market signals." />
          </div>
        </Card>

        <Card className="ceopro-section-card">
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>Dropdown</h3>
            <Badge variant="neutral">Menu</Badge>
          </div>
          <Dropdown trigger={triggerButton}>
            <button onClick={() => setToastMessage('View details clicked')}>View details</button>
            <button onClick={() => setToastMessage('Settings clicked')}>Settings</button>
            <button onClick={() => setToastMessage('Export clicked')}>Export report</button>
          </Dropdown>
        </Card>

        <Card className="ceopro-section-card">
          <div className="ceopro-section-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--ceopro-space-4)' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700' }}>Stepper</h3>
            <Badge variant="neutral">Onboarding</Badge>
          </div>
          <Stepper steps={['Industry', 'Workspace', 'Integration']} currentStep={2} />
        </Card>

      </div>

      <Modal 
        isOpen={isModalOpen} 
        onClose={() => setIsModalOpen(false)} 
        title="Scenario Planner & Insights"
        footer={
          <>
            <Button variant="outline" onClick={() => setIsModalOpen(false)}>Cancel</Button>
            <Button onClick={() => { setIsModalOpen(false); setToastMessage('New insight generated successfully!'); }}>Generate</Button>
          </>
        }
      >
        <p style={{ color: 'var(--ceopro-text-secondary)', fontSize: '14px', lineHeight: '1.5' }}>
          Configure scenario variables to run simulations and generate predictive market intelligence reports directly through the CEOPRO workspace engine.
        </p>
        <Input label="Scenario Name" placeholder="e.g. Q4 European Expansion" />
      </Modal>

    </div>
  );
}