// Подключение Kaspi (этап 2, задача 2.7). Работает только при флаге kaspi_connection на сервере.
import * as Clipboard from 'expo-clipboard';
import * as DocumentPicker from 'expo-document-picker';
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
import { SUPPORT_EMAIL } from '@/config';
import { useTour } from '@/onboarding/OnboardingProvider';
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
  store_ids?: string[];
  store_hint?: string | null;
  catalog?: { offers_count: number; imported_at: string } | null;
  load?: { done: number; total: number | null; complete: boolean } | null;
  price_hint?: string | null;
  reconnect_until?: string | null;  // К-21: окно восстановления токена (открывает поддержка, 24 часа)
};

// Код склада Kaspi (storeId): латиница, цифры, «-» и «_», до 40 знаков (документация Kaspi, К-7).
const STORE_RE = /^[A-Za-z0-9_-]{1,40}$/;

type SyncResult = { added: number; updated: number; pages: number; status: string };

const KEY = 'kaspi-connection';

// Тексты ошибок сервера — только по коду; остальное — общая фраза.
function errorText(e: unknown, t: ReturnType<typeof useI18n>['t']): string {
  if (e instanceof ApiError) {
    if (e.code === 'kaspi_token_rejected') return t('kaspi.errTokenRejected');
    if (e.code === 'kaspi_unavailable') return t('kaspi.errUnavailable');
    if (e.code === 'rate_limited') return t('kaspi.errRateLimited');
    if (e.code === 'kaspi_sync_running') return t('kaspi.errSyncRunning');
    if (e.code === 'kaspi_already_connected') return t('kaspi.errAlreadyConnected');
    if (e.code === 'kaspi_shop_taken') return t('kaspi.errShopTaken');
    if (e.code === 'kaspi_other_shop') return t('kaspi.errOtherShop');
    if (e.code === 'account_blocked') return e.message;
  }
  return t('kaspi.errGeneric');
}

