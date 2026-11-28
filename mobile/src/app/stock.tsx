import { Stack } from 'expo-router';
import { useState } from 'react';
import { ScrollView, View } from 'react-native';

import { ApiError } from '@/api/client';
import { useProducts, useShops, useStockAlerts, useStockList, useStockMutations, type StockItem } from '@/api/hooks';
import { Button } from '@/components/ui/Button';
import { TextField } from '@/components/ui/Inputs';
import { Sheet, useToast } from '@/components/ui/Overlays';
import { Card } from '@/components/ui/Surfaces';
import { Txt } from '@/components/ui/Text';
import { useI18n } from '@/i18n';
import { useSession } from '@/session/SessionProvider';
import { useTheme } from '@/theme/useTheme';

// Склад (решения владельца 22.11): остатки, приход, инвентаризация, уведомления 10/5/3, снятие с продажи.
// Списание продаж и возвраты делает сервер; здесь — ввод и подтверждение.
type Mode = { kind: 'inventory' | 'receipt' | 'buffer'; productId: string; name: string } | null;

export default function StockScreen() {
  const { t } = useI18n();
  const { colors, spacing } = useTheme();
  const toast = useToast();
  const { shopId } = useSession();
  const list = useStockList(shopId);
  const alerts = useStockAlerts(shopId);
  const products = useProducts(shopId, '30d', null, 'profit_desc', '');
  const mut = useStockMutations(shopId);
  const shops = useShops(!!shopId);
  const presentation = !!shops.data?.items.find((x) => x.id === shopId)?.presentation_mode;
  const [mode, setMode] = useState<Mode>(null);
  const [qty, setQty] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [confirmDelist, setConfirmDelist] = useState<StockItem | null>(null);
  // Первый приход без инвентаризации: сначала остаток (можно 0), потом приход (К-4)
  const [countFirst, setCountFirst] = useState<{ productId: string; name: string; qty: number } | null>(null);
  const [pendingReceipt, setPendingReceipt] = useState<{ productId: string; qty: number } | null>(null);

  const stockByProduct = new Map((list.data?.items ?? []).map((s) => [s.productId, s]));
  const allProducts = (products.data?.pages ?? []).flatMap((p) => p.items);
  // К-33 А3: предпросмотр автоснятия — товары, которые сняли бы с продажи сейчас (остаток 0 или снят вручную)
  const wouldDelist = (list.data?.items ?? []).filter((s) => s.delisted || (s.forSale ?? s.current) <= 0);

  const submitQty = async () => {
    // Инвентаризация: 0 допустим (товар закончился). Приход: только больше нуля.
    const raw = qty.trim();
    const n = Number(raw.replace(',', '.'));
    const min = mode?.kind === 'receipt' ? 1 : 0;
    if (!mode || raw === '' || !Number.isInteger(n) || n < min) return setError(t('stock.invalid'));
    setError(null);
    try {
      if (mode.kind === 'receipt') await mut.receipt.mutateAsync({ productId: mode.productId, qty: n });
      else if (mode.kind === 'buffer') await mut.buffer.mutateAsync({ productId: mode.productId, buffer: n });
      else await mut.inventory.mutateAsync({ productId: mode.productId, qty: n });
      setMode(null);
      setQty('');
      toast.show(t('stock.done'));
      if (mode.kind === 'inventory' && pendingReceipt && pendingReceipt.productId === mode.productId) {
        const pr = pendingReceipt;
        setPendingReceipt(null);
        await mut.receipt.mutateAsync({ productId: pr.productId, qty: pr.qty });
        toast.show(t('stock.done'));
      }
    } catch (e) {
      if (mode.kind === 'receipt' && e instanceof ApiError && e.code === 'stock_not_counted') {
        setCountFirst({ productId: mode.productId, name: mode.name, qty: n });
        setMode(null);
        return;
      }
      setError(t('stock.invalid'));
    }
  };

  const doDelist = async () => {
    if (!confirmDelist) return;
    await mut.delist.mutateAsync(confirmDelist.productId);
    setConfirmDelist(null);
  };

  const levelText = (s: StockItem) => {
    if (s.level === 'out') return t('stock.outOfStock');
    if (s.level) return t('stock.lowStock', { qty: s.current });
    return null;
  };

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}>
      <Stack.Screen options={{ title: t('stock.title') }} />
      {(alerts.data?.endingSoon?.length ?? 0) > 0 && (
        <Card>
          <Txt variant="headline">{t('stock.endingSoon')}</Txt>
          {alerts.data!.endingSoon.map((s) => (
            <Txt key={s.productId} variant="body">{s.name}: {t('stock.daysLeft', { days: s.daysLeft ?? 0 })}</Txt>
          ))}
        </Card>
      )}
      <Txt variant="footnote" tone="secondary">{t('stock.kaspiHint')}</Txt>
      {presentation && (
        <Card style={{ gap: spacing.xs }}>
          <Txt variant="headline">{t('stock.previewTitle', { count: wouldDelist.length })}</Txt>
          {wouldDelist.map((s) => <Txt key={s.productId} variant="body">{s.name} · {s.current} шт.</Txt>)}
          <Txt variant="footnote" tone="secondary">{t('stock.previewNote')}</Txt>
        </Card>
      )}
      {allProducts.length === 0 && <Txt variant="body" tone="secondary">{t('stock.empty')}</Txt>}
      {allProducts.map((p) => {
        const s = stockByProduct.get(p.product_id);
        return (
          <Card key={p.product_id}>
            <Txt variant="headline">{p.name}</Txt>
            <Txt variant="footnote" tone="secondary">{p.sku}</Txt>
            {s ? (
              <>
                <Txt variant="body">{s.current} шт.{s.example ? ` · ${t('stock.example')}` : ''}</Txt>
                {levelText(s) && <Txt variant="body" tone="danger">{levelText(s)}</Txt>}
                {s.daysLeft !== null && s.current > 0 && <Txt variant="footnote" tone="secondary">{t('stock.daysLeft', { days: s.daysLeft })}</Txt>}
                {(s.buffer ?? 0) > 0 && (
                  <Txt variant="footnote" tone="secondary">{t('stock.bufferInfo', { buffer: s.buffer ?? 0, forSale: s.forSale ?? 0 })}</Txt>
                )}
                {(s.returning ?? 0) > 0 && (
                  <View style={{ gap: spacing.xs }}>
                    <Txt variant="footnote" tone="secondary">{t('stock.returning', { qty: s.returning ?? 0 })}</Txt>
                    <View style={{ flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' }}>
                      <Button title={t('stock.pickedUpOk')} size="S" variant="secondary"
                        onPress={() => mut.pickedUp.mutate({ productId: p.product_id, qty: s.returning ?? 0, sellable: true })} />
                      <Button title={t('stock.pickedUpDefect')} size="S" variant="text"
                        onPress={() => mut.pickedUp.mutate({ productId: p.product_id, qty: s.returning ?? 0, sellable: false })} />
                    </View>
                  </View>
                )}
                {(s.pendingReturns ?? 0) > 0 && (
                  <View style={{ gap: spacing.xs }}>
                    <Txt variant="footnote" tone="secondary">{t('stock.confirmReturn', { qty: s.pendingReturns ?? 0 })}</Txt>
                    <View style={{ flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' }}>
                      <Button title={t('stock.returnBack')} size="S" variant="secondary"
                        onPress={() => mut.confirmReturns.mutate({ productId: p.product_id, sellable: true })} />
                      <Button title={t('stock.returnNotBack')} size="S" variant="text"
                        onPress={() => mut.confirmReturns.mutate({ productId: p.product_id, sellable: false })} />
                    </View>
                  </View>
                )}
              </>
            ) : (
              <Txt variant="footnote" tone="secondary">{t('stock.empty')}</Txt>
            )}
            <View style={{ flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' }}>
              <Button title={t('stock.inventory')} variant="secondary" onPress={() => setMode({ kind: 'inventory', productId: p.product_id, name: p.name })} />
              <Button title={t('stock.receipt')} variant="secondary" onPress={() => setMode({ kind: 'receipt', productId: p.product_id, name: p.name })} />
              {s && s.level === 'out' && !s.delisted && (
                <Button title={t('stock.delist')} variant="text" onPress={() => setConfirmDelist(s)} />
              )}
              {s && s.delisted && <Button title={t('stock.relist')} variant="text" onPress={() => mut.relist.mutate(p.product_id)} />}
              {s && <Button title={t('stock.buffer')} variant="text" onPress={() => { setMode({ kind: 'buffer', productId: p.product_id, name: p.name }); setQty(String(s.buffer ?? 0)); }} />}
            </View>
            {mode?.productId === p.product_id && (
              <View style={{ gap: spacing.sm }}>
                {mode.kind === 'buffer' && <Txt variant="footnote" tone="secondary">{t('stock.bufferHint')}</Txt>}
                <TextField label={mode.kind === 'buffer' ? t('stock.bufferLabel') : t('stock.qtyLabel')} accessibilityLabel={mode.kind === 'buffer' ? t('stock.bufferLabel') : t('stock.qtyLabel')} value={qty} onChangeText={setQty} keyboardType="number-pad" error={error ?? undefined} />
                <Button title={t('stock.save')} onPress={submitQty} loading={mut.inventory.isPending || mut.receipt.isPending || !!mut.buffer?.isPending} fullWidth />
              </View>
            )}
          </Card>
        );
      })}
      <Sheet visible={!!countFirst} onClose={() => setCountFirst(null)} title={t('stock.countFirst')}>
        <Txt variant="body" tone="secondary">{t('stock.countFirstBody')}</Txt>
        <Button
          title={t('stock.countFirstBtn')}
          onPress={() => {
            if (!countFirst) return;
            setPendingReceipt({ productId: countFirst.productId, qty: countFirst.qty });
            setMode({ kind: 'inventory', productId: countFirst.productId, name: countFirst.name });
            setCountFirst(null);
          }}
          fullWidth
        />
      </Sheet>
      <Sheet visible={!!confirmDelist} onClose={() => setConfirmDelist(null)} title={t('stock.confirmDelistTitle')}>
        <Txt variant="body" tone="secondary">{t('stock.confirmDelistBody')}</Txt>
        <Button title={t('stock.confirmDelist')} onPress={doDelist} loading={mut.delist.isPending} fullWidth />
        <Button title={t('stock.cancel')} variant="text" onPress={() => setConfirmDelist(null)} fullWidth />
      </Sheet>
    </ScrollView>
  );
}
