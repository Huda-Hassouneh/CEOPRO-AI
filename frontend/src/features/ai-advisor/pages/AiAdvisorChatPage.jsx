import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { DashboardLayout } from '../../../app/layouts/DashboardLayout.jsx';

export function AiAdvisorChatPage() {
  const { t: copyT } = useI18n();
  return (
    <DashboardLayout>
      <div>{copyT("interfaceCopy.aiAdvisorChat")}</div>
    </DashboardLayout>
  );
}
