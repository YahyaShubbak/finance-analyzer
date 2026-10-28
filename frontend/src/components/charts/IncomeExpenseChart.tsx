import { Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { MonthlyPoint } from "../../types";
import { formatMonth, formatMoney } from "../../lib/format";
import { useI18n } from "../../i18n/useI18n";

/** Income and expenses per month. With `onSelectMonth`, a click on a month
 * (anywhere in its column) chooses it; the chosen one stays highlighted. */
export function IncomeExpenseChart({
  data,
  currency = "EUR",
  selectedMonth,
  onSelectMonth,
}: {
  data: MonthlyPoint[];
  currency?: string;
  selectedMonth?: string | null;
  onSelectMonth?: (month: string) => void;
}) {
  const { t } = useI18n();
  const chartData = data.map((p) => ({
    key: p.month,
    month: formatMonth(p.month),
    Income: p.income_minor / 100,
    Expenses: p.expenses_minor / 100,
  }));
  const dimmed = (key: string) => Boolean(selectedMonth) && key !== selectedMonth;

  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart
        data={chartData}
        margin={{ top: 8, right: 8, left: 8, bottom: 0 }}
        onClick={(state) => {
          const index = Number(state?.activeIndex);
          if (onSelectMonth && Number.isInteger(index) && chartData[index]) onSelectMonth(chartData[index].key);
        }}
        style={onSelectMonth ? { cursor: "pointer" } : undefined}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="#E1E4E9" vertical={false} />
        <XAxis dataKey="month" tick={{ fontSize: 12, fill: "#5B6270" }} axisLine={{ stroke: "#E1E4E9" }} tickLine={false} />
        <YAxis tick={{ fontSize: 12, fill: "#5B6270" }} axisLine={false} tickLine={false} width={56} />
        <Tooltip
          formatter={(value) => formatMoney(Math.round(Number(value) * 100), currency)}
          contentStyle={{ borderRadius: 8, border: "1px solid #E1E4E9", fontSize: 13 }}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="Income" name={t("stats.income")} fill="#1E7A4C" radius={[3, 3, 0, 0]}>
          {chartData.map((d) => (
            <Cell key={d.key} fillOpacity={dimmed(d.key) ? 0.35 : 1} />
          ))}
        </Bar>
        <Bar dataKey="Expenses" name={t("stats.expenses")} fill="#A8431E" radius={[3, 3, 0, 0]}>
          {chartData.map((d) => (
            <Cell key={d.key} fillOpacity={dimmed(d.key) ? 0.35 : 1} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
