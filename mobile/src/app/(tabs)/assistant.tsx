import { useRouter } from 'expo-router';
import { CircleAlert, FileText, Flag, History, MessageCircle, Send, Sparkles, SquarePen, ThumbsDown, ThumbsUp } from 'lucide-react-native';
import { useRef, useState, type ReactNode } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, TextInput, View, type ScrollViewInstance } from 'react-native';

import { ApiError, request } from '@/api/client';
import {
  useAIConsent, useAIQuota, useAsk, useConversations, useDeleteConversation, useFeedback,
} from '@/api/hooks';
import type { AskAnswer } from '@/api/types';
import { Button } from '@/components/ui/Button';
import { TabHeader } from '@/components/ui/Header';
import { IconButton } from '@/components/ui/IconButton';
import { Badge, Banner, Chip, GroupCard, ListRow, Section, type Tone } from '@/components/ui/Surfaces';
import { Txt } from '@/components/ui/Text';
import { Sheet, useToast } from '@/components/ui/Overlays';
import { useSession } from '@/session/SessionProvider';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';
import { formatTimeAlmaty } from '@/lib/format';

type Msg =
  | { id: string; role: 'user'; text: string }
  | { id: string; role: 'assistant'; answer: AskAnswer };

const EXAMPLES = [
  'Почему упала прибыль за последние 14 дней?',
  'Какие товары в минус?',
  'Для каких товаров не заполнена закупка?',
  'Сколько заказов вчера?',
];

