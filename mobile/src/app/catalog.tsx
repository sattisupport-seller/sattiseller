import { useState } from 'react';
import { ScrollView, View } from 'react-native';

import { Button } from '@/components/ui/Button';
import { Chip, Badge, Banner, Card, CoverageBar, GroupCard, ListRow, Stepper, Section, type Tone } from '@/components/ui/Surfaces';
import { Segmented, SearchField, TextField, MoneyField } from '@/components/ui/Inputs';
import { EmptyState, ErrorState, Skeleton, Sheet } from '@/components/ui/Overlays';
import { Txt, typography } from '@/components/ui/Text';
import { LineChart, BarChart } from '@/components/ui/Charts';
import { useI18n } from '@/i18n';
import { useTheme } from '@/theme/useTheme';
import { formatMoney, formatMoneyShort, formatPercentBp } from '@/lib/format';

// Каталог компонентов для разработки (docs/spec.md, задача 3). Виден только в режиме разработки.
export default function CatalogScreen() {
  const { t } = useI18n();
  const { colors, spacing } = useTheme();
  const [period, setPeriod] = useState<'today' | '7d' | '30d'>('7d');
  const [search, setSearch] = useState('');
  const [money, setMoney] = useState('2800');
  const [sheet, setSheet] = useState(false);
  const tones: Tone[] = ['success', 'danger', 'warning', 'info', 'neutral', 'primary', 'outline'];
  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 80, gap: spacing.lg }} style={{ backgroundColor: colors.bg }}>
      <Section title="Типографика">
        {(Object.keys(typography) as (keyof typeof typography)[]).map((v) => (
          <Txt key={v} variant={v}>{v} · Прибыль 182 400 ₸</Txt>
        ))}
      </Section>
      <Section title="Кнопки">
        <Button title="Главная L" onPress={() => undefined} />
        <Button title="Вторичная M" variant="secondary" size="M" onPress={() => undefined} />
        <Button title="Контурная S" variant="outline" size="S" onPress={() => undefined} />
        <Button title="Текстовая" variant="text" onPress={() => undefined} />
        <Button title="Удалить" variant="destructive" onPress={() => undefined} />
        <Button title="Недоступна" disabled onPress={() => undefined} />
        <Button title="Загрузка" loading onPress={() => undefined} />
      </Section>
      <Section title="Чипы и бейджи">
        <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
          <Chip label="Все" selected onPress={() => undefined} count={40} />
          <Chip label="В минус" selected={false} onPress={() => undefined} count={1} />
        </View>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
          {tones.map((tone) => <Badge key={tone} label={tone} tone={tone} />)}
        </View>
      </Section>
      <Section title="Поля">
        <TextField label="Email" value="aidana@example.kz" onChangeText={() => undefined} />
        <MoneyField label="Закупка" value="1200,505" onChangeText={() => undefined} error="Больше двух знаков после запятой" />
        <SearchField value={search} onChangeText={setSearch} placeholder="Название или артикул" />
        <Segmented value={period} options={[{ value: 'today', label: 'Сегодня' }, { value: '7d', label: '7 дн' }, { value: '30d', label: '30 дн' }]} onChange={setPeriod} />
      </Section>
      <Section title="Баннеры и покрытие">
        <Banner text="Это демо-магазин: данные выдуманы" tone="primary" action="Подробнее" onAction={() => undefined} />
        <Banner text="Данные обновлялись 2 дня назад" tone="warning" />
        <Banner text="Не удалось обновить данные" tone="danger" action="Повторить" onAction={() => undefined} />
        <CoverageBar bp={9800} />
        <CoverageBar bp={8200} />
        <CoverageBar bp={5000} />
      </Section>
      <Section title="Списки">
        <GroupCard>
          <ListRow title="Беспроводные наушники TWS" subtitle="D012 · 52 шт." right={<Txt variant="headline" tone="success">{formatMoney(9620000, 'auto')}</Txt>} onPress={() => undefined} />
          <ListRow title="Детский рюкзак с подсветкой" subtitle="D023 · 12 шт." badges={<Badge label="В минус" tone="danger" />} right={<Txt variant="headline" tone="danger">{formatMoney(-860000)}</Txt>} last />
        </GroupCard>
      </Section>
      <Section title="Графики">
        <Card>
          <LineChart values={[18, 25, 22, 31, 28, 33, 36]} prev={[15, 22, 20, 24, 27, 26, 30]} labels={['13 нояб.', '19 нояб.']} format={(v) => formatMoney(v * 100, 'auto')} accessibilityLabel="Прибыль за 7 дней" />
          <BarChart values={[3, 4, 2, 5, 0, 6, 7]} labels={['13', '19']} accessibilityLabel="Продажи по дням" />
        </Card>
      </Section>
      <Section title="Шаги и состояния">
        <Stepper step={2} total={4} />
        <Skeleton height={20} width="60%" />
        <ErrorState title="Не удалось загрузить данные" code="7F3A" />
        <EmptyState title="За этот период заказов нет" action="Выбрать другой период" onAction={() => undefined} />
        <Txt variant="footnote" tone="secondary">{formatMoneyShort(124530000, 'kpi')} · {formatPercentBp(-1280, 'auto')}</Txt>
      </Section>
      <Button title="Открыть лист" onPress={() => setSheet(true)} />
      <Sheet visible={sheet} onClose={() => setSheet(false)} title="Лист снизу">
        <Txt variant="body">Содержимое листа</Txt>
      </Sheet>
    </ScrollView>
  );
}
