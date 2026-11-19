import * as Clipboard from 'expo-clipboard';
import * as DocumentPicker from 'expo-document-picker';
import { useState } from 'react';
import { Image, Pressable, ScrollView, View } from 'react-native';

import { ApiError } from '@/api/client';
import { useProductDraft } from '@/api/hooks';
import type { ProductDraft } from '@/api/types';
import { Button } from '@/components/ui/Button';
import { TextField } from '@/components/ui/Inputs';
import { Txt } from '@/components/ui/Text';
import { Banner, Card, Chip, Section } from '@/components/ui/Surfaces';
import { useToast } from '@/components/ui/Overlays';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

type Lang = 'ru' | 'kk' | 'both';

// Черновик описания товара (docs/spec.md, 8.9): только по введённым фактам и фото, ничего не публикуется.
export default function ProductDraftScreen() {
  const { t } = useI18n();
  const { colors, spacing, radii } = useTheme();
  const toast = useToast();
  const { shopId } = useSession();
  const draft = useProductDraft(shopId);
  const [facts, setFacts] = useState('');
  const [photos, setPhotos] = useState<{ uri: string; name: string; type: string }[]>([]);
  const [lang, setLang] = useState<Lang>('ru');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ProductDraft | null>(null);

  const addPhoto = async () => {
    const res = await DocumentPicker.getDocumentAsync({ type: ['image/jpeg', 'image/png', 'image/webp'], multiple: true, copyToCacheDirectory: true });
    if (res.canceled) return;
    const next = res.assets.map((a) => ({ uri: a.uri, name: a.name, type: a.mimeType ?? 'image/jpeg' }));
    setPhotos((p) => [...p, ...next].slice(0, 5));
  };

  const make = async () => {
    setError(null);
    const form = new FormData();
    form.append('shop_id', shopId ?? '');
    form.append('facts', facts);
    form.append('languages', lang);
    photos.forEach((p) => form.append('photos', { uri: p.uri, name: p.name, type: p.type } as unknown as Blob));
    try {
      setResult(await draft.mutateAsync(form));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('common.unknownError'));
    }
  };

  const copy = async (text: string) => {
    await Clipboard.setStringAsync(text);
    toast.show(t('common.copied'));
  };

  const copyAll = () => {
    if (!result) return;
    const chars = result.characteristics.map((c) => `${c.name}: ${c.value}`).join('\n');
    copy([result.titles[0], result.description, chars].join('\n\n'));
  };

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 48, gap: spacing.md }} style={{ backgroundColor: colors.bg }} keyboardShouldPersistTaps="handled">
      <TextField
        label={t('assistant.productDraftFacts')}
        value={facts}
        onChangeText={(v) => { setFacts(v); setError(null); }}
        placeholder={t('assistant.productDraftHint')}
        multiline
        minHeight={140}
        maxLength={1000}
        hint={`${facts.length}/1000`}
        autoCapitalize="sentences"
      />

      <Txt variant="subheadMedium" tone="secondary">{t('assistant.photos')}</Txt>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }}>
        {photos.map((p, i) => (
          <Pressable key={p.uri + i} accessibilityLabel={p.name} onPress={() => setPhotos((arr) => arr.filter((_, j) => j !== i))}
            style={{ width: 72, height: 72, borderRadius: radii.md, overflow: 'hidden', backgroundColor: colors.surfaceAlt }}>
            <Image source={{ uri: p.uri }} style={{ width: 72, height: 72 }} />
          </Pressable>
        ))}
        {photos.length < 5 ? (
          <Pressable accessibilityRole="button" accessibilityLabel={t('assistant.photos')} onPress={addPhoto}
            style={{ width: 72, height: 72, borderRadius: radii.md, borderWidth: 1, borderStyle: 'dashed', borderColor: colors.borderStrong, alignItems: 'center', justifyContent: 'center' }}>
            <Txt variant="title2" tone="tertiary">+</Txt>
          </Pressable>
        ) : null}
      </View>

      <Txt variant="subheadMedium" tone="secondary">{t('assistant.languages')}</Txt>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
        <Chip label={t('assistant.langRu')} selected={lang === 'ru'} onPress={() => setLang('ru')} />
        <Chip label={t('assistant.langKk')} selected={lang === 'kk'} onPress={() => setLang('kk')} />
        <Chip label={t('assistant.langBoth')} selected={lang === 'both'} onPress={() => setLang('both')} />
      </View>

      {error ? <Banner text={error} tone="danger" /> : null}

      <Button title={t('assistant.makeDraft')} onPress={make} loading={draft.isPending} disabled={!facts.trim()} fullWidth />

      {result ? (
        <>
          <Section title={t('assistant.titles')}>
            {result.titles.map((title, i) => (
              <Card key={i} style={{ gap: spacing.sm }}>
                <Txt variant="bodyMedium">{title}</Txt>
                <Button title={t('common.copy')} size="S" variant="secondary" onPress={() => copy(title)} />
              </Card>
            ))}
          </Section>
          <Section title={t('assistant.description')}>
            <Card style={{ gap: spacing.sm }}>
              <Txt variant="body">{result.description}</Txt>
              <Button title={t('common.copy')} size="S" variant="secondary" onPress={() => copy(result.description)} />
            </Card>
          </Section>
          <Section title={t('assistant.characteristics')}>
            <Card style={{ gap: spacing.sm }}>
              {result.characteristics.map((c) => (
                <View key={c.name} style={{ flexDirection: 'row', justifyContent: 'space-between', gap: spacing.md }}>
                  <Txt variant="subhead" tone="secondary">{c.name}</Txt>
                  <Txt variant="bodyMedium" tone={c.value === t('assistant.uncertain') ? 'warning' : 'primary'}>
                    {c.value === 'Уточнить' ? t('assistant.uncertain') : c.value}
                  </Txt>
                </View>
              ))}
            </Card>
          </Section>
          {result.warnings.map((w) => <Banner key={w} text={w} tone="info" />)}
          <Button title={t('assistant.copyAll')} onPress={copyAll} fullWidth />
        </>
      ) : null}
    </ScrollView>
  );
}
