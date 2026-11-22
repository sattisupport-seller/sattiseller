// Подключение Kaspi (этап 2, задача 2.7). Работает только при флаге kaspi_connection на сервере.
import * as Clipboard from 'expo-clipboard';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, ScrollView, View } from 'react-native';
import { Plug } from 'lucide-react-native';
import { useState } from 'react';

import { useAppConfig } from '@/api/hooks';
import { ApiError, request } from '@/api/client';
import { Button } from '@/components/ui/Button';
import { Badge, Banner, Card } from '@/components/ui/Surfaces';
import { TextField } from '@/components/ui/Inputs';
import { Txt } from '@/components/ui/Text';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

type KaspiStatus = {
  enabled: boolean;
  status: 'not_connected' | 'active' | 'token_invalid';
  seller_id?: string;
  connected_at?: string;
  last_sync_at?: string | null;
  last_error?: string | null;
  price_url?: string;
};

type SyncResult = { added: number; updated: number; pages: number; status: string };

const KEY = 'kaspi-connection';

// Тексты ошибок сервера — только по коду; остальное — общая фраза.
function errorText(e: unknown, t: ReturnType<typeof useI18n>['t']): string {
  if (e instanceof ApiError) {
    if (e.code === 'kaspi_token_rejected') return t('kaspi.errTokenRejected');
    if (e.code === 'kaspi_unavailable') return t('kaspi.errUnavailable');
    if (e.code === 'rate_limited') return t('kaspi.errRateLimited');
  }
  return t('kaspi.errGeneric');
}

