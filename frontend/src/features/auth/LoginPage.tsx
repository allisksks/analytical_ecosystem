import { BarChart3, ShieldCheck } from "lucide-react";
import QRCode from "qrcode";
import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router";
import { api, ApiError } from "../../shared/api/client";
import { useI18n } from "../../shared/i18n";
import { Button, ErrorBox, Field, Input } from "../../shared/ui";
import { useAuth, type MfaChallenge } from "./AuthProvider";
import s from "./LoginPage.module.css";

export function LoginPage() {
  const { t } = useI18n();
  const { status, login, verifyMfa } = useAuth();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [mfa, setMfa] = useState<MfaChallenge | null>(null);
  const [setup, setSetup] = useState<{ secret: string; qr: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!mfa?.setupRequired || setup) return;
    api
      .POST("/api/v1/auth/mfa/setup", { body: { mfa_token: mfa.token } })
      .then(async ({ data }) => {
        if (data)
          setSetup({ secret: data.secret, qr: await QRCode.toDataURL(data.otpauth_uri, { margin: 1, width: 180 }) });
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [mfa, setup]);

  if (status === "authenticated") {
    const from = (location.state as { from?: string } | null)?.from ?? "/";
    return <Navigate to={from} replace />;
  }

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError || e instanceof Error ? e.message : t("common.error"));
    } finally {
      setBusy(false);
    }
  };

  const onLogin = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => setMfa(await login(email, password)));
  };
  const onMfa = (e: FormEvent) => {
    e.preventDefault();
    if (mfa) void run(() => verifyMfa(mfa.token, code));
  };

  return (
    <div className={s.page}>
      <div className={s.panel}>
        <div className={s.brand}>
          <span className={s.mark}>
            <BarChart3 size={22} />
          </span>
          <span>{t("app.name")}</span>
        </div>
        {!mfa ? (
          <form onSubmit={onLogin} className={s.form} noValidate>
            <h1 className={s.title}>{t("auth.title")}</h1>
            <p className={s.sub}>{t("auth.subtitle")}</p>
            {error && <ErrorBox>{error}</ErrorBox>}
            <Field label={t("auth.email")}>
              <Input
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
              />
            </Field>
            <Field label={t("auth.password")}>
              <Input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </Field>
            <Button type="submit" variant="primary" block loading={busy} disabled={!email || !password}>
              {t("auth.signIn")}
            </Button>
          </form>
        ) : (
          <form onSubmit={onMfa} className={s.form}>
            <h1 className={s.title}>
              <ShieldCheck size={22} /> {mfa.setupRequired ? t("auth.mfaSetupTitle") : t("auth.mfaTitle")}
            </h1>
            <p className={s.sub}>{mfa.setupRequired ? t("auth.mfaSetupHint") : t("auth.mfaHint")}</p>
            {error && <ErrorBox>{error}</ErrorBox>}
            {mfa.setupRequired && setup && (
              <div className={s.qr}>
                <img src={setup.qr} alt="QR" width={180} height={180} />
                <div>
                  <div className={s.secretLabel}>{t("auth.mfaSecret")}</div>
                  <code className={s.secret}>{setup.secret}</code>
                </div>
              </div>
            )}
            <Field label={t("auth.mfaCode")}>
              <Input
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9 ]*"
                maxLength={8}
                value={code}
                onChange={(e) => setCode(e.target.value)}
                autoFocus
                mono
              />
            </Field>
            <Button type="submit" variant="primary" block loading={busy} disabled={code.replace(/\D/g, "").length < 6}>
              {t("auth.confirm")}
            </Button>
            <Button
              variant="ghost"
              block
              onClick={() => {
                setMfa(null);
                setSetup(null);
                setCode("");
              }}
            >
              {t("auth.back")}
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}