export default function KaspiScreen() {
  const { t, locale } = useI18n();
  const { colors, spacing, radii } = useTheme();
  const { shopId, isDemo } = useSession();
  const tour = useTour();
  const config = useAppConfig();
  const qc = useQueryClient();
  const [sellerId, setSellerId] = useState('');
  const [token, setToken] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [storeInput, setStoreInput] = useState('');
  const [storeError, setStoreError] = useState<string | null>(null);
  const enabled = config.data?.flags.kaspi_connection ?? false;

  const status = useQuery({
    queryKey: [KEY, shopId],
    queryFn: () => request<KaspiStatus>(`/shops/${shopId}/kaspi/connection`),
    enabled: enabled && !!shopId && !isDemo,
  });

  const connect = useMutation({
    mutationFn: (sellerValue: string) => request<KaspiStatus>(`/shops/${shopId}/kaspi/connection`, {
      method: 'POST', body: { seller_id: sellerValue.trim(), token: token.trim() },
    }),
    onMutate: () => { setError(null); setNotice(null); },
    onSuccess: () => { setToken(''); void qc.invalidateQueries({ queryKey: [KEY, shopId] }); },
    onError: (e) => setError(errorText(e, t)),
  });

  const saveStores = useMutation({
    mutationFn: (codes: string[]) => request<KaspiStatus>(`/shops/${shopId}/kaspi/stores`, {
      method: 'PUT', body: { store_ids: codes },
    }),
    onMutate: () => { setStoreError(null); setError(null); setNotice(null); },
    onSuccess: () => {
      setStoreInput('');
      setNotice(t('kaspi.storeSaved'));
      void qc.invalidateQueries({ queryKey: [KEY, shopId] });
    },
    onError: (e) => setError(errorText(e, t)),
  });

  const uploadCatalog = useMutation({
    mutationFn: async () => {
      const res = await DocumentPicker.getDocumentAsync({ type: ['text/xml', 'application/xml'], copyToCacheDirectory: true });
      if (res.canceled) return null;
      const a = res.assets[0];
      const form = new FormData();
      form.append('file', { uri: a.uri, name: a.name ?? 'price.xml', type: 'application/xml' } as unknown as Blob);
      return request<KaspiStatus>(`/shops/${shopId}/kaspi/catalog`, { method: 'POST', form });
    },
    onMutate: () => { setError(null); setNotice(null); },
    onSuccess: (r) => {
      if (r) {
        setNotice(t('kaspi.catalogDone', { count: r.catalog?.offers_count ?? 0 }));
        void qc.invalidateQueries({ queryKey: [KEY, shopId] });
      }
    },
    onError: (e) => setError(e instanceof ApiError && e.code === 'kaspi_catalog_invalid' ? e.message : errorText(e, t)),
  });

  const sync = useMutation({
    mutationFn: () => request<SyncResult>(`/shops/${shopId}/kaspi/sync`, { method: 'POST' }),
    onMutate: () => { setError(null); setNotice(null); },
    onSuccess: (r) => {
      setNotice(r.status === 'queued' ? t('kaspi.syncQueued') : t('kaspi.syncDone', { added: r.added, updated: r.updated }));
      void qc.invalidateQueries({ queryKey: [KEY, shopId] });
      void qc.invalidateQueries({ queryKey: ['shops'] });
    },
    onError: (e) => {
      setError(errorText(e, t));
      void qc.invalidateQueries({ queryKey: [KEY, shopId] });
    },
  });

  // К-21 (решение владельца 01:31): токен подключается один раз — перед подключением предупреждение.
  // Отдельного отключения Kaspi нет (01:24): только удаление или деактивация аккаунта.
  const confirmConnect = (sellerValue: string) => {
    if (!sellerValue.trim() || token.trim().length < 8) { setError(t('kaspi.requiredFields')); return; }
    Alert.alert(t('kaspi.onceTitle'), t('kaspi.onceText'), [
      { text: t('common.cancel'), style: 'cancel' },
      { text: t('kaspi.onceYes'), onPress: () => connect.mutate(sellerValue) },
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
  if (!tour.done && !(status.data && status.data.status !== 'not_connected')) {
    // решение владельца 02:19: без пройденного обучения подключение Kaspi недоступно
    return wrap(
      <Card style={{ gap: spacing.md }}>
        <Txt variant="body" tone="secondary">{t('kaspi.onboardingFirst')}</Txt>
        {tour.active ? null : <Button title={t('kaspi.onboardingStart')} onPress={tour.start} fullWidth />}
      </Card>,
    );
  }

  const data = status.data;
  const connected = data && data.status !== 'not_connected';
  const busy = connect.isPending || sync.isPending || saveStores.isPending;
  const lastSync = data?.last_sync_at
    ? new Date(data.last_sync_at).toLocaleString('ru-RU')
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
            onPress={() => confirmConnect(sellerId)}
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
            {data?.load && !data.load.complete ? (
              <Txt variant="footnote" tone="secondary">
                {t('kaspi.loadProgress', { done: data.load.done, total: data.load.total ?? data.load.done })}
              </Txt>
            ) : null}
            {data?.last_error ? <Banner text={data.last_error} tone="warning" /> : null}
            {data?.status === 'token_invalid' && !data.reconnect_until ? (
              <Txt variant="footnote" tone="secondary" selectable>{t('kaspi.tokenBroken', { email: SUPPORT_EMAIL })}</Txt>
            ) : null}
          </Card>

          {data?.reconnect_until ? (
            <Card style={{ gap: spacing.md }}>
              <Txt variant="subheadMedium">{t('kaspi.reconnectTitle')}</Txt>
              <Txt variant="footnote" tone="secondary">
                {t('kaspi.reconnectText', { date: new Date(data.reconnect_until).toLocaleString('ru-RU') })}
              </Txt>
              <TextField label={t('kaspi.token')} value={token} onChangeText={setToken}
                hint={t('kaspi.tokenHint')} secure maxLength={256} />
              {error ? <Banner text={error} tone="danger" /> : null}
              <Button
                title={connect.isPending ? t('kaspi.connecting') : t('kaspi.reconnectButton')}
                onPress={() => confirmConnect(data.seller_id ?? '')}
                loading={connect.isPending}
                disabled={busy}
                fullWidth
              />
            </Card>
          ) : null}

          <Card style={{ gap: spacing.sm }}>
            <Txt variant="subheadMedium">{t('kaspi.storeTitle')}</Txt>
            {data?.store_ids?.length
              ? <Txt variant="footnote" tone="secondary">{t('kaspi.storeCurrent', { codes: data.store_ids.join(', ') })}</Txt>
              : <Banner text={t('kaspi.storeMissing')} tone="warning" />}
            {data?.store_hint && !(data?.store_ids ?? []).includes(data.store_hint) ? (
              <Button title={t('kaspi.storeSuggest', { code: data.store_hint })} variant="outline"
                onPress={() => setStoreInput(data.store_hint!)} fullWidth />
            ) : null}
            <TextField label={t('kaspi.storeLabel')} value={storeInput} onChangeText={setStoreInput}
              hint={t('kaspi.storeHint')} maxLength={200} />
            {storeError ? <Banner text={storeError} tone="danger" /> : null}
            <Button
              title={saveStores.isPending ? t('kaspi.syncing') : t('kaspi.storeSave')}
              variant="outline"
              loading={saveStores.isPending}
              disabled={busy || !storeInput.trim()}
              onPress={() => {
                const codes = storeInput.split(',').map((x) => x.trim()).filter(Boolean);
                if (codes.length === 0 || !codes.every((c) => STORE_RE.test(c))) {
                  setStoreError(t('kaspi.storeInvalid'));
                  return;
                }
                saveStores.mutate(codes);
              }}
              fullWidth
            />
          </Card>

          <Card style={{ gap: spacing.sm }}>
            <Txt variant="subheadMedium">{t('kaspi.catalogTitle')}</Txt>
            {data?.catalog ? (
              <Txt variant="footnote" tone="secondary">
                {t('kaspi.catalogLoaded', { count: data.catalog.offers_count, date: new Date(data.catalog.imported_at).toLocaleString('ru-RU') })}
              </Txt>
            ) : (
              <Banner text={data?.price_hint ?? t('kaspi.catalogNone')} tone="warning" />
            )}
            <Button title={t('kaspi.catalogUpload')} variant="outline" onPress={() => uploadCatalog.mutate()}
              loading={uploadCatalog.isPending} disabled={busy} fullWidth />
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
          <Txt variant="footnote" tone="tertiary">{t('kaspi.noDisconnect')}</Txt>
        </>
      )}
    </>,
  );
}
