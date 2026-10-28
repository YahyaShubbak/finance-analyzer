import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { PointsMonth } from "../../types";
import { formatMonth, getFormatLocale } from "../../lib/format";
import { useI18n } from "../../i18n/useI18n";

/** Points earned (up) and redeemed (down) per month, and the standing as a line. */
export function PointsChart({ months }: { months: PointsMonth[] }) {
  const { t } = useI18n();
  const number = new Intl.NumberFormat(getFormatLocale());
  const data = months.map((m) => ({ month: formatMonth(m.month), earned: m.earned, redeemed: m.redeemed, balance: m.balance }));
  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 0 }} stackOffset="sign">
        <CartesianGrid strokeDasharray="3 3" stroke="#E1E4E9" vertical={false} />
        <XAxis dataKey="month" tick={{ fontSize: 12, fill: "#5B6270" }} axisLine={{ stroke: "#E1E4E9" }} tickLine={false} />
        <YAxis yAxisId="flow" tick={{ fontSize: 12, fill: "#5B6270" }} axisLine={false} tickLine={false} width={56}
          tickFormatter={(v) => number.format(Number(v))} />
        <YAxis yAxisId="balance" orientation="right" tick={{ fontSize: 12, fill: "#5B6270" }} axisLine={false} tickLine={false}
          width={56} tickFormatter={(v) => number.format(Number(v))} />
        <Tooltip formatter={(value) => number.format(Number(value))} contentStyle={{ borderRadius: 8, border: "1px solid #E1E4E9", fontSize: 13 }} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar yAxisId="flow" dataKey="earned" stackId="flow" name={t("points.earned")} fill="#1E7A4C" radius={[3, 3, 0, 0]} />
        <Bar yAxisId="flow" dataKey="redeemed" stackId="flow" name={t("points.redeemed")} fill="#A8431E" radius={[3, 3, 0, 0]} />
        <Line yAxisId="balance" dataKey="balance" name={t("points.balance")} stroke="#2F5DA8" strokeWidth={2} dot={false} type="monotone" />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