export default function KaspiScreen() {
  const { t, locale } = useI18n();
  const { colors, spacing, radii } = useTheme();
  const { shopId, isDemo } = useSession();
  const config = useAppConfig();
  const qc = useQueryClient();
  const [sellerId, setSellerId] = useState('');
  const [token, setToken] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const enabled = config.data?.flags.kaspi_connection ?? false;

  const status = useQuery({
    queryKey: [KEY, shopId],
    queryFn: () => request<KaspiStatus>(`/shops/${shopId}/kaspi/connection`),
    enabled: enabled && !!shopId && !isDemo,
  });

  const connect = useMutation({
    mutationFn: () => request<KaspiStatus>(`/shops/${shopId}/kaspi/connection`, {
      method: 'POST', body: { seller_id: sellerId.trim(), token: token.trim() },
    }),
    onMutate: () => { setError(null); setNotice(null); },
    onSuccess: () => { setToken(''); void qc.invalidateQueries({ queryKey: [KEY, shopId] }); },
    onError: (e) => setError(errorText(e, t)),
  });

  const sync = useMutation({
    mutationFn: () => request<SyncResult>(`/shops/${shopId}/kaspi/sync`, { method: 'POST' }),
    onMutate: () => { setError(null); setNotice(null); },
    onSuccess: (r) => {
      setNotice(t('kaspi.syncDone', { added: r.added, updated: r.updated }));
      void qc.invalidateQueries({ queryKey: [KEY, shopId] });
      void qc.invalidateQueries({ queryKey: ['shops'] });
    },
    onError: (e) => {
      setError(errorText(e, t));
      void qc.invalidateQueries({ queryKey: [KEY, shopId] });
    },
  });

  const disconnect = useMutation({
    mutationFn: () => request(`/shops/${shopId}/kaspi/connection`, { method: 'DELETE' }),
    onSuccess: () => { setNotice(null); void qc.invalidateQueries({ queryKey: [KEY, shopId] }); },
    onError: (e) => setError(errorText(e, t)),
  });

  const confirmDisconnect = () => {
    Alert.alert(t('kaspi.disconnectTitle'), t('kaspi.disconnectText'), [
      { text: t('common.cancel'), style: 'cancel' },
      { text: t('kaspi.disconnectYes'), style: 'destructive', onPress: () => disconnect.mutate() },
    ]);
  };

  const copyPrice = async (url: string) => {
    await Clipboard.setStringAsync(url);
    setNotice(t('kaspi.copied'));
  };

  const Header = (
    <View style={{ alignItems: 'center', gap: spacing.md, paddingVertical: spacing.lg }}>
      <View style={{ width: 72, height: 72, borderRadius: radii.full, backgroundColor: colors.primarySoft, alignItems: 'center', justifyContent: 'center' }}>
        <Plug size={32} color={colors.onPrimarySoft} />
      </View>
      <Txt variant="title3" align="center">{t('kaspi.title')}</Txt>
    </View>
  );

  const wrap = (children: React.ReactNode) => (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 48, gap: spacing.md }} style={{ backgroundColor: colors.bg }}>
      {Header}
      {children}
    </ScrollView>
  );

  if (!enabled) {
    return wrap(<Card><Txt variant="body" tone="secondary">{t('kaspi.disabled')}</Txt></Card>);
  }
  if (isDemo) {
    return wrap(<Card><Txt variant="body" tone="secondary">{t('kaspi.demoOnly')}</Txt></Card>);
  }

  const data = status.data;
  const connected = data && data.status !== 'not_connected';
  const busy = connect.isPending || sync.isPending || disconnect.isPending;
  const lastSync = data?.last_sync_at
    ? new Date(data.last_sync_at).toLocaleString(locale === 'kk' ? 'kk-KZ' : 'ru-RU')
    : t('kaspi.never');

  return wrap(
    <>
      {!connected ? (
        <Card style={{ gap: spacing.md }}>
          <Txt variant="body" tone="secondary">{t('kaspi.intro')}</Txt>
          <TextField label={t('kaspi.sellerId')} value={sellerId} onChangeText={setSellerId}
            hint={t('kaspi.sellerIdHint')} maxLength={64} />
          <TextField label={t('kaspi.token')} value={token} onChangeText={setToken}
            hint={t('kaspi.tokenHint')} secure maxLength={256} />
          {error ? <Banner text={error} tone="danger" /> : null}
          <Button
            title={connect.isPending ? t('kaspi.connecting') : t('kaspi.connect')}
            onPress={() => {
              if (!sellerId.trim() || token.trim().length < 8) { setError(t('kaspi.requiredFields')); return; }
              connect.mutate();
            }}
            loading={connect.isPending}
            disabled={busy}
            fullWidth
          />
        </Card>
      ) : (
        <>
          <Card style={{ gap: spacing.sm }}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
              <Txt variant="bodyMedium">{t('kaspi.connected')}</Txt>
              <Badge
                label={data?.status === 'token_invalid' ? t('kaspi.errTokenRejected') : t('kaspi.connected')}
                tone={data?.status === 'token_invalid' ? 'danger' : 'success'}
              />
            </View>
            <Txt variant="footnote" tone="secondary">{t('kaspi.lastSync')}: {lastSync}</Txt>
            {data?.last_error ? <Banner text={data.last_error} tone="warning" /> : null}
          </Card>

          {data?.price_url ? (
            <Card style={{ gap: spacing.sm }}>
              <Txt variant="subheadMedium">{t('kaspi.priceTitle')}</Txt>
              <Txt variant="footnote" tone="tertiary" selectable>{data.price_url}</Txt>
              <Txt variant="footnote" tone="tertiary">{t('kaspi.priceHint')}</Txt>
              <Button title={t('kaspi.copy')} variant="outline" onPress={() => { void copyPrice(data.price_url!); }} fullWidth />
            </Card>
          ) : null}

          {error ? <Banner text={error} tone="danger" /> : null}
          {notice ? <Banner text={notice} tone="info" /> : null}
          <Button
            title={sync.isPending ? t('kaspi.syncing') : t('kaspi.syncNow')}
            onPress={() => sync.mutate()}
            loading={sync.isPending}
            disabled={busy || data?.status === 'token_invalid'}
            fullWidth
          />
          <Button title={t('kaspi.disconnect')} variant="destructiveText" onPress={confirmDisconnect} disabled={busy} fullWidth />
        </>
      )}
    </>,
  );
}
