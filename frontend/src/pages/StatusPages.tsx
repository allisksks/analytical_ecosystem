import { Compass, Hammer } from "lucide-react";
import { Link } from "react-router";
import { PageBody } from "../layout/AppShell";
import { useI18n, type TKey } from "../shared/i18n";
import { Button, Card, EmptyState, PageHeader } from "../shared/ui";

export function ComingSoonPage({ titleKey }: { titleKey: TKey }) {
  const { t } = useI18n();
  return (
    <PageBody>
      <PageHeader title={t(titleKey)} />
      <Card>
        <EmptyState icon={<Hammer size={26} />} title={t("common.comingSoon")} />
      </Card>
    </PageBody>
  );
}

export function NotFoundPage() {
  const { t } = useI18n();
  return (
    <PageBody>
      <Card>
        <EmptyState
          icon={<Compass size={26} />}
          title={t("common.notFound")}
          action={
            <Link to="/">
              <Button variant="primary">{t("common.backHome")}</Button>
            </Link>
          }
        />
      </Card>
    </PageBody>
  );
}
