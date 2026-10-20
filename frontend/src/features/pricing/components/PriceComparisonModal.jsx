import Modal from '../../../shared/components/ui/Modal.jsx';
import { ProductPriceLadder } from './ProductPriceLadder.jsx';

export function PriceComparisonModal({ open, product, onClose, t }) {
  if (!product) return null;
  return <Modal isOpen={open} onClose={onClose} title={t('pricing.ladder.modalTitle', { name: product.product_name })} closeLabel={t('common.close')} maxWidth="1040px">
    <ProductPriceLadder productId={product.product_id} />
  </Modal>;
}

export default PriceComparisonModal;
