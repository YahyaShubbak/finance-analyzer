import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { MonthlyForecastPoint } from "../../types";
import { formatMonth, formatMoney } from "../../lib/format";
import { useI18n } from "../../i18n/useI18n";

export function ForecastChart({ data, currency = "EUR" }: { data: MonthlyForecastPoint[]; currency?: string }) {
  const { t } = useI18n();
  const chartData = data.map((p) => ({
    month: formatMonth(p.month),
    "Projected net": p.projected_net_minor / 100,
  }));

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={chartData} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#E1E4E9" vertical={false} />
        <XAxis dataKey="month" tick={{ fontSize: 12, fill: "#5B6270" }} axisLine={{ stroke: "#E1E4E9" }} tickLine={false} />
        <YAxis
          domain={[(min: number) => Math.min(0, min), (max: number) => Math.max(0, max)]}
          tick={{ fontSize: 12, fill: "#5B6270" }} axisLine={false} tickLine={false} width={64} />
        <Tooltip
          formatter={(value) => formatMoney(Math.round(Number(value) * 100), currency)}
          contentStyle={{ borderRadius: 8, border: "1px solid #E1E4E9", fontSize: 13 }}
        />
        <Bar dataKey="Projected net" name={t("chart.projectedNet")} radius={[3, 3, 0, 0]}>
          {chartData.map((d, i) => (
            <Cell key={i} fill={d["Projected net"] >= 0 ? "#1E7A4C" : "#A8431E"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
