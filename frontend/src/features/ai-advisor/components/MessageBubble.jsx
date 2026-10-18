import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function MessageBubble() {
  const { t: copyT } = useI18n();
  return <div className="message-bubble">{copyT("interfaceCopy.message")}</div>;
}