// Помощник (docs/design.md, 12.13): ответы с основаниями, согласие перед первым вопросом, жалоба на ответ.
export default function AssistantScreen() {
  const { t } = useI18n();
  const { colors, spacing, radii } = useTheme();
  const router = useRouter();
  const toast = useToast();
  const { shopId, isDemo } = useSession();
  const quota = useAIQuota(shopId);
  const consent = useAIConsent();
  const ask = useAsk(shopId);
  const feedback = useFeedback();
  const conversations = useConversations(shopId);
  const deleteConv = useDeleteConversation(shopId);

  const [messages, setMessages] = useState<Msg[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [consentOpen, setConsentOpen] = useState(false);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [flagTurn, setFlagTurn] = useState<string | null>(null);
  const [limitHit, setLimitHit] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [lastQuestion, setLastQuestion] = useState<string | null>(null);
  const scrollRef = useRef<ScrollViewInstance>(null);

  const hasChat = messages.length > 0;
  const remaining = quota.data?.remaining ?? quota.data?.limit ?? 20;
  const consentActive = quota.data?.consent_active ?? false;

  const send = async (question: string, consentJustGiven = false) => {
    const q = question.trim();
    if (!q) return;
    if (!consentActive && !consentJustGiven) {
      setPendingQuestion(q);
      setConsentOpen(true);
      return;
    }
    setFailed(null);
    setLimitHit(false);
    setLastQuestion(q);
    setInput('');
    setMessages((m) => [...m, { id: `u-${Date.now()}`, role: 'user', text: q }]);
    try {
      const res = await ask.mutateAsync({ question: q, conversationId });
      setConversationId(res.conversationId);
      setMessages((m) => [...m, { id: res.turnId, role: 'assistant', answer: res }]);
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 120);
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) setLimitHit(true);
      else if (e instanceof ApiError && e.status === 403) {
        setPendingQuestion(q);
        setConsentOpen(true);
      } else setFailed(t('assistant.failed'));
    }
  };

  const allowConsent = async () => {
    try {
      await consent.mutateAsync(true);
      setConsentOpen(false);
      const q = pendingQuestion;
      setPendingQuestion(null);
      if (q) await send(q, true);
    } catch {
      setFailed(t('assistant.failed'));
    }
  };

  const giveFeedback = (turnId: string, kind: 'up' | 'down' | 'flag', reason?: string) => {
    if (!shopId) return;
    feedback.mutate({ shop_id: shopId, turn_id: turnId, kind, reason });
    if (kind === 'flag') toast.show(t('assistant.flagSent'));
  };

  const startNew = () => {
    setMessages([]);
    setConversationId(null);
    setLimitHit(false);
    setFailed(null);
  };

  const openConversation = async (id: string) => {
    setHistoryOpen(false);
    const conv = await request<{ id: string; turns: { id: string; question: string; answer: AskAnswer }[] }>(
      `/ai/conversations/${id}`,
    );
    setConversationId(id);
    setMessages(conv.turns.flatMap((turn) => [
      { id: `${turn.id}-q`, role: 'user' as const, text: turn.question },
      { id: turn.id, role: 'assistant' as const, answer: turn.answer },
    ]));
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: colors.bg }} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={90}>
      <ScrollView
        ref={scrollRef}
        contentContainerStyle={{ paddingHorizontal: spacing.lg, paddingBottom: spacing.lg, paddingTop: spacing.sm }}
        keyboardShouldPersistTaps="handled"
      >
        <TabHeader
          title={t('assistant.title')}
          subtitle={<Txt variant="subhead" tone="tertiary">{t('assistant.subtitle')}</Txt>}
          right={
            <>
              <IconButton label={t('assistant.history')} onPress={() => setHistoryOpen(true)}>
                <History size={22} color={colors.textSecondary} />
              </IconButton>
              <IconButton label={t('assistant.newDialog')} onPress={startNew}>
                <SquarePen size={22} color={colors.textSecondary} />
              </IconButton>
            </>
          }
        />

        {isDemo ? <Txt variant="footnote" tone="tertiary">{t('assistant.demoNote')}</Txt> : null}

        {!hasChat ? (
          <>
            <View style={{ gap: spacing.md, marginTop: spacing.md }}>
              <ActionCard icon={<Sparkles size={22} color={colors.onPrimarySoft} />} title={t('assistant.cardAsk')} onPress={() => setInput('')} />
              <ActionCard icon={<FileText size={22} color={colors.onPrimarySoft} />} title={t('assistant.cardProduct')} onPress={() => router.push('/assistant/product-draft')} />
              <ActionCard icon={<MessageCircle size={22} color={colors.onPrimarySoft} />} title={t('assistant.cardReply')} onPress={() => router.push('/assistant/reply-draft')} />
            </View>
            <Section title={t('assistant.examples')}>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }}>
                {EXAMPLES.map((e) => (
                  <Chip key={e} label={e} selected={false} onPress={() => send(e)} />
                ))}
              </View>
            </Section>
          </>
        ) : null}

        <View style={{ gap: spacing.md, marginTop: spacing.md }}>
          {messages.map((m) =>
            m.role === 'user' ? (
              <View
                key={m.id}
                style={{ alignSelf: 'flex-end', maxWidth: '80%', backgroundColor: colors.primaryButton, borderRadius: 20, borderBottomRightRadius: 6, paddingVertical: 12, paddingHorizontal: 14 }}
              >
                <Txt variant="body" tone="onPrimary">{m.text}</Txt>
              </View>
            ) : (
              <AnswerCard
                key={m.id}
                answer={m.answer}
                onUp={() => giveFeedback(m.id, 'up')}
                onDown={() => giveFeedback(m.id, 'down')}
                onFlag={() => setFlagTurn(m.id)}
              />
            ),
          )}
          {ask.isPending ? (
            <View style={{ alignSelf: 'flex-start', backgroundColor: colors.surface, borderRadius: 20, borderBottomLeftRadius: 6, borderWidth: 1, borderColor: colors.border, padding: 14 }}>
              <Txt variant="footnote" tone="secondary">{t('assistant.typing')}</Txt>
            </View>
          ) : null}
          {failed ? (
            <Banner
              text={failed}
              tone="danger"
              action={t('common.retry')}
              onAction={() => (lastQuestion ? send(lastQuestion) : undefined)}
            />
          ) : null}
          {limitHit ? <Banner text={t('assistant.limit')} tone="warning" action={t('assistant.openReports')} onAction={() => router.push('/(tabs)')} /> : null}
        </View>
      </ScrollView>

      <View style={{ paddingHorizontal: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing.sm, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.divider, gap: spacing.sm }}>
        {hasChat ? (
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
            {EXAMPLES.slice(0, 3).map((e) => <Chip key={e} label={e} selected={false} onPress={() => send(e)} />)}
          </ScrollView>
        ) : null}
        <Txt variant="footnote" tone={remaining <= 5 ? 'warning' : 'tertiary'}>{t('assistant.remaining', { count: remaining })}</Txt>
        <View style={{ flexDirection: 'row', alignItems: 'flex-end', gap: spacing.sm }}>
          <View style={{ flex: 1, minHeight: 44, maxHeight: 120, backgroundColor: colors.surfaceAlt, borderRadius: radii.xl, paddingHorizontal: spacing.lg, justifyContent: 'center' }}>
            <TextInput
              accessibilityLabel={t('assistant.placeholder')}
              value={input}
              onChangeText={setInput}
              placeholder={t('assistant.placeholder')}
              placeholderTextColor={colors.textTertiary}
              multiline
              maxLength={500}
              style={{ color: colors.textPrimary, fontFamily: undefined, fontSize: 16, paddingVertical: 10 }}
            />
          </View>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={t('common.apply')}
            disabled={!input.trim() || ask.isPending}
            onPress={() => send(input)}
            style={{ width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center', backgroundColor: input.trim() ? colors.primaryButton : colors.surfaceAlt }}
          >
            <Send size={20} color={input.trim() ? colors.onPrimary : colors.textDisabled} />
          </Pressable>
        </View>
      </View>

      <Sheet visible={consentOpen} onClose={() => setConsentOpen(false)} title={t('assistant.consentTitle')}>
        <Txt variant="body" tone="secondary">{t('assistant.consentBody', { service: quota.data ? 'Satti AI' : '' })}</Txt>
        <Button title={t('assistant.allow')} onPress={allowConsent} loading={consent.isPending} fullWidth />
        <Button title={t('assistant.notNow')} variant="text" onPress={() => setConsentOpen(false)} fullWidth />
      </Sheet>

      <Sheet visible={historyOpen} onClose={() => setHistoryOpen(false)} title={t('assistant.history')}>
        {conversations.data?.items.length ? (
          <GroupCard>
            {conversations.data.items.map((c, i, arr) => (
              <ListRow
                key={c.id}
                title={c.title}
                subtitle={formatTimeAlmaty(c.created_at)}
                right={
                  <Pressable accessibilityRole="button" accessibilityLabel={t('assistant.deleteDialog')} onPress={() => deleteConv.mutate(c.id)} hitSlop={8}>
                    <Txt variant="footnote" tone="danger">{t('common.delete')}</Txt>
                  </Pressable>
                }
                onPress={() => openConversation(c.id)}
                last={i === arr.length - 1}
              />
            ))}
          </GroupCard>
        ) : (
          <Txt variant="body" tone="secondary">{t('assistant.emptyHistory')}</Txt>
        )}
      </Sheet>

      <Sheet visible={!!flagTurn} onClose={() => setFlagTurn(null)} title={t('assistant.flagTitle')}>
        {[
          { key: 'wrong_numbers', label: t('assistant.flagWrong') },
          { key: 'rude', label: t('assistant.flagRude') },
          { key: 'other', label: t('assistant.flagOther') },
        ].map((r) => (
          <Button
            key={r.key}
            title={r.label}
            variant="outline"
            fullWidth
            onPress={() => {
              if (flagTurn) giveFeedback(flagTurn, 'flag', r.key);
              setFlagTurn(null);
            }}
          />
        ))}
      </Sheet>
    </KeyboardAvoidingView>
  );
}

