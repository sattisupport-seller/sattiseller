import * as Clipboard from 'expo-clipboard';
import * as DocumentPicker from 'expo-document-picker';
import * as ImageManipulator from 'expo-image-manipulator';
import * as ImagePicker from 'expo-image-picker';
import { useState } from 'react';
import { Image, Pressable, ScrollView, View } from 'react-native';

import { ApiError } from '@/api/client';
import { useFeedback, useProductDraft } from '@/api/hooks';
import { draftErrorText } from '@/api/aiErrors';
import type { ProductDraft } from '@/api/types';
import { Button } from '@/components/ui/Button';
import { TextField } from '@/components/ui/Inputs';
import { Txt } from '@/components/ui/Text';
import { Banner, Card, Chip, Section } from '@/components/ui/Surfaces';
import { useToast } from '@/components/ui/Overlays';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

// К-20 п.2: фото с телефона бывают больше лимита сервера (5 МБ). Сжимаем до длинной стороны 1600 px в JPEG 0,7.
async function shrinkPhoto(uri: string, width?: number, height?: number) {
  // Размер неизвестен (файл из проводника): ширина 1600, высота по пропорции — этого хватает для лимита.
  const landscapeOrUnknown = width === undefined || height === undefined || width >= height;
  const longest = Math.max(width ?? 0, height ?? 0);
  const actions = longest > 1600 || longest === 0
    ? [{ resize: landscapeOrUnknown ? { width: 1600 } : { height: 1600 } }]
    : [];
  const out = await ImageManipulator.manipulateAsync(uri, actions, {
    compress: 0.7,
    format: ImageManipulator.SaveFormat.JPEG,
  });
  return { uri: out.uri, name: `photo-${Date.now()}.jpg`, type: 'image/jpeg' };
}

// Черновик описания товара (docs/spec.md, 8.9): только по введённым фактам и фото, ничего не публикуется.
export default function ProductDraftScreen() {
  const { t } = useI18n();
  const { colors, spacing, radii } = useTheme();
  const toast = useToast();
  const { shopId } = useSession();
  const draft = useProductDraft(shopId);
  const feedback = useFeedback();
  const [flagged, setFlagged] = useState(false);
  const [facts, setFacts] = useState('');
  const [photos, setPhotos] = useState<{ uri: string; name: string; type: string }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ProductDraft | null>(null);

  const addPhoto = async () => {
    const res = await DocumentPicker.getDocumentAsync({ type: ['image/jpeg', 'image/png', 'image/webp'], multiple: true, copyToCacheDirectory: true });
    if (res.canceled) return;
    const next = await Promise.all(res.assets.map((a) => shrinkPhoto(a.uri)));  // у файлов из проводника размер не известен
    setPhotos((p) => [...p, ...next].slice(0, 5));
  };

  // Съёмка камерой: разрешение запрашивается в момент нажатия (spec-2.1, задача 17).
  const takePhoto = async () => {
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    if (!perm.granted) {
      setError(t('assistant.cameraDenied'));
      return;
    }
    const res = await ImagePicker.launchCameraAsync({ mediaTypes: ['images'], quality: 0.8 });
    if (res.canceled) return;
    const a = res.assets[0];
    const photo = await shrinkPhoto(a.uri, a.width, a.height);
    setPhotos((p) => [...p, photo].slice(0, 5));
  };

  const make = async () => {
    setError(null);
    const form = new FormData();
    form.append('shop_id', shopId ?? '');
    form.append('facts', facts);
    form.append('languages', 'ru');  // К-13: описание только на русском
    photos.forEach((p) => form.append('photos', { uri: p.uri, name: p.name, type: p.type } as unknown as Blob));
    try {
      setResult(await draft.mutateAsync(form));
      setFlagged(false);
    } catch (e) {
      setError(draftErrorText(e, t));
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
          <>
            <Pressable accessibilityRole="button" accessibilityLabel={t('assistant.takePhoto')} onPress={takePhoto}
              style={{ width: 72, height: 72, borderRadius: radii.md, borderWidth: 1, borderStyle: 'dashed', borderColor: colors.borderStrong, alignItems: 'center', justifyContent: 'center' }}>
              <Txt variant="footnote" tone="tertiary">{t('assistant.takePhoto')}</Txt>
            </Pressable>
            <Pressable accessibilityRole="button" accessibilityLabel={t('assistant.pickPhoto')} onPress={addPhoto}
              style={{ width: 72, height: 72, borderRadius: radii.md, borderWidth: 1, borderStyle: 'dashed', borderColor: colors.borderStrong, alignItems: 'center', justifyContent: 'center' }}>
              <Txt variant="footnote" tone="tertiary">{t('assistant.pickPhoto')}</Txt>
            </Pressable>
          </>
        ) : null}
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
          {/* Google Play: жалоба на созданный ИИ текст — прямо в приложении */}
          {(result as { generatedBy?: string }).generatedBy !== 'template' ? (
            <Button
              title={flagged ? t('assistant.flagSent') : t('assistant.flagDraft')}
              variant="text"
              disabled={flagged || !shopId}
              onPress={() => {
                if (!shopId) return;
                feedback.mutate({ shop_id: shopId, turn_id: null, kind: 'flag', reason: 'product_draft' });
                setFlagged(true);
                toast.show(t('assistant.flagSent'));
              }}
              fullWidth
            />
          ) : null}
          <Button title={t('assistant.copyAll')} onPress={copyAll} fullWidth />
        </>
      ) : null}
    </ScrollView>
  );
}
