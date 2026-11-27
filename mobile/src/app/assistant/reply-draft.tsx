import * as Clipboard from 'expo-clipboard';
import { useState } from 'react';
import { ScrollView, View } from 'react-native';

import { ApiError } from '@/api/client';
import { useReplyDraft } from '@/api/hooks';
import { draftErrorText } from '@/api/aiErrors';
import type { ReplyDraft } from '@/api/types';
import { Button } from '@/components/ui/Button';
import { TextField } from '@/components/ui/Inputs';
import { Txt } from '@/components/ui/Text';
import { Banner, Card, Chip } from '@/components/ui/Surfaces';
import { useToast } from '@/components/ui/Overlays';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';

// Ответ покупателю (docs/spec.md, 8.9): только из вставленного вопроса, приложение ничего не отправляет.
export default function ReplyDraftScreen() {
  const { t } = useI18n();
  const { colors, spacing } = useTheme();
  const toast = useToast();
  const { shopId } = useSession();
  const reply = useReplyDraft(shopId);
  const [question, setQuestion] = useState('');
  const [tone, setTone] = useState<'polite' | 'short'>('polite');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ReplyDraft | null>(null);

  const make = async () => {
    setError(null);
    try {
      setResult(await reply.mutateAsync({ question, tone }));
    } catch (e) {
      setError(draftErrorText(e, t));
    }
  };

  const copy = async (text: string) => {
    await Clipboard.setStringAsync(text);
    toast.show(t('common.copied'));
  };

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 48, gap: spacing.md }} style={{ backgroundColor: colors.bg }} keyboardShouldPersistTaps="handled">
      <TextField
        label={t('assistant.replyQuestion')}
        value={question}
        onChangeText={(v) => { setQuestion(v); setError(null); }}
        placeholder={t('assistant.replyPaste')}
        multiline
        minHeight={120}
        maxLength={500}
        hint={t('assistant.replyWarning')}
      />
      <Txt variant="subheadMedium" tone="secondary">{t('assistant.replyTone')}</Txt>
      <View style={{ flexDirection: 'row' }}>
        <Chip label={t('assistant.tonePolite')} selected={tone === 'polite'} onPress={() => setTone('polite')} />
        <Chip label={t('assistant.toneShort')} selected={tone === 'short'} onPress={() => setTone('short')} />
      </View>
      {error ? <Banner text={error} tone="danger" /> : null}
      <Button title={t('assistant.makeReply')} onPress={make} loading={reply.isPending} disabled={!question.trim()} fullWidth />

      {result ? (
        <>
          <Card style={{ gap: spacing.md }}>
            <Txt variant="footnoteStrong" tone="secondary">{t('assistant.reply')}</Txt>
            <Txt variant="body" selectable>{result.reply}</Txt>
            <Button title={t('common.copy')} size="S" variant="secondary" onPress={() => copy(result.reply)} />
          </Card>
          {result.warnings.map((w) => <Banner key={w} text={w} tone="warning" />)}
          <Txt variant="footnote" tone="tertiary">{t('assistant.replySendYourself')}</Txt>
        </>
      ) : null}
    </ScrollView>
  );
}
