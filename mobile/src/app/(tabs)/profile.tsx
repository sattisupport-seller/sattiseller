import Constants from 'expo-constants';
import { useRouter } from 'expo-router';
import { LogOut, Sun } from 'lucide-react-native';
import { useState, type ReactNode } from 'react';
import { Linking, Pressable, ScrollView, View } from 'react-native';

import { useAIConsent, useAIQuota, useAppConfig, useResetDemo } from '@/api/hooks';
import { Button } from '@/components/ui/Button';
import { TabHeader } from '@/components/ui/Header';
import { Txt } from '@/components/ui/Text';
import { Badge, GroupCard, ListRow, Section, Card } from '@/components/ui/Surfaces';
import { Sheet, useToast } from '@/components/ui/Overlays';
import { useSession, type Locale, type ThemeMode } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';
import { SUPPORT_EMAIL } from '@/config';
import { downloadAndShare } from '@/lib/download';

// Профиль (docs/design.md, 12.16): аккаунт или демо, магазин, данные, настройки, помощь, выход.
export default function ProfileScreen() {
  const { t } = useI18n();
  const { colors, spacing } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const { isDemo, email, locale, themeMode, setLocale, setThemeMode, logout, shopId } = useSession();
  const config = useAppConfig();
  const quota = useAIQuota(shopId);
  const consent = useAIConsent();
  const reset = useResetDemo();
  const [langOpen, setLangOpen] = useState(false);
  const [themeOpen, setThemeOpen] = useState(false);
  const [logoutOpen, setLogoutOpen] = useState(false);
  const version = (Constants.expoConfig?.version as string | undefined) ?? '1.0.0';
  const build = String(Constants.expoConfig?.ios?.buildNumber ?? Constants.expoConfig?.android?.versionCode ?? '1');
  const initials = (email ?? 'Satti').slice(0, 2).toUpperCase();
  const themeLabel = themeMode === 'system' ? t('settings.system') : themeMode === 'light' ? t('settings.light') : t('settings.dark');
  const langLabel = locale === 'kk' ? t('settings.kk') : t('settings.ru');
  const aiOn = quota.data?.consent_active ?? false;
  const assistantOn = config.data?.flags.ai_assistant === true;

  return (
    <ScrollView contentContainerStyle={{ paddingHorizontal: spacing.lg, paddingBottom: 120, paddingTop: spacing.sm }} style={{ backgroundColor: colors.bg }} showsVerticalScrollIndicator={false}>
      <TabHeader title={t('profile.title')} />

      {isDemo ? (
        <Card style={{ gap: spacing.md }}>
          <Txt variant="headline">{t('profile.demoCard')}</Txt>
          <Txt variant="subhead" tone="secondary">{t('profile.demoCardHint')}</Txt>
          <View style={{ flexDirection: 'row', gap: spacing.sm }}>
            <Button title={t('profile.createAccount')} size="M" onPress={() => router.push('/login')} />
            <Button title={t('profile.resetDemo')} size="M" variant="secondary" loading={reset.isPending} onPress={() => reset.mutate(undefined, { onSuccess: () => toast.show(t('common.done')) })} />
          </View>
        </Card>
      ) : (
        <Card style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.md }}>
          <View style={{ width: 48, height: 48, borderRadius: 24, backgroundColor: colors.primarySoft, alignItems: 'center', justifyContent: 'center' }}>
            <Txt variant="headline" tone="primaryText">{initials}</Txt>
          </View>
          <View style={{ flex: 1 }}>
            <Txt variant="headline">{email ?? ''}</Txt>
          </View>
        </Card>
      )}

      <Section title={t('profile.shop')}>
        <GroupCard>
          <ListRow title={t('profile.shop')} onPress={() => undefined} right={<Txt variant="subhead" tone="tertiary">{isDemo ? t('overview.demo') : ''}</Txt>} />
          <ListRow
            title={t('profile.kaspi')}
            onPress={() => router.push('/settings/kaspi')}
            right={<Badge label={t('profile.soon')} tone="neutral" />}
            last
          />
        </GroupCard>
      </Section>

      <Section title={t('profile.data')}>
        <GroupCard>
          <ListRow title={t('profile.importCosts')} onPress={() => router.push('/import')} />
          <ListRow title={t('profile.commissions')} onPress={() => router.push('/settings/commissions')} />
          <ListRow title={t('profile.tax')} onPress={() => router.push('/settings/tax')} />
          <ListRow title={t('profile.expenses')} onPress={() => router.push('/settings/expenses')} />
          <ListRow
            title={t('profile.exportData')}
            onPress={() => {
              downloadAndShare('/me/export', 'satti-moi-dannye.zip', 'application/zip')
                .catch(() => toast.show(t('common.unknownError')));
            }}
            last
          />
        </GroupCard>
      </Section>

      <Section title={t('profile.settings')}>
        <GroupCard>
          <ListRow title={t('profile.language')} right={<Txt variant="subhead" tone="tertiary">{langLabel}</Txt>} onPress={() => setLangOpen(true)} />
          <ListRow title={t('profile.theme')} right={<Txt variant="subhead" tone="tertiary">{themeLabel}</Txt>} onPress={() => setThemeOpen(true)} />
          <ListRow title={t('profile.notifications')} onPress={() => router.push('/settings/notifications')} />
          {assistantOn ? (
            <ListRow
              title={t('profile.aiAccess')}
              right={<Txt variant="subhead" tone={aiOn ? 'tertiary' : 'danger'}>{aiOn ? t('profile.valueOn') : t('profile.valueOff')}</Txt>}
              onPress={() => {
                if (aiOn) consent.mutate(false);
                else consent.mutate(true);
              }}
              last
            />
          ) : null}
        </GroupCard>
      </Section>

      <Section title={t('profile.help')}>
        <GroupCard>
          <ListRow title={t('profile.howProfit')} onPress={() => router.push('/settings/how-profit')} />
          <ListRow title={t('profile.support')} onPress={() => Linking.openURL(`mailto:${SUPPORT_EMAIL}`)} />
          <ListRow title={t('profile.privacy')} onPress={() => config.data && Linking.openURL(config.data.privacy_url)} />
          <ListRow title={t('profile.terms')} onPress={() => config.data && Linking.openURL(config.data.terms_url)} last />
        </GroupCard>
      </Section>

      <View style={{ marginTop: spacing['2xl'], gap: spacing.sm }}>
        {!isDemo ? (
          <>
            <Button title={t('profile.logout')} variant="outline" fullWidth onPress={() => setLogoutOpen(true)} icon={<LogOut size={20} color={colors.textPrimary} />} />
            <Button title={t('profile.deleteAccount')} variant="destructiveText" fullWidth onPress={() => router.push('/settings/delete-account')} />
          </>
        ) : null}
      </View>

      <Pressable
        accessibilityRole="button"
        onLongPress={() => (__DEV__ ? router.push('/catalog') : undefined)}
        style={{ marginTop: spacing.xl, alignItems: 'center', gap: 4 }}
      >
        <Txt variant="footnote" tone="tertiary" align="center">{t('profile.version', { version, build })}</Txt>
        <Txt variant="footnote" tone="tertiary" align="center">{t('profile.independent')}</Txt>
      </Pressable>

      <Sheet visible={langOpen} onClose={() => setLangOpen(false)} title={t('settings.languageTitle')}>
        {(['ru', 'kk'] as Locale[]).map((l) => (
          <Option key={l} label={l === 'ru' ? t('settings.ru') : t('settings.kk')} selected={locale === l} onPress={() => { setLocale(l); setLangOpen(false); }} />
        ))}
      </Sheet>

      <Sheet visible={themeOpen} onClose={() => setThemeOpen(false)} title={t('settings.themeTitle')}>
        {(['system', 'light', 'dark'] as ThemeMode[]).map((m) => (
          <Option
            key={m}
            label={m === 'system' ? t('settings.system') : m === 'light' ? t('settings.light') : t('settings.dark')}
            selected={themeMode === m}
            icon={<Sun size={18} color={colors.textSecondary} />}
            onPress={() => { setThemeMode(m); setThemeOpen(false); }}
          />
        ))}
      </Sheet>

      <Sheet visible={logoutOpen} onClose={() => setLogoutOpen(false)} title={t('settings.logoutTitle')}>
        <Button title={t('profile.logout')} variant="destructive" fullWidth onPress={async () => { setLogoutOpen(false); await logout(); }} />
        <Button title={t('common.cancel')} variant="text" fullWidth onPress={() => setLogoutOpen(false)} />
      </Sheet>
    </ScrollView>
  );
}

function Option({ label, selected, onPress, icon }: { label: string; selected: boolean; onPress: () => void; icon?: ReactNode }) {
  const { colors, spacing, radii } = useTheme();
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ selected }}
      accessibilityLabel={label}
      onPress={onPress}
      style={{ minHeight: 52, borderRadius: radii.md, borderWidth: 1, borderColor: selected ? colors.primary : colors.border, backgroundColor: selected ? colors.primarySoft : colors.surface, paddingHorizontal: spacing.lg, flexDirection: 'row', alignItems: 'center', gap: spacing.md }}
    >
      {icon}
      <Txt variant="bodyMedium" style={{ flex: 1 }}>{label}</Txt>
      {selected ? <Txt variant="headline" tone="primaryText">✓</Txt> : null}
    </Pressable>
  );
}
