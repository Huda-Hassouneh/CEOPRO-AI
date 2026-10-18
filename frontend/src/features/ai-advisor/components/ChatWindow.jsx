import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function ChatWindow() {
  const { t: copyT } = useI18n();
  return <div className="chat-window">{copyT("interfaceCopy.advisorChat")}</div>;
}
