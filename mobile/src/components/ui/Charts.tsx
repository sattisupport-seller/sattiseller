import { useState } from 'react';
import { Pressable, View, type GestureResponderEvent } from 'react-native';
import Svg, { Circle, Line, Path, Rect } from 'react-native-svg';

import { useTheme } from '@/theme/useTheme';

import { Txt } from './Text';

type LineProps = {
  values: number[];
  prev?: number[];
  labels: string[];
  height?: number;
  format: (v: number) => string;
  accessibilityLabel: string;
  color?: 'primary';
};

// Линейный график по дням: основная серия primary 2,5 pt с заливкой 12%, сравнение — пунктир (docs/design.md, 3.5 и 10.17).
export function LineChart({ values, prev, labels, height = 180, format, accessibilityLabel }: LineProps) {
  const { colors } = useTheme();
  const [width, setWidth] = useState(300);
  const [active, setActive] = useState<number | null>(null);
  const all = [...values, ...(prev ?? [])];
  const max = Math.max(1, ...all);
  const min = Math.min(0, ...all);
  const span = max - min || 1;
  const padX = 8;
  const padTop = 12;
  const padBottom = 20;
  const innerH = height - padTop - padBottom;
  const x = (i: number, n: number) => padX + (n <= 1 ? 0 : (i * (width - padX * 2)) / (n - 1));
  const y = (v: number) => padTop + innerH - ((v - min) / span) * innerH;

  const path = (arr: number[]) => arr.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i, arr.length).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const area = `${path(values)} L${x(values.length - 1, values.length).toFixed(1)},${y(min).toFixed(1)} L${x(0, values.length).toFixed(1)},${y(min).toFixed(1)} Z`;

  const onTouch = (e: GestureResponderEvent) => {
    const px = e.nativeEvent.locationX;
    const idx = Math.round(((px - padX) / (width - padX * 2)) * (values.length - 1));
    setActive(Math.max(0, Math.min(values.length - 1, idx)));
  };

  return (
    <View
      accessible
      accessibilityLabel={accessibilityLabel}
      onLayout={(e) => setWidth(e.nativeEvent.layout.width)}
    >
      <Pressable onPress={onTouch} onPressOut={() => setActive(null)} onLongPress={onTouch} delayLongPress={120} style={{ height }}>
        <Svg width={width} height={height}>
          {[0, 1, 2].map((k) => (
            <Line
              key={k}
              x1={padX}
              x2={width - padX}
              y1={padTop + (innerH * k) / 2}
              y2={padTop + (innerH * k) / 2}
              stroke={colors.divider}
              strokeWidth={1}
            />
          ))}
          {values.length > 1 ? <Path d={area} fill={colors.primary} fillOpacity={0.12} /> : null}
          {prev && prev.length > 1 ? (
            <Path d={path(prev)} stroke={colors.textTertiary} strokeWidth={2} strokeDasharray="4 4" fill="none" />
          ) : null}
          {values.length > 1 ? <Path d={path(values)} stroke={colors.primary} strokeWidth={2.5} fill="none" /> : null}
          {active !== null ? (
            <>
              <Line x1={x(active, values.length)} x2={x(active, values.length)} y1={padTop} y2={padTop + innerH} stroke={colors.textTertiary} strokeWidth={1} />
              <Circle cx={x(active, values.length)} cy={y(values[active])} r={4} fill={colors.primary} />
            </>
          ) : values.length ? (
            <Circle cx={x(values.length - 1, values.length)} cy={y(values[values.length - 1])} r={4} fill={colors.primary} />
          ) : null}
        </Svg>
      </Pressable>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', paddingHorizontal: padX }}>
        <Txt variant="caption" tone="tertiary">{labels[0] ?? ''}</Txt>
        <Txt variant="caption" tone="tertiary">{labels[labels.length - 1] ?? ''}</Txt>
      </View>
      {active !== null ? (
        <View style={{ position: 'absolute', top: 0, left: Math.min(Math.max(0, x(active, values.length) - 70), width - 150), backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 10, padding: 8 }}>
          <Txt variant="caption" tone="tertiary">{labels[active]}</Txt>
          <Txt variant="footnoteStrong" numeric>{format(values[active])}</Txt>
          {prev && prev[active] !== undefined ? <Txt variant="caption" tone="tertiary">прошлый период: {format(prev[active])}</Txt> : null}
        </View>
      ) : null}
    </View>
  );
}

type BarProps = { values: number[]; labels: string[]; height?: number; accessibilityLabel: string };

// Столбцы по дням: primary для количества (docs/design.md, 3.5).
export function BarChart({ values, labels, height = 120, accessibilityLabel }: BarProps) {
  const { colors, radii } = useTheme();
  const [width, setWidth] = useState(300);
  const max = Math.max(1, ...values);
  const gap = 3;
  const bw = values.length ? Math.max(3, (width - gap * (values.length - 1)) / values.length) : 0;
  return (
    <View accessible accessibilityLabel={accessibilityLabel} onLayout={(e) => setWidth(e.nativeEvent.layout.width)}>
      <Svg width={width} height={height}>
        {values.map((v, i) => {
          const h = Math.max(v > 0 ? 3 : 0, (v / max) * (height - 4));
          return (
            <Rect
              key={i}
              x={i * (bw + gap)}
              y={height - h}
              width={bw}
              height={h}
              rx={Math.min(radii.xs, bw / 2)}
              fill={v > 0 ? colors.primary : colors.surfaceAlt}
            />
          );
        })}
      </Svg>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
        <Txt variant="caption" tone="tertiary">{labels[0] ?? ''}</Txt>
        <Txt variant="caption" tone="tertiary">{labels[labels.length - 1] ?? ''}</Txt>
      </View>
    </View>
  );
}