function ActionCard({ icon, title, onPress }: { icon: ReactNode; title: string; onPress: () => void }) {
  const { colors, spacing, radii } = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={title}
      onPress={onPress}
      style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.md, backgroundColor: colors.surface, borderRadius: radii.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.lg }}
    >
      <View style={{ width: 40, height: 40, borderRadius: 20, backgroundColor: colors.primarySoft, alignItems: 'center', justifyContent: 'center' }}>{icon}</View>
      <Txt variant="headline" style={{ flex: 1 }}>{title}</Txt>
    </Pressable>
  );
}

function AnswerCard({ answer, onFlag, onUp, onDown }: { answer: AskAnswer; onFlag: () => void; onUp: () => void; onDown: () => void }) {
  const { t } = useI18n();
  const { colors, spacing, radii } = useTheme();
  const router = useRouter();
  const tone: Tone = answer.confidence === 'high' ? 'success' : answer.confidence === 'medium' ? 'warning' : 'danger';
  const level = answer.confidence === 'high' ? t('assistant.levelHigh') : answer.confidence === 'medium' ? t('assistant.levelMedium') : t('assistant.levelLow');
  const action = answer.suggestedActions[0];
  return (
    <View style={{ alignSelf: 'stretch', backgroundColor: colors.surface, borderRadius: radii.xl, borderBottomLeftRadius: 6, borderWidth: 1, borderColor: colors.border, padding: spacing.lg, gap: spacing.md }}>
      <Txt variant="footnote" tone="secondary">{t('assistant.aiLabel')}</Txt>
      <Txt variant="body">{answer.renderedAnswer}</Txt>

      {answer.evidence.length > 0 ? (
        <View style={{ gap: 6 }}>
          <Txt variant="footnoteStrong" tone="secondary">{t('assistant.basis')}</Txt>
          {answer.evidence.map((e) => (
            <View key={e.factId} style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
              <Txt variant="subhead" tone="secondary">{e.label}</Txt>
              <Txt variant="headline" numeric>{e.text ?? String(e.value)}</Txt>
            </View>
          ))}
        </View>
      ) : null}

      {answer.missingData.length > 0 ? <Banner text={answer.missingData.join('. ')} tone="warning" /> : null}

      {answer.confidence ? (
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm, flexWrap: 'wrap' }}>
          <Badge label={t('assistant.confidence', { level })} tone={tone} icon={<CircleAlert size={12} color={colors.textSecondary} />} />
          {answer.confidenceReason ? <Txt variant="footnote" tone="tertiary">{answer.confidenceReason}</Txt> : null}
        </View>
      ) : null}

      <Txt variant="footnote" tone="tertiary">{t('assistant.dataAt', { time: formatTimeAlmaty(answer.dataAsOf) })}</Txt>

      {action ? (
        <View style={{ flexDirection: 'row' }}>
          <Button
            title={action.type === 'open_tax_settings' ? t('assistant.openTax') : t('assistant.openProduct')}
            size="S"
            variant="secondary"
            onPress={() => {
              if (action.type === 'open_tax_settings') router.push('/settings/tax');
              else if (action.entityId) router.push(`/product/${action.entityId}`);
            }}
          />
        </View>
      ) : null}

      <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderTopWidth: 1, borderTopColor: colors.divider, paddingTop: spacing.md }}>
        <Txt variant="footnote" tone="tertiary" style={{ flex: 1 }}>{t('assistant.helpful')}</Txt>
        <IconButton label={t('assistant.helpfulYes')} onPress={onUp}><ThumbsUp size={20} color={colors.textTertiary} /></IconButton>
        <IconButton label={t('assistant.helpfulNo')} onPress={onDown}><ThumbsDown size={20} color={colors.textTertiary} /></IconButton>
        <IconButton label={t('assistant.flag')} onPress={onFlag}><Flag size={20} color={colors.textTertiary} /></IconButton>
      </View>
    </View>
  );
}
